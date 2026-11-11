import os
import html
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import resend

resend.api_key = os.environ.get("RESEND_API_KEY", "")

EMAIL_PROVIDER = os.environ.get("EMAIL_PROVIDER", "resend").strip().lower()
FROM_ADDRESS = os.environ.get("EMAIL_FROM", "").strip()
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "").strip()
SMTP_APP_PASSWORD = os.environ.get("SMTP_APP_PASSWORD", "").replace(" ", "")
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "Rolebeam Careers").strip()
try:
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
except ValueError:
    SMTP_PORT = 587
FRONTEND_URL = os.environ.get(
    "FRONTEND_URL", "https://applicant-tracking-system-frontend.vercel.app"
)
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "")


def _send(to: str, subject: str, body_html: str) -> bool:
    # Email problems must never break an application or a status change.
    if EMAIL_PROVIDER == "smtp":
        return _send_smtp(to, subject, body_html)
    if EMAIL_PROVIDER != "resend":
        print("Email skipped: EMAIL_PROVIDER must be 'resend' or 'smtp'")
        return False
    if not resend.api_key:
        print("Email skipped: RESEND_API_KEY is not set")
        return False
    if not FROM_ADDRESS:
        print("Email skipped: EMAIL_FROM must be set to an address on a Resend-verified domain")
        return False
    try:
        resend.Emails.send(
            {"from": FROM_ADDRESS, "to": [to], "subject": subject, "html": body_html}
        )
        return True
    except Exception as e:
        print("Email failed:", e)
        return False


def _send_smtp(to: str, subject: str, body_html: str) -> bool:
    if not SMTP_USERNAME or not SMTP_APP_PASSWORD:
        print("Email skipped: SMTP_USERNAME and SMTP_APP_PASSWORD are required for SMTP")
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((SMTP_FROM_NAME, SMTP_USERNAME))
    message["To"] = to
    message.set_content("This message contains your Rolebeam application update. Please view it in an HTML-capable email app.")
    message.add_alternative(body_html, subtype="html")

    try:
        context = ssl.create_default_context()
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=25) as server:
                server.login(SMTP_USERNAME, SMTP_APP_PASSWORD)
                refused = server.send_message(message)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=25) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                server.login(SMTP_USERNAME, SMTP_APP_PASSWORD)
                refused = server.send_message(message)
        if refused:
            print("SMTP email was refused by the mail server")
            return False
        return True
    except Exception:
        # Never log applicant addresses or SMTP credentials.
        print("SMTP email failed; check Gmail SMTP settings and the Render logs")
        return False


