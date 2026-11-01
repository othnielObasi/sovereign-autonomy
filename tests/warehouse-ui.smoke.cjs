// Run against the local stack: node tests/warehouse-ui.smoke.cjs
// Mission mutations are intercepted so this check cannot move the simulator.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}),
    headless: true,
    args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1100, height: 760 } });
    const errors = [];
    page.on('pageerror', e => { errors.push(e.message); console.error('Browser error:', e.message); });
    let savedPayload;
    let creates = 0;
    let starts = 0;
    await page.route('**/api/missions', async route => {
      if (route.request().method() !== 'POST') return route.continue();
      savedPayload = route.request().postDataJSON();
      creates++;
      await route.fulfill({ json: { id: 'warehouse-smoke-draft', title: savedPayload.title, goal: savedPayload.goal, status: 'draft' } });
    });
    await page.route('**/api/missions/warehouse-smoke-draft/start', async route => {
      starts++;
      await route.fulfill({ status: 503, json: { detail: 'Test planner unavailable; draft retained' } });
    });
    await page.goto(`${process.env.APP_URL || 'http://127.0.0.1:3000'}/twin?q=low`, { timeout: 120000, waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: 'Inspect robot', exact: true }).waitFor({ timeout: 90000 }).catch(async error => {
      console.error('Rendered page:', await page.locator('body').innerText());
      throw error;
    });
    console.log('Warehouse loaded');
    await page.getByRole('button', { name: 'Plan mission', exact: true }).click();
    const select = page.getByLabel('Destination bay');
    const bayId = await select.locator('option').nth(1).getAttribute('value');
    assert.ok(bayId);
    assert.equal(await page.getByRole('button', { name: 'Save mission draft', exact: true }).isEnabled(), false);
    await select.selectOption(bayId);
    await page.getByLabel('Mission instruction').fill('Warehouse UI smoke mission');
    await page.getByRole('button', { name: 'Save mission draft', exact: true }).click();
    await page.getByText('Draft saved: Warehouse UI smoke mission', { exact: true }).waitFor();
    assert.equal(creates, 1);
    assert.equal(savedPayload.bay_id, bayId);
    assert.equal(typeof savedPayload.goal.x, 'number');
    assert.equal(typeof savedPayload.goal.y, 'number');
    await page.getByRole('button', { name: 'Start governed run', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'draft retained' }).waitFor();
    assert.equal(starts, 1);
    assert.equal(creates, 1, 'a failed start must not create a duplicate mission');
    await page.getByRole('button', { name: 'Plan another mission', exact: true }).click();
    await page.getByRole('button', { name: 'Follow', exact: true }).click();
    await page.getByRole('button', { name: 'Pick destination on floor', exact: true }).click();
    await page.getByRole('button', { name: 'Overview', exact: true, pressed: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Overview', exact: true }).getAttribute('aria-pressed'), 'true');
    await page.getByRole('button', { name: 'Cancel floor selection', exact: true }).click();
    await page.getByRole('button', { name: 'Inspect robot', exact: true }).click();
    await page.getByText('Active robot', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Close inspection', exact: true }).click();
    await page.getByRole('button', { name: 'Robot eye', exact: true }).click();
    await page.getByText('Simulated detections · projected from world state', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Overview', exact: true }).click();
    if (process.env.WAREHOUSE_SCREENSHOT) await page.screenshot({ path: process.env.WAREHOUSE_SCREENSHOT });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.getByRole('button', { name: 'Save mission draft', exact: true }).isVisible(), true);
    assert.deepEqual(errors, []);
    console.log('PASS: bay selection, draft creation, failed-start recovery, camera selection, floor-pick mode, inspection, robot eye, mobile panel; no page errors.');
    await page.close();
  } finally {
    await Promise.race([browser.close(), new Promise(resolve => setTimeout(resolve, 10000))]);
  }
})().then(() => process.exit(0)).catch(e => { console.error(e); process.exit(1); });
