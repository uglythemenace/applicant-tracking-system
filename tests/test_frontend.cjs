/** Browser smoke tests. A local server and fake API are used; no real
 * candidate information or production requests are sent. */
const http = require('http');
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
// Track the backend address exactly as the pages use it, so the mock never drifts.
const API_BASE = fs.readFileSync(path.join(root, 'Frontend/static/script.js'), 'utf8').match(/const API_BASE = "([^"]+)"/)[1];
const STAFF_TOKEN = 'MOCK-STAFF-TOKEN';
const TRACK_TOKEN = '11111111-2222-3333-4444-555555555555';
const routes = {
  '/': 'Frontend/templates/home.html',
  '/jobs': 'Frontend/templates/jobs.html',
  '/job': 'Frontend/templates/job.html',
  '/apply': 'Frontend/templates/index.html',
  '/track': 'Frontend/templates/track.html',
  '/admin': 'Frontend/templates/admin.html',
  '/privacy': 'Frontend/templates/privacy.html',
  '/contact': 'Frontend/templates/contact.html',
  '/Frontend/static/style.css': 'Frontend/static/style.css',
  '/Frontend/static/script.js': 'Frontend/static/script.js',
};
const types = { css: 'text/css; charset=utf-8', js: 'text/javascript; charset=utf-8', html: 'text/html; charset=utf-8' };
const jobs = [
  { id: 1, title: 'Backend Developer (Python/FastAPI)', department: 'Engineering', location: 'Lagos', description: 'Build and maintain the APIs behind the platform.', status: 'approved', work_mode: 'hybrid', employment_type: 'full_time', created_at: '2026-10-01T00:00:00Z' },
  { id: 2, title: 'Frontend Developer', department: 'Engineering', location: 'Remote', description: 'Build the interfaces candidates and staff use.', status: 'approved', work_mode: 'remote', employment_type: 'full_time', created_at: '2026-10-02T00:00:00Z' },
  { id: 3, title: 'Closed test job', department: 'Product', description: 'A closed role that must stay hidden from visitors.', status: 'rejected', created_at: '2026-10-03T00:00:00Z' },
];
const daysAgo = (n) => new Date(Date.now() - n * 86400000).toISOString();
function seedApplicants() {
  return [
    { id: 1, job_id: 1, candidate_name: 'Test Candidate', email: 'test@example.com', status: 'pending', resume_url: 'https://example.com/resume.pdf', created_at: daysAgo(1), tracking_code: 'L2E-ABC23456' },
    { id: 2, job_id: 2, candidate_name: 'Legacy Candidate', email: 'other@example.com', status: 'accepted', resume_url: 'javascript:alert(1)', created_at: daysAgo(2), tracking_code: 'L2E-DEF23456' },
    { id: 3, job_id: 1, candidate_name: 'Interview Soon', email: 'interview@example.com', status: 'interview', resume_url: null, created_at: daysAgo(3), tracking_code: 'L2E-GHI23456', interview_at: new Date(Date.now() + 3600000).toISOString(), interview_timezone: 'UTC' },
  ];
}
let applicants = seedApplicants();
const sent = [];
const cors = {
  'access-control-allow-origin': '*',
  'access-control-allow-methods': 'GET, POST, PATCH, DELETE, OPTIONS',
  'access-control-allow-headers': 'content-type, authorization',
  'content-type': 'application/json',
};
const respond = (route, status, value) => route.fulfill({ status, headers: cors, body: JSON.stringify(value) });
const publicTrackData = (app) => ({
  job_title: jobs.find(j => j.id === app.job_id)?.title || 'The role',
  status: app.status,
  applied_at: app.created_at,
  history: [{ status: 'pending', changed_at: app.created_at }, ...(app.status !== 'pending' ? [{ status: app.status, changed_at: daysAgo(0) }] : [])],
  interview_at: app.interview_at || null,
  interview_timezone: app.interview_timezone || null,
});

