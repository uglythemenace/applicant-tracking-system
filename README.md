# Rolebeam Applicant Tracking System

A candidate careers portal and recruiter workspace for posting jobs, receiving applications, and moving candidates through a hiring pipeline.

## Priority fixes in this copy

- Public job endpoints return open, unexpired jobs only. Individual job pages show clear details and search-engine structured job data.
- Staff can archive closed jobs from the main list and restore them later; archiving preserves their application history.
- The staff workspace combines job management, a candidate pipeline, upcoming interview and new-application counts, search, private notes, and the activity log under one sign-in.
- Staff can open a keyboard command palette with Cmd/Ctrl+K to search candidates, jump to jobs, and review the work that needs attention.
- The recruiter workspace uses a draggable hiring board with a list-view fallback and a candidate profile drawer for résumé access, private notes, interview details, and status changes.
- Applications require a non-blank name and a valid email; résumé links must use HTTP or HTTPS. The backend rejects applications to closed or missing jobs.
- Staff can permanently delete an individual application and its related notes, status history, identity claims, and uploaded résumé. Résumé object cleanup is queued and retried if storage is temporarily unavailable; the deletion audit stores only the actor and time.
- Once the retention secret is configured, finalized applications (accepted, rejected, or withdrawn) are automatically deleted after 12 months from their final status date.
- Tracking lookups use a JSON POST request instead of putting the email and code in the request URL. New tracking links no longer put the code in the page address.
- Confirmation messages can open a private applicant status dashboard with a random tracking link; the email-and-code lookup remains available as a fallback.
- Applicants can view recorded status changes and interview details on their private tracking dashboard.
- Form labels, error announcements, contrast, mobile navigation, and small-screen job cards were improved.
- The site was redesigned for everyday readers: large text, big buttons, plain words, confirmation before Accept, Reject and Close, a phone-friendly layout, and a friendly "server is waking up" message. The public pages use the shared `Frontend/static/style.css` stylesheet.
- Applicant email and optional consent-based SMS notifications are supported. Phone and email reuse are blocked by a database trigger, with a ten-minute cooldown after repeated duplicate attempts.
- AI résumé parsing and candidate scoring, a unified team inbox, trigger-based messaging, and Google or Outlook calendar sync are not connected yet; the interface does not claim those integrations are active.

## Important: deploy the frontend and backend together

The tracking API uses **POST** so the applicant's email and tracking code do not appear in the request URL. Deploy the backend and frontend close together; older deployed versions may not work with the updated tracking flow. Other clients that call the tracking endpoint must also use POST.

Nothing in this copy deploys automatically. Apply the Supabase SQL migrations in `Backend/migrations/` in date order before deploying. The `20261102_initial_application_schema.sql` migration creates the core tables without copying production records. The later migrations add phone and job archiving, public job details, candidate status history, interview details, private notes, the admin activity log, private résumé storage, data deletion, automated retention, and private tracking tokens. `20261110_tighten_identity_guard_and_index.sql` closes direct API access to the identity trigger function and indexes the application-to-job foreign key. Apply these migrations to staging first; the existing email-and-code tracking flow remains available for fallback.

The staff page now uses individual Supabase Auth accounts. In Supabase, create an Auth user for each staff member, then set `SUPABASE_ANON_KEY` and a comma-separated `ADMIN_EMAILS` allowlist in Render. Keep `SUPABASE_KEY` as the service-role key used by the backend; never expose that key to the frontend. The `ADMIN_API_KEY` remains only as a fallback secret for duplicate-attempt hash generation, not as staff login. Set `PUBLIC_CONTACT_EMAIL` in Render to show the hiring team's contact address on `/contact`.

To enable the 12-month applicant retention schedule, generate a unique random `RETENTION_PURGE_TOKEN`. Set matching environment-specific values in the Render backend and in GitHub Actions environments: `staging` for the `redesign` branch and `production` for `main`. Use different random values. The workflow targets staging on `redesign` and production on `main`, and can also be run manually from GitHub Actions. It purges only accepted, rejected, or withdrawn applications whose `status_updated_at` is at least 12 months old. Résumé files are queued for storage cleanup and retried by the backend. Do not reuse the Supabase service key or another existing secret for this token.

