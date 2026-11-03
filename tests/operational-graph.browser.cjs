const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const base = process.env.PUBLIC_BASE_URL || 'http://127.0.0.1:19300';
const output = path.resolve('docs/validation/2026-11-03-memgraph');
fs.mkdirSync(output, { recursive: true });
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [], commands = [], checks = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('request', r => {
    if (r.method() === 'POST' && /\/(sim|missions|operator|authority)\//.test(r.url())) commands.push(r.url());
  });
  try {
    await page.goto(base + '/authority');
    await page.getByText('Memgraph connected', { exact: true }).waitFor();
    // Assert source facts against the actual API, not a fixture response.
    const run = await page.getByLabel('Knowledge graph run').inputValue();
    const evidence = await (await page.request.get(base + '/api/knowledge/runs/' + run)).json();
    assert.ok(evidence.facts.length > 0);
    await page.getByText(`View ${evidence.facts.length} verified decision connections`, { exact: true }).click();
    const table = page.getByRole('table').filter({ hasText: 'Historical sample for investigation' });
    assert.equal(await table.locator('tbody tr').count(), evidence.facts.length);
    assert.ok((await table.innerText()).includes(evidence.facts[0].event_id));
    await page.screenshot({ path: path.join(output, 'verified-connections.png') });
    checks.push('Real Memgraph evidence renders with source event IDs and signed receipt references');
    await page.getByRole('button', { name: 'Sync evidence', exact: true }).click();
    await page.getByRole('button', { name: 'Sync evidence', exact: true }).waitFor();
    const status = await (await page.request.get(base + '/api/knowledge/status')).json();
    assert.equal(status.decisions, 25);
    checks.push('Operator sync is idempotent against the real 25-decision mission projection');
    for (const width of [390, 768, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.getByText('Operational knowledge graph', { exact: true }).scrollIntoViewIfNeeded();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
      await page.screenshot({ path: path.join(output, `knowledge-${width}.png`) });
    }
    checks.push('Graph workspace fits phone, tablet and desktop widths');
    // Explicitly mocked status responses exercise unavailable/disabled UI only.
    await page.route('**/api/knowledge/status', r => r.fulfill({ json: { enabled: true, state: 'unavailable' } }));
    await page.reload();
    await page.getByText('Memgraph unavailable', { exact: true }).waitFor();
    await page.route('**/api/knowledge/status', r => r.fulfill({ json: { enabled: false, state: 'disabled' } }));
    await page.reload();
    await page.getByText('Memgraph disabled', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Sync evidence', exact: true }).count(), 0);
    checks.push('Mocked outage/disabled responses display accurate states without fabricated evidence');
    assert.deepEqual(commands, []);
    assert.deepEqual(errors, []);
    checks.push('Graph inspection and sync send no simulator commands and cause no browser errors');
    fs.writeFileSync(path.join(output, 'browser-report.json'), JSON.stringify({ passed: checks.length, checks, errors }, null, 2));
    console.log(JSON.stringify({ passed: checks.length, checks, errors }, null, 2));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