async function mockApi(route) {
  const request = route.request();
  const url = new URL(request.url());
  if (request.method() === 'OPTIONS') return respond(route, 200, {});
  let payload;
  try { payload = request.postDataJSON(); } catch (_) { payload = null; }
  sent.push({ method: request.method(), url: request.url(), headers: request.headers(), payload });
  const isAdmin = request.headers()['authorization'] === 'Bearer ' + STAFF_TOKEN;
  const p = url.pathname;

  if (p === '/auth/login' && request.method() === 'POST') {
    if (payload?.email === 'staff@example.com' && payload?.password === 'Mock-password-1') {
      return respond(route, 200, { access_token: STAFF_TOKEN, refresh_token: 'MOCK-REFRESH-TOKEN-123456', expires_in: 3600, user: { email: 'staff@example.com' } });
    }
    return respond(route, 401, { detail: 'Sign-in failed. Check your staff account details.' });
  }
  if (p === '/auth/refresh' && request.method() === 'POST') {
    return respond(route, 200, { access_token: STAFF_TOKEN, refresh_token: 'MOCK-REFRESH-TOKEN-123456', expires_in: 3600, user: { email: 'staff@example.com' } });
  }
  if (p === '/site-info') return respond(route, 200, { contact_email: 'hiring@example.com' });
  if (p === '/jobs/' && request.method() === 'GET') {
    return respond(route, 200, { jobs: isAdmin ? jobs : jobs.filter(j => j.status === 'approved') });
  }
  const jobDetail = p.match(/^\/jobs\/(\d+)$/);
  if (jobDetail && request.method() === 'GET') {
    const job = jobs.find(j => j.id === Number(jobDetail[1]));
    if (!job || (!isAdmin && job.status !== 'approved')) return respond(route, 404, { detail: 'Not open' });
    return respond(route, 200, job);
  }
  if (p === '/applications/' && request.method() === 'POST') {
    return respond(route, 200, { id: 7, status: 'pending', tracking_code: 'L2E-ABC23456', tracking_email_sent: true, tracking_sms_queued: null, ...payload });
  }
  if (p === '/applications/' && request.method() === 'GET') {
    if (!isAdmin) return respond(route, 401, { detail: 'Staff sign-in required' });
    return respond(route, 200, applicants.map(({ tracking_code, ...rest }) => rest));
  }
  if (p === '/applications/track' && request.method() === 'POST') {
    const app = applicants.find(a => a.tracking_code === String(payload?.code || '').toUpperCase() && a.email === String(payload?.email || '').toLowerCase());
    return app ? respond(route, 200, publicTrackData(app)) : respond(route, 404, { detail: 'No application found. Check your email and tracking code.' });
  }
  if (p === '/applications/track-link' && request.method() === 'POST') {
    const app = payload?.token === TRACK_TOKEN ? applicants[0] : null;
    return app ? respond(route, 200, publicTrackData(app)) : respond(route, 404, { detail: 'This tracking link is invalid or no longer available.' });
  }
  if ((p === '/applications/withdraw' || p === '/applications/withdraw-link') && request.method() === 'POST') {
    const app = p.endsWith('withdraw-link')
      ? (payload?.token === TRACK_TOKEN ? applicants[0] : null)
      : applicants.find(a => a.tracking_code === String(payload?.code || '').toUpperCase() && a.email === String(payload?.email || '').toLowerCase());
    if (!app) return respond(route, 404, { detail: 'No application found.' });
    app.status = 'withdrawn';
    return respond(route, 200, { status: 'withdrawn', changed_at: new Date().toISOString() });
  }
  const appRoute = p.match(/^\/applications\/(\d+)(\/resume|\/activity)?$/);
  if (appRoute) {
    if (!isAdmin) return respond(route, 401, { detail: 'Staff sign-in required' });
    const app = applicants.find(a => a.id === Number(appRoute[1]));
    if (!app) return respond(route, 404, { detail: 'Application not found' });
    if (appRoute[2] === '/activity') return respond(route, 200, { activity: [{ created_at: app.created_at, actor_email: 'staff@example.com', action: 'status_changed' }] });
    if (appRoute[2] === '/resume') return respond(route, 200, { url: 'https://files.test/resume.pdf' });
    if (request.method() === 'PATCH') { Object.assign(app, payload); return respond(route, 200, app); }
    if (request.method() === 'DELETE') { applicants = applicants.filter(a => a.id !== app.id); return respond(route, 200, { deleted: true }); }
  }
  return respond(route, 404, { detail: 'Not part of the test' });
}

