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
  '/Frontend/static/tailwind.css': 'Frontend/static/tailwind.css',
};
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
  if (url.pathname === '/jobs/' && request.method() === 'GET') {
    const visible = request.headers()['x-admin-key'] === 'MOCK-ONLY' ? jobs : jobs.filter(j => j.status === 'approved');
    return respond(route, 200, { jobs: visible });
  }
  if (url.pathname === '/applications/' && request.method() === 'POST') {
    const created = { id: 7, status: 'pending', tracking_code: 'L2E-ABC23456', ...payload };
    return respond(route, 200, created);
  }
  if (url.pathname === '/applications/track' && request.method() === 'POST') {
    return respond(route, 200, { job_title: 'Backend Developer (Python/FastAPI)', status: 'rejected', applied_at: '2026-10-20T00:00:00Z' });
  }
  if (url.pathname === '/applications/' && request.method() === 'GET') {
    return request.headers()['x-admin-key'] === 'MOCK-ONLY' ? respond(route, 200, applicants) : respond(route, 401, { detail: 'Admin access required' });
  }
  return respond(route, 404, { detail: 'Not part of the test' });
}

async function run() {
  const server = http.createServer((req, res) => {
    const pathname = new URL(req.url, 'http://local.test').pathname;
    const filename = routes[pathname];
    if (!filename) { res.writeHead(404); return res.end('Not found'); }
    const file = path.join(root, filename);
    res.writeHead(200, { 'content-type': filename.endsWith('.css') ? 'text/css; charset=utf-8' : 'text/html; charset=utf-8', 'cache-control': 'no-store' });
    fs.createReadStream(file).pipe(res);
  });
  await new Promise(resolve => server.listen(0, '0.0.0.0', resolve));
  const local = `http://127.0.0.1:${server.address().port}`;
  let browser;
  try {
    browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
    const context = await browser.newContext({ viewport: { width: 320, height: 700 } });
    await context.route('https://applicant-tracking-system-tbaw.onrender.com/**', mockApi);
    const page = await context.newPage();
    const failures = [];
    page.on('pageerror', error => failures.push(error.message));
    page.on('requestfailed', request => failures.push(`${request.method()} ${request.url()}: ${request.failure()?.errorText}`));

    await page.goto(local + '/', { waitUntil: 'networkidle' });
    assert.equal(await page.getByRole('link', { name: 'Track', exact: true }).isVisible(), true);
    assert.equal(await page.getByRole('link', { name: 'Jobs', exact: true }).isVisible(), true);
    const navFits = await page.locator('nav').evaluate(nav => {
      const links = [...nav.querySelectorAll('a')].filter(a => a.getClientRects().length);
      return links.every(a => { const r = a.getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth; });
    });
    assert.equal(navFits, true, 'Mobile navigation should fit the viewport');
    await page.getByRole('link', { name: 'View Open Jobs' }).first().click();
    await page.locator('#jobs-container a').first().waitFor();
    const card = page.locator('#jobs-container > div').filter({ hasText: 'Backend Developer (Python/FastAPI)' });
    const badgeFits = await card.evaluate(el => {
      const cardBounds = el.getBoundingClientRect();
      const badgeBounds = el.querySelector('span').getBoundingClientRect();
      return badgeBounds.left >= cardBounds.left && badgeBounds.right <= cardBounds.right;
    });
    assert.equal(badgeFits, true, 'Engineering badge should fit inside the job card');
    await card.getByRole('link', { name: 'Apply Now' }).click();
    await page.waitForFunction(() => document.querySelector('#job-id').value === '1');
    assert.equal(await page.getByLabel('Position Applying For').inputValue(), '1');
    await page.getByLabel('Full Name').fill('   ');
    await page.getByLabel('Email Address').fill('test@example.com');
    await page.getByRole('button', { name: 'Submit Application' }).click();
    assert.match(await page.locator('#status-message').innerText(), /full name/i);
    assert.equal(sent.filter(x => x.url.endsWith('/applications/') && x.method === 'POST').length, 0);

    await page.getByLabel('Full Name').fill('Test Candidate');
    await page.getByLabel('CV / Resume Link').fill('https://example.com/resume.pdf');
    await page.getByRole('button', { name: 'Submit Application' }).click();
    await page.locator('#success-card:not(.hidden)').waitFor();
    assert.equal(await page.locator('#track-link').getAttribute('href'), '/track');
    assert.equal(await page.locator('#success-code').innerText(), 'L2E-ABC23456');
    await page.locator('#track-link').click();
    assert.equal(new URL(page.url()).search, '');
    assert.equal(await page.getByLabel('Tracking code').inputValue(), 'L2E-ABC23456');
    await page.getByLabel('Email').fill('test@example.com');
    await page.getByRole('button', { name: 'Check status' }).click();
    await page.getByText('Not selected this time').waitFor();
    const trackCall = sent.find(x => x.url.endsWith('/applications/track'));
    assert.equal(trackCall.method, 'POST');
    assert.equal(new URL(trackCall.url).search, '');
    assert.deepEqual(trackCall.payload, { email: 'test@example.com', code: 'L2E-ABC23456' });
    const interviewDot = await page.locator('#result ol li').nth(2).locator('span').getAttribute('class');
    const decisionDot = await page.locator('#result ol li').nth(3).locator('span').getAttribute('class');
    assert.match(interviewDot, /bg-gray-800/);
    assert.match(decisionDot, /bg-red-500/);

    await page.goto(local + '/track?code=L2E-ABC23456&email=test%40example.com&from=old', { waitUntil: 'networkidle' });
    assert.equal(new URL(page.url()).search, '?from=old');
    assert.equal(await page.getByLabel('Tracking code').inputValue(), 'L2E-ABC23456');
    assert.equal(await page.getByLabel('Email').inputValue(), 'test@example.com');
    await context.close();

    applicants = [
      { id: 1, job_id: 1, candidate_name: 'Test Candidate', email: 'test@example.com', status: 'pending', resume_url: 'https://example.com/resume.pdf' },
      { id: 2, job_id: 2, candidate_name: 'Legacy Candidate', email: 'other@example.com', status: 'accepted', resume_url: 'javascript:alert(1)' },
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
    assert.equal(await dashboard.locator('#applicant-table-body tr').nth(1).getByText('Invalid link').isVisible(), true);
    assert.equal(await dashboard.getByText('Closed test job').isVisible(), true);
    assert.ok(sent.some(x => new URL(x.url).pathname === '/jobs/' && x.headers['x-admin-key'] === 'MOCK-ONLY'));

    applicants = [];
    await dashboard.getByRole('button', { name: 'Refresh Data' }).click();
    await dashboard.getByText('No applicants submitted yet.').waitFor();
    assert.equal(await dashboard.locator('#total-count').innerText(), '0');
    assert.equal(await dashboard.locator('#pending-count').innerText(), '0');
    assert.equal(await dashboard.locator('#accepted-count').innerText(), '0');
    await dashboard.getByRole('button', { name: 'Sign out' }).click();
    assert.equal(await dashboard.getByRole('dialog').isVisible(), true);
    assert.equal(await dashboard.evaluate(() => sessionStorage.getItem('adminKey')), null);
    assert.equal(await dashboard.locator('#applicant-table-body').innerText(), '');
    assert.equal(await dashboard.locator('main').evaluate(el => el.inert), true);
    assert.deepEqual(failures, []);
    await admin.close();
    console.log('Frontend smoke tests passed: mobile, application, POST tracking, résumé links, admin counts and sign-out.');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}
run().catch(error => { console.error(error); process.exit(1); });