def _wrap(content: str) -> str:
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;color:#222;line-height:1.5">
      {content}
      <p style="color:#888;font-size:12px;margin-top:32px">Rolebeam Careers</p>
    </div>"""


def send_application_received(to: str, name: str, job_title: str, code: str) -> bool:
    name = html.escape(name or "there")
    job_title = html.escape(job_title)
    track_url = f"{FRONTEND_URL}/track"
    body = _wrap(f"""
      <h2>Application submitted successfully</h2>
      <p>Hi {name}, your application for <b>{job_title}</b> has been received and is waiting for review.</p>
      <p>Your tracking code is:</p>
      <p style="font-size:24px;font-weight:bold;letter-spacing:2px">{html.escape(code)}</p>
      <p>Use this code and your email address to check your status any time:</p>
      <p><a href="{track_url}">{track_url}</a></p>
    """)
    return _send(to, f"Application submitted successfully: {job_title}", body)


def _send_sms(to: str, body: str) -> bool:
    if not all((TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER)):
        print("SMS skipped: Twilio settings are not configured")
        return False
    try:
        from twilio.rest import Client

        Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN).messages.create(
            body=body,
            from_=TWILIO_FROM_NUMBER,
            to=to,
        )
        return True
    except Exception:
        # Do not write applicants' phone numbers or message contents to logs.
        print("SMS delivery request failed")
        return False


def send_application_received_sms(to: str, job_title: str, code: str) -> bool:
    track_url = f"{FRONTEND_URL}/track"
    body = (
        f"Rolebeam: We received your application for {job_title}. "
        f"Tracking code: {code}. Check your status at {track_url} using your email and code. Reply STOP to stop texts."
    )
    return _send_sms(to, body)


def _format_interview_time(interview_at: str | None, timezone_name: str | None) -> str | None:
    """Turn the saved interview timestamp into a readable local time, or None."""
    if not interview_at:
        return None
    try:
        moment = datetime.fromisoformat(str(interview_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    zone_label = "UTC"
    if timezone_name:
        try:
            moment = moment.astimezone(ZoneInfo(timezone_name))
            zone_label = timezone_name
        except Exception:
            moment = moment.astimezone(timezone.utc)
    else:
        moment = moment.astimezone(timezone.utc)
    return f"{moment.strftime('%A, %d %B %Y at %H:%M')} ({zone_label})"


def _interview_block(
    interview_at: str | None,
    interview_timezone: str | None,
    interview_location: str | None,
    interview_reschedule_url: str | None,
) -> str:
    """Interview details for the email, or a short note if none are set yet."""
    when = _format_interview_time(interview_at, interview_timezone)
    lines = []
    if when:
        lines.append(f"<b>When:</b> {html.escape(when)}")
    if interview_location:
        lines.append(f"<b>Where:</b> {html.escape(interview_location)}")
    if interview_reschedule_url:
        parsed = urlsplit(interview_reschedule_url)
        if parsed.scheme in {"http", "https"} and parsed.hostname:
            safe_url = html.escape(interview_reschedule_url, quote=True)
            lines.append(f'<b>Need a different time?</b> <a href="{safe_url}">Reschedule here</a>')
    if not lines:
        return "<p>The team will share the interview time and place soon. You will find them on your tracking page as soon as they are added.</p>"
    return '<p style="background:#f3f6fb;border-radius:8px;padding:12px 16px">' + "<br>".join(lines) + "</p>"


def _status_email_content(
    status: str,
    name: str,
    job_title: str,
    interview_block: str,
) -> tuple[str, str, str]:
    """Return (subject, heading, body HTML). The subject is plain text; the body is escaped."""
    subject_title = " ".join(job_title.split())
    name = html.escape(name or "there")
    job_title = html.escape(job_title)
    jobs_url = f"{FRONTEND_URL}/jobs"
    key = (status or "").strip().lower()
    if key == "pending":
        return (
            f"Your application is waiting for review: {subject_title}",
            "Your application is in the queue",
            f"<p>Hi {name}, your application for <b>{job_title}</b> is waiting for review. We will email you as soon as something changes.</p>",
        )
    if key == "reviewing":
        return (
            f"Your application is being reviewed: {subject_title}",
            "Someone is reading your application",
            f"<p>Hi {name}, the hiring team has started reviewing your application for <b>{job_title}</b>. Nothing else is needed from you right now.</p>",
        )
    if key == "interview":
        return (
            f"You are moving to the interview stage: {subject_title}",
            "You are moving to the interview stage",
            f"<p>Hi {name}, thank you for your interest. The hiring team would like to talk with you about <b>{job_title}</b>.</p>{interview_block}",
        )
    if key == "accepted":
        return (
            f"Good news about your application: {subject_title}",
            "Congratulations, you have been accepted",
            f"<p>Hi {name}, the hiring team has accepted your application for <b>{job_title}</b>. They will contact you about the next steps. You can also check your tracking page for details.</p>",
        )
    if key == "rejected":
        return (
            f"An update on your application: {subject_title}",
            "Thank you for applying",
            f"<p>Hi {name}, thank you for the time and care you put into applying for <b>{job_title}</b>.</p>"
            "<p>After careful consideration, the team has decided not to move forward with your application this time. "
            "We know this is not the news you hoped for, and we truly appreciate your interest.</p>"
            f'<p>You are welcome to look at our other open roles: <a href="{jobs_url}">{jobs_url}</a></p>',
        )
    if key == "withdrawn":
        return (
            f"Your application was withdrawn: {subject_title}",
            "Your application was withdrawn",
            f"<p>Hi {name}, your application for <b>{job_title}</b> has been withdrawn. You can apply again for any open role whenever you are ready.</p>",
        )
    # Unknown or future statuses still produce a clear, readable message.
    readable = html.escape(key.replace("_", " ").capitalize()) if key else "Updated"
    return (
        f"Update on your application: {subject_title}",
        "Your application was updated",
        f"<p>Hi {name}, there is news on your application for <b>{job_title}</b>.</p><p>New status: <b>{readable}</b></p>",
    )


def send_status_update(
    to: str,
    name: str,
    job_title: str,
    status: str,
    code: str,
    interview_at: str | None = None,
    interview_timezone: str | None = None,
    interview_location: str | None = None,
    interview_reschedule_url: str | None = None,
) -> bool:
    track_url = f"{FRONTEND_URL}/track"
    interview_block = _interview_block(
        interview_at, interview_timezone, interview_location, interview_reschedule_url
    )
    subject, heading, content = _status_email_content(status, name, job_title, interview_block)
    body = _wrap(f"""
      <h2>{heading}</h2>
      {content}
      <p style="margin-top:24px">Tracking code: <b>{html.escape(code)}</b><br>
      <a href="{track_url}">Check your application any time</a></p>
    """)
    return _send(to, subject, body)


def send_status_sms(to: str, job_title: str, status: str) -> bool:
    label = "accepted" if status.strip().lower() in {"accepted", "approved", "hired", "offer", "offered"} else "rejected"
    body = (
        f"Rolebeam update: Your application for {job_title} has been {label}. "
        "Check your email for details from the hiring team. Reply STOP to stop texts."
    )
    return _send_sms(to, body)
