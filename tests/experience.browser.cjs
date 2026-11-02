// Real-service validation against scripts/browser_validation_stack.py.
// This file creates a simulated mission only on the explicitly isolated stack.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const base = process.env.APP_URL || 'http://127.0.0.1:19300';
assert.equal(new URL(base).port, '19300', 'Use the isolated browser validation stack');
const out = path.resolve(process.env.BROWSER_EVIDENCE_DIR || 'docs/validation/2026-11-02');
const forceFallback = process.env.BROWSER_FORCE_FALLBACK === '1';
fs.mkdirSync(out, { recursive: true });
const report = { scope: 'Isolated real simulator/backend/frontend; signed browser fixture, no model calls', renderingMode: forceFallback ? 'forced WebGL fallback' : 'normal scene; test-host 10 FPS cap', steps: [], errors: [], externalRequests: [] };
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function until(fn, description, timeout = 45000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) { const value = await fn(); if (value) return value; await sleep(300); }
  throw new Error(`Timed out: ${description}`);
}

(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  let runId, request, headers;
  let page;
  try {
    const context = await browser.newContext({ viewport: { width: 1380, height: 980 } });
    context.setDefaultTimeout(90000);
    // Bound software-renderer load on CPU-only validation hosts (10 FPS).
    await context.addInitScript(() => {
      window.requestAnimationFrame = callback => window.setTimeout(() => callback(performance.now()), 100);
      window.cancelAnimationFrame = id => window.clearTimeout(id);
    });
    if (forceFallback) await context.addInitScript(() => {
      const original = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function(kind, ...args) {
        if (String(kind).includes('webgl')) return null;
        return original.call(this, kind, ...args);
      };
    });
    const collectError = e => {
      if (forceFallback && /WebGL|R3F|THREE/i.test(e.message)) return;
      report.errors.push(e.message);
    };
    await context.route('**/*', route => {
      const url = new URL(route.request().url());
      if (['http:', 'https:'].includes(url.protocol) && url.origin !== new URL(base).origin) {
        report.externalRequests.push(url.origin); return route.abort();
      }
      return route.continue();
    });
    page = await context.newPage();
    page.on('pageerror', collectError);
    request = page.request;
    const token = await (await request.post(`${base}/api/auth/dev-token?role=admin`)).json();
    headers = { Authorization: `Bearer ${token.access_token}` };
    await page.goto(`${base}/authority`);
    await page.getByText('robot-A (fixture)', { exact: true }).first().waitFor();
    await page.screenshot({ path: path.join(out, 'experience-before.png'), fullPage: true });
    report.steps.push('Signed fixture is shown with provenance and eligibility');

    await page.goto(`${base}/twin?q=low`);
    assert.equal((await (await request.get(`${base}/api/sim/fleet`)).json()).robots.length, 2);
    if (!forceFallback) {
      await page.getByRole('button', { name: 'Inspect robot', exact: true }).click();
      await page.getByText('Active robot', { exact: true }).waitFor();
      await page.getByRole('button', { name: 'Close inspection', exact: true }).click();
      await page.screenshot({ path: path.join(out, 'factory.png') });
      report.steps.push('Factory canvas and two-robot fleet load with external requests blocked');
    } else {
      await page.getByText(/(WebGL|3D rendering|3D view).*unavailable/).first().waitFor();
      report.steps.push('Two-robot API and fallback scene load with external requests blocked');
    }
    await page.getByRole('button', { name: 'Plan mission', exact: true }).click();
    await page.getByLabel('Destination bay').selectOption('L-05');
    await page.getByLabel('Mission instruction').fill('Browser validation: environment revalidation');
    await page.getByRole('button', { name: 'Save mission draft', exact: true }).click();
    await page.getByRole('button', { name: 'Start governed run', exact: true }).click();
    await page.waitForURL(/\/runs\//, { timeout: 45000 });
    runId = new URL(page.url()).pathname.split('/').pop();
    const events = async () => (await request.get(`${base}/api/runs/${runId}/events?limit=1000`)).json();
    await until(async () => (await events()).some(e => e.type === 'EXPERIENCE_RETRIEVAL'), 'initial retrieval event');
    const twin = page;
    await twin.setViewportSize({ width: 800, height: 600 });
    await twin.goto(`${base}/twin?q=low`, { waitUntil: 'domcontentloaded' });
    await twin.getByRole('button', { name: 'Inspect robot', exact: true }).waitFor();
    const blockedReply = twin.waitForResponse(r => r.url().endsWith('/api/sim/scenario') && r.request().method() === 'POST');
    await twin.getByRole('button', { name: 'Dropped pallet', exact: true }).click();
    assert.equal((await blockedReply).status(), 200);
    await until(async () => (await events()).some(e => e.type === 'ENVIRONMENT_CHANGE'), 'environment revalidation');
    const clearReply = twin.waitForResponse(r => r.url().endsWith('/api/sim/scenario') && r.request().method() === 'POST');
    await twin.getByRole('button', { name: 'Clear', exact: true }).click();
    assert.equal((await clearReply).status(), 200);
    const changed = await until(async () => {
      const list = (await events()).filter(e => e.type === 'ENVIRONMENT_CHANGE');
      return list.length >= 2 && list.at(-1).payload.action === 'replanned' ? list : null;
    }, 'replacement route after clear');
    report.environmentEvents = changed.map(e => e.payload);
    await page.goto(`${base}/runs/${runId}`, { waitUntil: 'domcontentloaded' });
    await page.getByRole('tab', { name: 'Learning & task', exact: true }).click();
    await page.getByText('Old plan discarded; replacement route ready', { exact: true }).first().waitFor();
    await page.getByText('Experience and environment', { exact: true }).first().scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(out, 'mission-replanned.png') });
    report.steps.push('Mission UI creates a run, records changed assumptions, and shows replacement routing');

    await page.goto(`${base}/authority`);
    await page.getByTestId('experience-checks').getByText('Excluded', { exact: true }).first().waitFor();
    await page.getByTestId('environment-changes').waitFor();
    await page.screenshot({ path: path.join(out, 'experience-invalidated.png'), fullPage: true });
    report.steps.push('Old fixture becomes excluded and durable lifecycle changes are visible');

    const paused = await request.post(`${base}/api/runs/${runId}/pause`, { headers });
    assert.equal(paused.status(), 200);
    await page.getByRole('button', { name: 'Stop everything', exact: true }).click();
    await page.getByText(/Stop confirmed in/).waitFor();
    const tel = await (await request.get(`${base}/api/sim/telemetry`)).json();
    assert.equal(tel.estop.engaged, true); assert.equal(tel.target, null);
    const refused = await request.post(`${base}/api/runs/${runId}/resume`, { headers });
    assert.equal(refused.status(), 409);
    await page.getByRole('button', { name: 'Reset (operator)', exact: true }).click();
    await page.getByText('Lock lifted. New moves need fresh permits.', { exact: true }).waitFor();
    await page.goto(`${base}/runs/${runId}`);
    await page.getByRole('button', { name: /Override & Resume/ }).click();
    await until(async () => (await (await request.get(`${base}/api/runs/${runId}`)).json()).status === 'running', 'operator resume');
    report.steps.push('Pause, kill, refused resume, authenticated reset and UI resume match API/controller state');

    await request.post(`${base}/api/runs/${runId}/stop`, { headers });
    await page.goto(`${base}/authority`);
    await page.getByTestId('experience-checks').waitFor();
    const drillReply = page.waitForResponse(r => r.url().endsWith('/api/authority/drills') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Run all drills', exact: true }).click();
    const drillResponse = await drillReply;
    assert.equal(drillResponse.status(), 200);
    const drillResult = await drillResponse.json();
    assert.equal(drillResult.all_passed, true, JSON.stringify(drillResult));
    report.poisoning = drillResult.results.find(r => r.drill === 'poisoning');
    assert.equal(report.poisoning.passed, true);
    assert.equal(report.poisoning.checks.length, 7);
    await page.getByText('PASS · mild flood cannot dilute stop', { exact: true }).waitFor();
    await page.screenshot({ path: path.join(out, 'poisoning-drill.png'), fullPage: true });
    report.steps.push('Authority UI runs real security drills and displays all seven poisoning sub-checks');

    // Force a real WebGL initialization failure, without adding a product test hook.
    const fallbackContext = await browser.newContext();
    await fallbackContext.addInitScript(() => {
      const original = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function(kind, ...args) {
        if (String(kind).includes('webgl')) return null;
        return original.call(this, kind, ...args);
      };
    });
    const fallback = await fallbackContext.newPage();
    await fallback.goto(`${base}/twin?q=low`);
    await fallback.getByText(/(WebGL|3D rendering|3D view).*unavailable/).first().waitFor({ timeout: 60000 });
    await fallback.getByRole('button', { name: 'Plan mission', exact: true }).click();
    assert(await fallback.getByLabel('Destination bay').isVisible());
    assert(await fallback.getByRole('button', { name: 'Stop all robots', exact: true }).isEnabled());
    await fallback.screenshot({ path: path.join(out, 'graphics-fallback.png') });
    report.steps.push('WebGL failure leaves mission and stop controls usable');
    assert.deepEqual(report.errors, []);
    report.passed = true;
  } catch (error) {
    if (page) {
      report.failurePage = await page.locator('body').innerText({ timeout: 5000 }).catch(() => 'unavailable');
      await page.screenshot({ path: path.join(out, 'failure.png'), timeout: 10000 }).catch(() => {});
    }
    report.passed = false; report.failure = String(error.stack || error); throw error;
  } finally {
    if (runId && request) await request.post(`${base}/api/runs/${runId}/stop`, { headers }).catch(() => {});
    fs.writeFileSync(path.join(out, 'browser-results.json'), JSON.stringify(report, null, 2));
    await browser.close();
  }
  console.log(JSON.stringify(report, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; });
