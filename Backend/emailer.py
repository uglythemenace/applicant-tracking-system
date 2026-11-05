import os
import html
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
import resend

resend.api_key = os.environ.get("RESEND_API_KEY", "")

EMAIL_PROVIDER = os.environ.get("EMAIL_PROVIDER", "resend").strip().lower()
FROM_ADDRESS = os.environ.get("EMAIL_FROM", "").strip()
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "").strip()
SMTP_APP_PASSWORD = os.environ.get("SMTP_APP_PASSWORD", "").replace(" ", "")
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "TalentFlow Careers").strip()
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
    message.set_content("This message contains your TalentFlow application update. Please view it in an HTML-capable email app.")
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
      <p style="color:#888;font-size:12px;margin-top:32px">TalentFlow Careers</p>
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
        f"TalentFlow: We received your application for {job_title}. "
        f"Tracking code: {code}. Check your status at {track_url} using your email and code. Reply STOP to stop texts."
    )
    return _send_sms(to, body)


def send_status_update(to: str, name: str, job_title: str, status: str, code: str) -> bool:
    name = html.escape(name or "there")
    job_title = html.escape(job_title)
    status = html.escape(status)
    track_url = f"{FRONTEND_URL}/track"
    body = _wrap(f"""
      <h2>Your application was updated</h2>
      <p>Hi {name}, there is news on your application for <b>{job_title}</b>.</p>
      <p>New status: <b>{status}</b></p>
      <p>Tracking code: {html.escape(code)}<br>
      <a href="{track_url}">Check your status</a></p>
    """)
    return _send(to, f"Update on your application: {job_title}", body)


def send_status_sms(to: str, job_title: str, status: str) -> bool:
    label = "accepted" if status.strip().lower() in {"accepted", "approved", "hired", "offer", "offered"} else "rejected"
    body = (
        f"TalentFlow update: Your application for {job_title} has been {label}. "
        "Check your email for details from the hiring team. Reply STOP to stop texts."
    )
    return _send_sms(to, body)
