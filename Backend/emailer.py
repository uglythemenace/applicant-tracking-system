import os
import html
import resend

resend.api_key = os.environ.get("RESEND_API_KEY", "")

FROM_ADDRESS = os.environ.get("EMAIL_FROM", "Learn2earn <onboarding@resend.dev>")
FRONTEND_URL = os.environ.get(
    "FRONTEND_URL", "https://applicant-tracking-system-frontend.vercel.app"
)


def _send(to: str, subject: str, body_html: str) -> None:
    # Email problems must never break an application or a status change.
    if not resend.api_key:
        print("Email skipped: RESEND_API_KEY is not set")
        return
    try:
        resend.Emails.send(
            {"from": FROM_ADDRESS, "to": [to], "subject": subject, "html": body_html}
        )
    except Exception as e:
        print("Email failed:", e)


def _wrap(content: str) -> str:
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;color:#222;line-height:1.5">
      {content}
      <p style="color:#888;font-size:12px;margin-top:32px">Learn2earn Careers</p>
    </div>"""


def send_application_received(to: str, name: str, job_title: str, code: str) -> None:
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
    _send(to, f"Application received: {job_title}", body)


def send_status_update(to: str, name: str, job_title: str, status: str, code: str) -> None:
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
    _send(to, f"Update on your application: {job_title}", body)