// True when the page is wider than the screen (a sideways scrollbar on a phone).
const overflowsSideways = (page) => page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
const staffSessionScript = () => sessionStorage.setItem('staffSession', JSON.stringify({
  access_token: 'MOCK-STAFF-TOKEN', refresh_token: 'MOCK-REFRESH-TOKEN-123456',
  expires_in: 3600, expires_at: Date.now() + 3600000, user: { email: 'staff@example.com' },
}));

async function launchBrowser() {
  try { return await chromium.launch({ headless: true, args: ['--no-sandbox'] }); }
  catch (_) {
    for (const executablePath of ['/usr/bin/google-chrome-stable', '/usr/bin/google-chrome', '/snap/bin/chromium']) {
      if (fs.existsSync(executablePath)) return chromium.launch({ headless: true, executablePath, args: ['--no-sandbox'] });
    }
    throw new Error('No Chromium browser found. Run: npx playwright install chromium');
  }
}

async function run() {
  const server = http.createServer((req, res) => {
    const pathname = new URL(req.url, 'http://local.test').pathname;
    if (pathname === '/dashboard') { res.writeHead(302, { location: '/admin' }); return res.end(); }
    const filename = routes[pathname];
    if (!filename) { res.writeHead(404); return res.end('Not found'); }
    res.writeHead(200, { 'content-type': types[filename.split('.').pop()], 'cache-control': 'no-store' });
    fs.createReadStream(path.join(root, filename)).pipe(res);
  });
  await new Promise(resolve => server.listen(0, '0.0.0.0', resolve));
  const local = `http://127.0.0.1:${server.address().port}`;
  let browser;
  try {
    browser = await launchBrowser();
    const failures = [];
    const watch = (page) => {
      page.on('pageerror', error => failures.push(error.message));
      page.on('requestfailed', request => {
        const url = request.url();
        if (url.startsWith('https://fonts.googleapis.com') || url.startsWith('https://fonts.gstatic.com')) return;
        failures.push(`${request.method()} ${url}: ${request.failure()?.errorText}`);
      });
    };

    // ---------- Visitor on a small phone (320px wide) ----------
    const context = await browser.newContext({ viewport: { width: 320, height: 700 } });
    await context.route(API_BASE + '/**', mockApi);
    const page = await context.newPage();
    watch(page);

    await page.goto(local + '/', { waitUntil: 'networkidle' });
    assert.equal(await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Jobs', exact: true }).isVisible(), true);
    await page.locator('#mini-jobs li').first().waitFor();
    assert.equal(await page.locator('#mini-jobs li').count(), 2, 'Home lists the two open jobs, not the closed one');
    assert.equal(await overflowsSideways(page), false, 'Home fits a phone');

    await page.getByRole('link', { name: 'See open jobs' }).click();
    await page.locator('#jobs-container .job').first().waitFor();
    assert.equal(await page.locator('#jobs-container .job').count(), 2);
    assert.equal(await overflowsSideways(page), false, 'Jobs fit a phone');
    await page.getByLabel('Search by job title or keyword').fill('frontend');
    assert.equal(await page.locator('#jobs-container .job').count(), 1);
    await page.getByLabel('Search by job title or keyword').fill('zzzz');
    await page.getByText('No jobs match your search.').waitFor();
    await page.getByLabel('Search by job title or keyword').fill('');

    const card = page.locator('#jobs-container .job').filter({ hasText: 'Backend Developer (Python/FastAPI)' });
    await card.getByRole('link', { name: 'View details for Backend Developer (Python/FastAPI)' }).click();
    await page.getByRole('heading', { name: 'Backend Developer (Python/FastAPI)' }).waitFor();
    assert.equal(await page.locator('script[type="application/ld+json"]').count(), 1, 'JobPosting structured data is preserved for search engines');
    await page.getByRole('link', { name: 'Apply for this role' }).click();
    await page.waitForFunction(() => document.querySelector('#job-id').value === '1');
    assert.equal(await overflowsSideways(page), false, 'Apply fits a phone');

    // Blank fields are caught with plain messages, and nothing is sent.
    await page.getByRole('button', { name: 'Send my application' }).click();
    assert.match(await page.locator('#status-message').innerText(), /boxes/i);
    assert.equal(await page.locator('#e-name').isVisible(), true);
    assert.equal(await page.getByLabel(/Your full name/).evaluate(el => document.activeElement === el), true, 'Focus jumps to the first problem');
    assert.equal(sent.filter(x => x.url.endsWith('/applications/') && x.method === 'POST').length, 0);

    await page.getByLabel(/Your full name/).fill('Test Candidate');
    await page.getByLabel(/Your email address/).fill('test@example.com');
    await page.getByLabel('Or paste a résumé link').fill('https://example.com/resume.pdf');
    await page.getByRole('button', { name: 'Send my application' }).click();
    await page.locator('#success-card:not([hidden])').waitFor();
    assert.equal(await page.locator('#success-code').innerText(), 'L2E-ABC23456');
    assert.equal(await page.locator('#track-link').getAttribute('href'), '/track');
    assert.equal(await overflowsSideways(page), false, 'The code ticket fits a phone');
    const post = sent.find(x => x.url.endsWith('/applications/') && x.method === 'POST');
    assert.deepEqual(post.payload, { candidate_name: 'Test Candidate', email: 'test@example.com', sms_updates_consent: false, job_id: 1, resume_url: 'https://example.com/resume.pdf' });
    assert.equal('track_token' in post.payload, false, 'The bearer token never reaches the browser');

    // The code travels to the tracking page without appearing in the address.
    await page.locator('#track-link').click();
    await page.waitForFunction(() => document.querySelector('#code') && document.querySelector('#code').value === 'L2E-ABC23456');
    assert.equal(new URL(page.url()).search, '');
    assert.equal(await page.getByLabel('Your tracking code').inputValue(), 'L2E-ABC23456');
    await page.getByLabel('Your email address').fill('test@example.com');
    await page.getByRole('button', { name: 'Check my application' }).click();
    await page.locator('#status-dashboard:not([hidden])').waitFor();
    const trackCall = sent.find(x => new URL(x.url).pathname === '/applications/track');
    assert.equal(trackCall.method, 'POST');
    assert.deepEqual(trackCall.payload, { email: 'test@example.com', code: 'L2E-ABC23456' });
    assert.ok(await page.locator('.application-timeline li').count() >= 1);
    assert.equal(await overflowsSideways(page), false, 'Tracking result fits a phone');

    // A private magic link opens the dashboard and is scrubbed from the address bar.
    await page.goto(local + '/track?t=' + TRACK_TOKEN, { waitUntil: 'networkidle' });
    await page.locator('#status-dashboard:not([hidden])').waitFor();
    assert.equal(new URL(page.url()).search, '', 'The token is removed from the address bar');
    const linkCall = sent.find(x => new URL(x.url).pathname === '/applications/track-link');
    assert.equal(linkCall.method, 'POST');
    assert.deepEqual(linkCall.payload, { token: TRACK_TOKEN });
    assert.equal(sent.some(x => x.url.includes(TRACK_TOKEN)), false, 'The token never appears in a request URL');

    // Withdrawing through the private link uses the token endpoint.
    await page.getByRole('button', { name: 'Withdraw application' }).click();
    await page.getByRole('button', { name: 'Confirm withdrawal' }).click();
    await page.getByRole('heading', { name: 'Application withdrawn' }).waitFor();
    const withdrawCall = sent.find(x => new URL(x.url).pathname === '/applications/withdraw-link');
    assert.deepEqual(withdrawCall.payload, { token: TRACK_TOKEN });

    // An invalid link falls back to the email-and-code form with a clear message.
    await page.evaluate(() => sessionStorage.removeItem('rolebeam-tracking-token'));
    await page.goto(local + '/track?t=00000000-0000-0000-0000-000000000000', { waitUntil: 'networkidle' });
    await page.getByText('We could not open that tracking link.').waitFor();
    assert.equal(await page.locator('#lookup-card').isVisible(), true);
    await context.close();

    // ---------- Staff on a desktop ----------
    applicants = seedApplicants();
    const admin = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await admin.route(API_BASE + '/**', mockApi);
    const dashboard = await admin.newPage();
    watch(dashboard);

    // Signed out: the workspace is locked behind the sign-in panel.
    await dashboard.goto(local + '/admin', { waitUntil: 'networkidle' });
    await dashboard.locator('#login-overlay:not([hidden])').waitFor();
    assert.equal(await dashboard.locator('main').evaluate(el => el.inert), true);
    await dashboard.getByLabel('Staff email').fill('staff@example.com');
    await dashboard.getByLabel('Password', { exact: true }).fill('Mock-password-1');
    await dashboard.getByRole('button', { name: 'Sign in', exact: true }).click();
    await dashboard.locator('#login-overlay').waitFor({ state: 'hidden' });
    await dashboard.locator('.candidate-card').first().waitFor();
    assert.equal(await dashboard.locator('#total-count').innerText(), '3');
    assert.equal(await dashboard.locator('#pending-count').innerText(), '1');
    assert.equal(await dashboard.locator('#accepted-count').innerText(), '1');
    assert.equal(await dashboard.locator('#new-applications-count').innerText(), '3');
    assert.ok(sent.some(x => new URL(x.url).pathname === '/jobs/' && x.headers['authorization'] === 'Bearer ' + STAFF_TOKEN));

    // Cmd/Ctrl+K opens the quick-actions palette; typing narrows it; Enter runs it.
    await dashboard.keyboard.press('Control+k');
    await dashboard.locator('#command-palette[open]').waitFor();
    await dashboard.locator('#command-search').fill('post a job');
    assert.equal(await dashboard.locator('.command-option').count(), 1);
    await dashboard.keyboard.press('Enter');
    await dashboard.locator('#command-palette').waitFor({ state: 'hidden' });
    assert.equal(await dashboard.locator('#job-title').evaluate(el => document.activeElement === el), true);
    await dashboard.getByRole('button', { name: /Quick actions/ }).click();
    await dashboard.locator('#command-palette[open]').waitFor();
    await dashboard.keyboard.press('Escape');
    await dashboard.locator('#command-palette').waitFor({ state: 'hidden' });

    // One-click advance on a pipeline card sends the status change.
    const patchesBefore = sent.filter(x => x.method === 'PATCH').length;
    await dashboard.getByRole('button', { name: 'Start review: Test Candidate' }).click();
    await dashboard.getByText('Test Candidate is now: Being reviewed.').waitFor();
    const advance = sent.filter(x => x.method === 'PATCH').pop();
    assert.equal(new URL(advance.url).pathname, '/applications/1');
    assert.deepEqual(advance.payload, { status: 'reviewing' });
    await dashboard.locator('[data-drop-status="reviewing"]').getByText('Test Candidate').waitFor();

    // Advance to interview, then accept. Accepting asks first; cancelling changes nothing.
    await dashboard.getByRole('button', { name: 'Move to interview: Test Candidate' }).click();
    await dashboard.getByText('Test Candidate is now: Interview stage.').waitFor();
    const beforeCancel = sent.filter(x => x.method === 'PATCH').length;
    await dashboard.getByRole('button', { name: 'Accept: Test Candidate' }).click();
    await dashboard.getByRole('dialog').waitFor();
    await dashboard.getByRole('button', { name: 'Cancel' }).click();
    assert.equal(sent.filter(x => x.method === 'PATCH').length, beforeCancel);
    await dashboard.getByRole('button', { name: 'Accept: Test Candidate' }).click();
    await dashboard.getByRole('button', { name: 'Accept', exact: true }).click();
    await dashboard.getByText('Test Candidate is now: Accepted.').waitFor();
    assert.equal(await dashboard.locator('#accepted-count').innerText(), '2');

    // The candidate drawer saves private notes and loads activity.
    await dashboard.getByRole('button', { name: 'Open profile for Legacy Candidate' }).first().click();
    await dashboard.locator('#candidate-drawer-backdrop:not([hidden])').waitFor();
    await dashboard.getByLabel('Private reviewer notes', { exact: true }).fill('Strong portfolio.');
    await dashboard.getByRole('button', { name: 'Save candidate details' }).click();
    await dashboard.getByText('Private notes and interview details saved.').waitFor();
    const notesPatch = sent.filter(x => x.method === 'PATCH').pop();
    assert.equal(notesPatch.payload.reviewer_notes, 'Strong portfolio.');
    await dashboard.getByRole('button', { name: 'Load activity history' }).click();
    await dashboard.getByText(/staff@example.com · status changed/).waitFor();
    await dashboard.keyboard.press('Escape');
    await dashboard.locator('#candidate-drawer-backdrop').waitFor({ state: 'hidden' });

    // List view keeps unsafe résumé links as plain text and shows job names.
    await dashboard.getByRole('button', { name: 'List', exact: true }).click();
    await dashboard.locator('#applicant-table-body tr').first().waitFor();
    assert.equal(await dashboard.locator('#applicant-table-body').getByText('Invalid link').isVisible(), true);
    assert.equal(await dashboard.locator('#applicant-table-body').getByText('Frontend Developer').first().isVisible(), true);
    const resume = dashboard.getByRole('link', { name: 'View résumé for Test Candidate' });
    assert.equal(await resume.getAttribute('rel'), 'noopener noreferrer');

    // Sign-out clears the session and locks the workspace again.
    await dashboard.getByRole('button', { name: 'Sign out' }).click();
    await dashboard.locator('#login-overlay:not([hidden])').waitFor();
    assert.equal(await dashboard.evaluate(() => sessionStorage.getItem('staffSession')), null);
    assert.equal(await dashboard.locator('main').evaluate(el => el.inert), true);
    assert.equal(await dashboard.locator('.candidate-card').count(), 0);
    await admin.close();

    // ---------- Staff page on a phone ----------
    applicants = seedApplicants();
    const small = await browser.newContext({ viewport: { width: 320, height: 700 } });
    await small.addInitScript(staffSessionScript);
    await small.route(API_BASE + '/**', mockApi);
    const phoneAdmin = await small.newPage();
    watch(phoneAdmin);
    await phoneAdmin.goto(local + '/admin', { waitUntil: 'networkidle' });
    await phoneAdmin.locator('.candidate-card').first().waitFor();
    assert.equal(await overflowsSideways(phoneAdmin), false, 'Staff workspace fits a phone');
    await small.close();

    // ---------- Contact page ----------
    const misc = await browser.newContext();
    await misc.route(API_BASE + '/**', mockApi);
    const contact = await misc.newPage();
    watch(contact);
    await contact.goto(local + '/contact', { waitUntil: 'networkidle' });
    assert.equal(await contact.getByRole('link', { name: 'hiring@example.com' }).getAttribute('href'), 'mailto:hiring@example.com');
    await contact.goto(local + '/dashboard');
    assert.equal(new URL(contact.url()).pathname, '/admin', '/dashboard redirects to the unified workspace');
    await misc.close();

    assert.deepEqual(failures, []);
    console.log('Frontend smoke tests passed: phone layouts, job search, structured data, apply form, code + magic-link tracking, withdrawal, staff sign-in, palette, quick actions, drawer, list safety and sign-out.');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}
run().catch(error => { console.error(error); process.exit(1); });
