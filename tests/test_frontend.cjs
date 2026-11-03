/** Browser smoke tests. A local server and fake API are used; no real
 * candidate information or production requests are sent. */
const http = require('http');
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const routes = {
  '/': 'Frontend/templates/home.html',
  '/jobs': 'Frontend/templates/jobs.html',
  '/apply': 'Frontend/templates/index.html',
  '/track': 'Frontend/templates/track.html',
  '/admin': 'Frontend/templates/admin.html',
  '/dashboard': 'Frontend/templates/dashboard.html',
  '/Frontend/static/style.css': 'Frontend/static/style.css',
  '/Frontend/static/script.js': 'Frontend/static/script.js',
};
const types = { css: 'text/css; charset=utf-8', js: 'text/javascript; charset=utf-8', html: 'text/html; charset=utf-8' };
const jobs = [
  { id: 1, title: 'Backend Developer (Python/FastAPI)', department: 'Engineering', description: 'Build APIs.', status: 'approved' },
  { id: 2, title: 'Frontend Developer', department: 'Engineering', description: 'Build interfaces.', status: 'approved' },
  { id: 3, title: 'Closed test job', department: 'Product', description: 'Hidden.', status: 'rejected' },
];
let applicants = [];
const sent = [];
const cors = {
  'access-control-allow-origin': '*',
  'access-control-allow-methods': 'GET, POST, PATCH, OPTIONS',
  'access-control-allow-headers': 'content-type, x-admin-key',
  'content-type': 'application/json',
};

function respond(route, status, value) {
  return route.fulfill({ status, headers: cors, body: JSON.stringify(value) });
}

async function mockApi(route) {
  const request = route.request();
  const url = new URL(request.url());
  if (request.method() === 'OPTIONS') return respond(route, 200, {});
  let payload;
  try { payload = request.postDataJSON(); } catch (_) { payload = null; }
  sent.push({ method: request.method(), url: request.url(), headers: request.headers(), payload });
  const isAdmin = request.headers()['x-admin-key'] === 'MOCK-ONLY';
  if (url.pathname === '/jobs/' && request.method() === 'GET') {
    return respond(route, 200, { jobs: isAdmin ? jobs : jobs.filter(j => j.status === 'approved') });
  }
  if (url.pathname === '/applications/' && request.method() === 'POST') {
    return respond(route, 200, { id: 7, status: 'pending', tracking_code: 'L2E-ABC23456', ...payload });
  }
  if (url.pathname === '/applications/track' && request.method() === 'POST') {
    return respond(route, 200, { job_title: 'Backend Developer (Python/FastAPI)', status: 'rejected', applied_at: '2026-10-20T00:00:00Z' });
  }
  if (url.pathname === '/applications/' && request.method() === 'GET') {
    return isAdmin ? respond(route, 200, applicants) : respond(route, 401, { detail: 'Admin access required' });
  }
  const patch = url.pathname.match(/^\/applications\/(\d+)$/);
  if (patch && request.method() === 'PATCH') {
    if (!isAdmin) return respond(route, 401, { detail: 'Admin access required' });
    const app = applicants.find(a => a.id === Number(patch[1]));
    app.status = payload.status;
    return respond(route, 200, app);
  }
  return respond(route, 404, { detail: 'Not part of the test' });
}

// True when the page is wider than the screen (a sideways scrollbar on a phone).
const overflowsSideways = (page) => page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);

