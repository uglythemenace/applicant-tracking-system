# Learn2earn Applicant Tracking System

A simple careers site and FastAPI backend for posting jobs, receiving applications, and tracking application status.

## Priority fixes in this copy

- Public job endpoints now return **open** jobs only. The admin dashboard sends its existing admin key to retrieve open and closed jobs.
- Staff can archive closed jobs from the main list and restore them later; archiving preserves their application history.
- The admin dashboard shows safe résumé links, resets counts when there are no applications, and has a sign-out button.
- Applications require a non-blank name and a valid email; résumé links must use HTTP or HTTPS. The backend rejects applications to closed or missing jobs.
- Tracking lookups use a JSON POST request instead of putting the email and code in the request URL. New tracking links no longer put the code in the page address.
- The tracking timeline highlights only the current status; it does not claim that earlier stages happened.
- Form labels, error announcements, contrast, mobile navigation, and small-screen job cards were improved.
- The site was redesigned for everyday readers: large text, big buttons, plain words, confirmation before Accept, Reject and Close, a phone-friendly layout, and a friendly "server is waking up" message. The public pages use the shared `Frontend/static/style.css` stylesheet.
- Applicant email and optional consent-based SMS notifications are supported. Phone and email reuse are blocked by a database trigger, with a ten-minute cooldown after repeated duplicate attempts.

## Important: deploy the frontend and backend together

The tracking API uses **POST** so the applicant's email and tracking code do not appear in the request URL. Deploy the backend and frontend close together; older deployed versions may not work with the updated tracking flow. Other clients that call the tracking endpoint must also use POST.

Nothing in this copy deploys automatically. Apply the Supabase SQL migrations in `Backend/migrations/` before deploying. `20261103_add_application_phone.sql` adds phone/text consent and database-side duplicate protection with cooldown storage. `20261103_add_job_archiving.sql` adds a reversible archive flag so jobs can be removed from public listings and the main admin list without deleting their applications. Then deploy the backend and frontend together. Set a strong `APPLICATION_COOLDOWN_SECRET`; the backend can use the existing `ADMIN_API_KEY` as a fallback so cooldown storage contains keyed hashes rather than raw applicant identifiers. Application and status emails use Resend; configure `RESEND_API_KEY`, a verified `EMAIL_FROM` address, and `FRONTEND_URL`. Optional SMS uses Twilio; configure `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and `TWILIO_FROM_NUMBER`. Applicants must explicitly opt in to texts. Twilio charges per message, and sender registration or recipient verification can be required by country/account type; see [Twilio's SMS setup guide](https://www.twilio.com/docs/messaging/tutorials/how-to-send-sms-messages). If email or SMS delivery is unavailable, the confirmation page still displays the tracking code.

Email delivery to applicants requires a sender address on a domain you own and have verified in Resend. The Resend test sender (`onboarding@resend.dev`) is not a production sender for arbitrary applicants. In Render, set `EMAIL_FROM` to a sender such as `Learn2earn Careers <careers@yourdomain.com>` after Resend verifies the domain, then redeploy the backend. If `EMAIL_FROM` is missing, applications still save and the tracking code remains on the confirmation page, while the backend logs why it skipped email.

After deployment, verify that:

1. The Render backend installs the updated `Backend/requirements.txt` and has `SUPABASE_URL`, `SUPABASE_KEY`, a strong `ADMIN_API_KEY`, `RESEND_API_KEY`, `EMAIL_FROM`, and `FRONTEND_URL` configured. `APPLICATION_COOLDOWN_SECRET` is recommended; otherwise the backend uses `ADMIN_API_KEY`. Add Twilio settings only when SMS sending is available. **Never put real values in the frontend or commit them to GitHub.**
2. The Vercel project uses the repository root and serves `/Frontend/static/style.css` and `/Frontend/static/script.js` successfully.
3. The jobs page shows only open jobs, and the admin page can also show closed jobs after signing in.
4. In a **staging environment**, submit a test application with email-only and text opt-in, confirm the tracking code delivery, and check the stored phone and consent in admin. Reusing either credential should be rejected; the fourth duplicate attempt should return a 10-minute cooldown.
5. In staging, change an opted-in applicant to accepted and rejected and confirm email and SMS status notices; also check the tracking POST with the correct email and code shows the dashboard, a wrong pair returns 404, `GET /jobs/` without an admin key does not return closed jobs, and `GET /applications/` without a key returns 401.

The frontend still points at your existing Render URL. Viewing or deploying it without changing that URL will use that backend. Do not submit fake applications to the live site; use a staging backend or the mock tests below.

## Run the backend locally

Use Python 3.10 or newer. From the repository root:

```bash
python -m venv .venv
# Activate it: source .venv/bin/activate (macOS/Linux)
# or .venv\Scripts\activate (Windows)
python -m pip install -r Backend/requirements.txt
```

Create `Backend/.env` with your own Supabase and admin values. See `Backend/.env.example` for the names. Keep it private. Start the API from the backend folder:

```bash
cd Backend
python -m uvicorn app:app --reload
```

The deployed API URL lives in one place, `API_BASE` at the top of `Frontend/static/script.js`. Change it there when connecting to a separate local or staging backend.

## Run the tests

The tests use **fake data and a fake database**; they do not call Supabase or submit real applications.

```bash
python -m pip install -r Backend/requirements.txt pytest httpx
python -m pytest tests/test_backend.py -q
```

Browser smoke tests require Node.js and Playwright:

```bash
npm install --no-save --no-package-lock playwright
npx playwright install chromium
node tests/test_frontend.cjs
```

On Linux, Playwright may also require browser system libraries; see `npx playwright install-deps chromium`.

## Changing how the site looks

All styling is in one plain file, `Frontend/static/style.css`, and all shared behavior (the menu, footer, staff sign-in, confirmation boxes, and the backend address `API_BASE`) is in `Frontend/static/script.js`. There is no build step. Edit a file, save it, and refresh the page.

## Remaining work before real hiring

- Add a privacy notice and a way to contact the hiring team. Decide how long applicant data is kept and how deletion requests are handled.
- Provide a secure way to recover a lost tracking code. Resend emails the code when the backend has a valid API key and sender address configured.
- The admin still uses a shared key in browser session storage. For real applicant information, use individual accounts, session expiry, MFA, server-side authorization, rate limiting and audit logs. Review Supabase row-level security as well. These changes are not a complete security audit.
- Check log settings and avoid recording tracking request bodies or applicant data. POST reduces URL exposure but does not prevent all logging.
- Add real job details such as location, employment type and requirements; don't publish placeholder roles.
- `/dashboard` is now a staff-only summary page that uses the same sign-in as `/admin`. `/post-job` redirects to `/admin`, where jobs are posted.