Email and SMS delivery configuration is documented below and can be completed separately. The application confirmation still displays the tracking code if a messaging provider is unavailable.

Email delivery can use either Resend with a verified domain or Gmail SMTP. Resend's test sender (`onboarding@resend.dev`) is not a production sender for arbitrary applicants. For Gmail, enable 2-Step Verification, create an App Password, and set `EMAIL_PROVIDER=smtp`, `SMTP_USERNAME`, and `SMTP_APP_PASSWORD` in Render; the code uses Gmail's secure SMTP connection. Google requires 2-Step Verification for App Passwords. Keep the app password in Render only, never in GitHub or chat. Alternatively, set `EMAIL_PROVIDER=resend`, `RESEND_API_KEY`, and `EMAIL_FROM` to an address on a domain verified with Resend. If the selected provider is not configured, applications still save and the tracking code remains on the confirmation page while the backend logs the configuration issue.

After deployment, verify that:

1. Apply the SQL migrations in order in Supabase. The Render backend needs `SUPABASE_URL`, the service-role `SUPABASE_KEY`, the public `SUPABASE_ANON_KEY`, `ADMIN_EMAILS`, and a strong `APPLICATION_COOLDOWN_SECRET`. Add `PUBLIC_CONTACT_EMAIL` for the contact page. Configure email or SMS provider variables separately when ready. **Never put real values in the frontend or commit them to GitHub.**
2. The Vercel project uses the repository root and serves `/Frontend/static/style.css` and `/Frontend/static/script.js` successfully.
3. The jobs page shows only open jobs, and the admin page can also show closed jobs after signing in.
4. In a **staging environment**, submit an application, save the on-screen tracking code, and confirm the applicant dashboard opens with the matching email and code. Reusing an email or phone should be rejected; repeated duplicate attempts should trigger the ten-minute cooldown.
5. In staging, change an applicant's status, schedule an interview, then confirm the applicant dashboard shows those updates. Confirm staff can search and sort applicants and that `/applications/` rejects requests without an approved staff sign-in.

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

While working on the `redesign` branch, `API_BASE` points to the separate staging backend at `https://applicant-tracking-system-1-0g5l.onrender.com`. Before merging the frontend branch into `main`, change it back to the production backend URL and deploy the matching frontend and backend changes together. Do not use real applicant data for staging checks.

For staging tracking links, the Render staging service has `FRONTEND_URL` set to the Vercel preview for `redesign`. When creating another staging service, set this before testing; the default points to production.

## Delivered on `redesign`

- `/admin` is the unified recruiter workspace; `/dashboard` and `/post-job` redirect there.
- Applicants can use private tracking links or the existing email-and-code fallback, with a timeline of status changes.
- The recruiter workspace includes Cmd/Ctrl+K quick actions and candidate pipeline actions.
- The recruiter view uses a dark theme; candidate pages use the Rolebeam beam identity.
- Applying is a single-screen flow with résumé first, inline validation, and immediate confirmation.
- Staging uses separate free-tier Render and Supabase projects. Keep real applicant data out of staging.

## Remaining work before real hiring

- Configure separate `RETENTION_PURGE_TOKEN` values on the staging and production Render services and in the matching GitHub Actions environments. Verify the staging workflow first. The retention workflow does not change provider-backup retention.
- Configure and verify email delivery so applicants can recover their tracking code from the receipt message.
- Run a human-paced application timing check against the under-60-second target. A local mock-browser submission passed, but it does not establish real applicant completion time.
- Add and verify MFA before relying on staff access for real hiring. Staff tokens are checked against Supabase; keep the service key backend-only.
- Review log settings and avoid recording tracking request bodies or applicant data. POST reduces URL exposure but does not prevent all logging.
- Add complete, accurate responsibilities and qualifications before publishing each role.
- After the core application flow feels effortless, consider AI résumé parsing and chat/SMS applying. Those integrations are not connected yet.
