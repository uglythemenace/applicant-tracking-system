import os
import html
import resend

resend.api_key = os.environ.get("RESEND_API_KEY", "")

FROM_ADDRESS = os.environ.get("EMAIL_FROM", "").strip()
FRONTEND_URL = os.environ.get(
    "FRONTEND_URL", "https://applicant-tracking-system-frontend.vercel.app"
)
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "")


def _send(to: str, subject: str, body_html: str) -> bool:
    # Email problems must never break an application or a status change.
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


def _wrap(content: str) -> str:
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;color:#222;line-height:1.5">
      {content}
      <p style="color:#888;font-size:12px;margin-top:32px">Learn2earn Careers</p>
    </div>"""


def send_application_received(to: str, name: str, job_title: str, code: str) -> bool:
    name = html.escape(name or "there")
    job_title = html.escape(job_title)
    track_url = f"{FRONTEND_URL}/track"
    body = _wrap(f"""
      <h2>We got your application</h2>
      <p>Hi {name}, thanks for applying for <b>{job_title}</b>.</p>
      <p>Your tracking code is:</p>
      <p style="font-size:24px;font-weight:bold;letter-spacing:2px">{html.escape(code)}</p>
      <p>Use this code and your email address to check your status any time:</p>
      <p><a href="{track_url}">{track_url}</a></p>
    """)
    return _send(to, f"Application received: {job_title}", body)


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
        f"Learn2earn: We received your application for {job_title}. "
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
        f"Learn2earn update: Your application for {job_title} has been {label}. "
        "Check your email for details from the hiring team. Reply STOP to stop texts."
    )
    return _send_sms(to, body)