async function run() {
  const server = http.createServer((req, res) => {
    const pathname = new URL(req.url, 'http://local.test').pathname;
    const filename = routes[pathname];
    if (!filename) { res.writeHead(404); return res.end('Not found'); }
    res.writeHead(200, { 'content-type': types[filename.split('.').pop()], 'cache-control': 'no-store' });
    fs.createReadStream(path.join(root, filename)).pipe(res);
  });
  await new Promise(resolve => server.listen(0, '0.0.0.0', resolve));
  const local = `http://127.0.0.1:${server.address().port}`;
  let browser;
  try {
    browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
    const failures = [];

    // ---------- Visitor on a small phone (320px wide) ----------
    const context = await browser.newContext({ viewport: { width: 320, height: 700 } });
    await context.route('https://applicant-tracking-system-tbaw.onrender.com/**', mockApi);
    const page = await context.newPage();
    page.on('pageerror', error => failures.push(error.message));
    page.on('requestfailed', request => failures.push(`${request.method()} ${request.url()}: ${request.failure()?.errorText}`));

    await page.goto(local + '/', { waitUntil: 'networkidle' });
    assert.equal(await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Jobs', exact: true }).isVisible(), true);
    assert.equal(await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Check my application' }).isVisible(), true);
    await page.locator('#mini-jobs li').first().waitFor();
    assert.equal(await page.locator('#mini-jobs li').count(), 2, 'Home should list the two open jobs and not the closed one');
    assert.equal(await overflowsSideways(page), false, 'Home should not scroll sideways on a phone');

    await page.getByRole('link', { name: 'See open jobs' }).click();
    await page.locator('#jobs-container .job').first().waitFor();
    assert.equal(await page.locator('#jobs-container .job').count(), 2);
    assert.equal(await overflowsSideways(page), false, 'Jobs should not scroll sideways on a phone');

    // Search narrows the list
    await page.getByLabel('Search jobs').fill('frontend');
    assert.equal(await page.locator('#jobs-container .job').count(), 1);
    await page.getByLabel('Search jobs').fill('zzzz');
    await page.getByText('No jobs match your search.').waitFor();
    await page.getByLabel('Search jobs').fill('');

    const card = page.locator('#jobs-container .job').filter({ hasText: 'Backend Developer (Python/FastAPI)' });
    const pillFits = await card.evaluate(el => {
      const c = el.getBoundingClientRect(); const p = el.querySelector('.pill').getBoundingClientRect();
      return p.left >= c.left && p.right <= c.right;
    });
    assert.equal(pillFits, true, 'Type-of-work label should fit inside the job card');
    await card.getByRole('link', { name: 'Apply for Backend Developer (Python/FastAPI)' }).click();
    await page.waitForFunction(() => document.querySelector('#job-id').value === '1');
    assert.equal(await page.getByLabel(/Which job are you applying for/).inputValue(), '1');
    assert.equal(await overflowsSideways(page), false, 'Apply should not scroll sideways on a phone');

    // Blank name and a bad email are caught with plain messages, and nothing is sent
    await page.getByLabel(/Your full name/).fill('   ');
    await page.getByLabel(/Your email address/).fill('not-an-email');
    await page.getByRole('button', { name: 'Send my application' }).click();
    assert.match(await page.locator('#status-message').innerText(), /2 boxes/i);
    assert.equal(await page.locator('#e-name').isVisible(), true);
    assert.equal(await page.locator('#e-email').isVisible(), true);
    assert.equal(await page.getByLabel(/Your full name/).evaluate(el => document.activeElement === el), true, 'Focus should jump to the first problem');
    assert.equal(sent.filter(x => x.url.endsWith('/applications/') && x.method === 'POST').length, 0);

    await page.getByLabel(/Your full name/).fill('Test Candidate');
    await page.getByLabel(/Your email address/).fill('test@example.com');
    await page.getByLabel(/Link to your resume/).fill('https://example.com/resume.pdf');
    await page.getByRole('button', { name: 'Send my application' }).click();
    await page.locator('#success-card:not([hidden])').waitFor();
    assert.equal(await page.locator('#track-link').getAttribute('href'), '/track');
    assert.equal(await page.locator('#success-code').innerText(), 'L2E-ABC23456');
    assert.equal(await overflowsSideways(page), false, 'The code ticket should fit a phone screen');
    const post = sent.find(x => x.url.endsWith('/applications/') && x.method === 'POST');
    assert.deepEqual(post.payload, { candidate_name: 'Test Candidate', email: 'test@example.com', job_id: 1, resume_url: 'https://example.com/resume.pdf' });

    // The code travels to the tracking page without appearing in the address
    await page.locator('#track-link').click();
    assert.equal(new URL(page.url()).search, '');
    assert.equal(await page.getByLabel('Your tracking code').inputValue(), 'L2E-ABC23456');
    await page.getByLabel('Your email address').fill('test@example.com');
    await page.getByRole('button', { name: 'Check my application' }).click();
    await page.getByText('Not selected this time').first().waitFor();
    const trackCall = sent.find(x => x.url.endsWith('/applications/track'));
    assert.equal(trackCall.method, 'POST');
    assert.equal(new URL(trackCall.url).search, '');
    assert.deepEqual(trackCall.payload, { email: 'test@example.com', code: 'L2E-ABC23456' });
    // Only the current stage is marked; earlier stages are not claimed as done
    assert.doesNotMatch(await page.locator('#result ol li').nth(2).locator('.dot').getAttribute('class'), /is-current/);
    assert.match(await page.locator('#result ol li').nth(3).locator('.dot').getAttribute('class'), /is-bad/);
    assert.equal(await page.locator('#result ol li[aria-current="step"]').count(), 1);
    assert.equal(await overflowsSideways(page), false, 'Tracking result should not scroll sideways on a phone');

    // Old links that carry the code and email still work, then are cleaned from the address bar
    await page.goto(local + '/track?code=L2E-ABC23456&email=test%40example.com&from=old', { waitUntil: 'networkidle' });
    assert.equal(new URL(page.url()).search, '?from=old');
    assert.equal(await page.getByLabel('Your tracking code').inputValue(), 'L2E-ABC23456');
    assert.equal(await page.getByLabel('Your email address').inputValue(), 'test@example.com');
    await context.close();

    // ---------- Staff on a desktop ----------
    applicants = [
      { id: 1, job_id: 1, candidate_name: 'Test Candidate', email: 'test@example.com', status: 'pending', resume_url: 'https://example.com/resume.pdf', created_at: '2026-10-20T00:00:00Z' },
      { id: 2, job_id: 2, candidate_name: 'Legacy Candidate', email: 'other@example.com', status: 'accepted', resume_url: 'javascript:alert(1)', created_at: '2026-10-21T00:00:00Z' },
    ];
    const admin = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await admin.addInitScript(() => sessionStorage.setItem('adminKey', 'MOCK-ONLY'));
    await admin.route('https://applicant-tracking-system-tbaw.onrender.com/**', mockApi);
    const dashboard = await admin.newPage();
    dashboard.on('pageerror', error => failures.push(error.message));
    await dashboard.goto(local + '/admin', { waitUntil: 'networkidle' });
    await dashboard.locator('#applicant-table-body tr').nth(1).waitFor();
    assert.equal(await dashboard.locator('#total-count').innerText(), '2');
    assert.equal(await dashboard.locator('#pending-count').innerText(), '1');
    assert.equal(await dashboard.locator('#accepted-count').innerText(), '1');
    const resume = dashboard.getByRole('link', { name: 'View résumé for Test Candidate' });
    assert.equal(await resume.getAttribute('href'), 'https://example.com/resume.pdf');
    assert.equal(await resume.getAttribute('rel'), 'noopener noreferrer');
    // Newest application first; the unsafe link is shown as text, never as a link
    assert.equal(await dashboard.locator('#applicant-table-body tr').nth(0).getByText('Invalid link').isVisible(), true);
    assert.equal(await dashboard.locator('#applicant-table-body tr').nth(0).locator('a').count(), 0);
    // Job names are shown instead of "Job #2"
    assert.equal(await dashboard.locator('#applicant-table-body tr').nth(0).getByText('Frontend Developer').isVisible(), true);
    assert.equal(await dashboard.getByText('Closed test job').isVisible(), true);
    assert.ok(sent.some(x => new URL(x.url).pathname === '/jobs/' && x.headers['x-admin-key'] === 'MOCK-ONLY'));

    // Filter chips
    await dashboard.getByRole('button', { name: /^Waiting for review \(1\)/ }).click();
    assert.equal(await dashboard.locator('#applicant-table-body tr').count(), 1);
    await dashboard.getByRole('button', { name: /^Everyone/ }).click();

    // Accepting asks first; cancelling changes nothing, confirming sends the change
    const patchesBefore = sent.filter(x => x.method === 'PATCH').length;
    await dashboard.getByRole('button', { name: 'Accept: Test Candidate' }).click();
    assert.equal(await dashboard.getByRole('dialog').isVisible(), true);
    await dashboard.getByRole('button', { name: 'Cancel' }).click();
    assert.equal(sent.filter(x => x.method === 'PATCH').length, patchesBefore);
    await dashboard.getByRole('button', { name: 'Accept: Test Candidate' }).click();
    await dashboard.getByRole('button', { name: 'Accept', exact: true }).click();
    await dashboard.getByText('Test Candidate is now: Accepted.').waitFor();
    const patch = sent.filter(x => x.method === 'PATCH').pop();
    assert.equal(new URL(patch.url).pathname, '/applications/1');
    assert.deepEqual(patch.payload, { status: 'accepted' });
    assert.equal(await dashboard.locator('#accepted-count').innerText(), '2');

    // Staff summary page shares the same sign-in
    await dashboard.goto(local + '/dashboard', { waitUntil: 'networkidle' });
    await dashboard.locator('#bars li').nth(4).waitFor();
    assert.equal(await dashboard.locator('#total-count').innerText(), '2');
    assert.equal(await dashboard.locator('#accepted-count').innerText(), '2');
    await dashboard.goto(local + '/admin', { waitUntil: 'networkidle' });
    await dashboard.locator('#applicant-table-body tr').nth(1).waitFor();

    applicants = [];
    await dashboard.getByRole('button', { name: 'Refresh the lists' }).click();
    await dashboard.getByText('No applicants submitted yet.').waitFor();
    assert.equal(await dashboard.locator('#total-count').innerText(), '0');
    assert.equal(await dashboard.locator('#pending-count').innerText(), '0');
    assert.equal(await dashboard.locator('#accepted-count').innerText(), '0');
    await dashboard.getByRole('button', { name: 'Sign out' }).click();
    assert.equal(await dashboard.getByRole('dialog').isVisible(), true);
    assert.equal(await dashboard.evaluate(() => sessionStorage.getItem('adminKey')), null);
    assert.equal(await dashboard.locator('#applicant-table-body').innerText(), '');
    assert.equal(await dashboard.locator('main').evaluate(el => el.inert), true);
    await admin.close();

    // ---------- Staff page on a phone: the table becomes cards, with no sideways scroll ----------
    applicants = [{ id: 1, job_id: 1, candidate_name: 'Test Candidate', email: 'a-very-long-email-address-for-testing@example-company-name.com', status: 'pending', resume_url: null, created_at: '2026-10-20T00:00:00Z' }];
    const small = await browser.newContext({ viewport: { width: 320, height: 700 } });
    await small.addInitScript(() => sessionStorage.setItem('adminKey', 'MOCK-ONLY'));
    await small.route('https://applicant-tracking-system-tbaw.onrender.com/**', mockApi);
    const phoneAdmin = await small.newPage();
    phoneAdmin.on('pageerror', error => failures.push(error.message));
    await phoneAdmin.goto(local + '/admin', { waitUntil: 'networkidle' });
    await phoneAdmin.locator('#applicant-table-body tr').first().waitFor();
    assert.equal(await overflowsSideways(phoneAdmin), false, 'Staff page should not scroll sideways on a phone');
    await small.close();

    assert.deepEqual(failures, []);
    console.log('Frontend smoke tests passed: phone layout, search, application form, POST tracking, staff confirmations, filters, résumé links and sign-out.');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}
run().catch(error => { console.error(error); process.exit(1); });
