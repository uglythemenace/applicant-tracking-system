# Learn2earn Applicant Tracking System

A simple careers site and FastAPI backend for posting jobs, receiving applications, and tracking application status.

## Priority fixes in this copy

- Public job endpoints now return **open** jobs only. The admin dashboard sends its existing admin key to retrieve open and closed jobs.
- The admin dashboard shows safe résumé links, resets counts when there are no applications, and has a sign-out button.
- Applications require a non-blank name and a valid email; résumé links must use HTTP or HTTPS. The backend rejects applications to closed or missing jobs.
- Tracking lookups use a JSON POST request instead of putting the email and code in the request URL. New tracking links no longer put the code in the page address.
- The tracking timeline highlights only the current status; it does not claim that earlier stages happened.
- Form labels, error announcements, contrast, mobile navigation, and small-screen job cards were improved.
- Tailwind CSS is compiled into `Frontend/static/tailwind.css` instead of loading the development CDN at runtime.

## Important: deploy the frontend and backend together

The tracking API changed from **GET** to **POST**. The old deployed frontend cannot track against the new backend, and the new frontend cannot track against the old backend. Deploy the backend and frontend close together and then test tracking; there can be a short interruption while the two deployments are updating. Other clients that call the old tracking endpoint must be updated too.

Nothing in this copy deploys automatically. Review the changes, commit them to your GitHub repository, and let Render and Vercel deploy the updated commit (or deploy it through your normal process). These changes do not require a new database column.

After deployment, verify that:

1. The Render backend installs the updated `Backend/requirements.txt` and has `SUPABASE_URL`, `SUPABASE_KEY`, and a strong `ADMIN_API_KEY` configured. **Never put these real values in the frontend or commit them to GitHub.**
2. The Vercel project uses the repository root and serves `/Frontend/static/tailwind.css` successfully.
3. The jobs page shows only open jobs, and the admin page can also show closed jobs after signing in.
4. In a **staging environment**, submit a test application, check its résumé link in admin, and use the tracking code to check its status.
5. Check that `GET /jobs/` without an admin key does not return closed jobs and `GET /applications/` without a key returns 401.

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

The frontend templates currently contain the deployed API URL. Change the URL in the templates when connecting to a separate local or staging backend.

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

## Rebuild CSS after changing HTML classes

The generated CSS file is committed so Vercel can serve it directly. From the repository root, run this command after adding or changing Tailwind classes:

```bash
npx --yes tailwindcss@3.4.17 -c tailwind.config.js -i Frontend/static/tailwind.input.css -o Frontend/static/tailwind.css --minify
```

## Remaining work before real hiring

- Add a privacy notice and a way to contact the hiring team. Decide how long applicant data is kept and how deletion requests are handled.
- Provide a secure way to recover a lost tracking code. This repository does not contain an automated confirmation-email sender; check any external email services separately.
- The admin still uses a shared key in browser session storage. For real applicant information, use individual accounts, session expiry, MFA, server-side authorization, rate limiting and audit logs. Review Supabase row-level security as well. These changes are not a complete security audit.
- Check log settings and avoid recording tracking request bodies or applicant data. POST reduces URL exposure but does not prevent all logging.
- Add real job details such as location, employment type and requirements; don't publish placeholder roles.
- The old `/dashboard` page uses an outdated unauthenticated flow, and `/post-job` currently rewrites to a missing file. Decide whether to retire, redirect, or rebuild these legacy pages.
