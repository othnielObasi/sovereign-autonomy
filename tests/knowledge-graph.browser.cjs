const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.PUBLIC_BASE_URL || 'http://127.0.0.1:19300';
const out = path.resolve('docs/validation/2026-11-03-knowledge-graph');
fs.mkdirSync(out, { recursive: true });
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  const errors = [], commands = [], checks = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', r => { if (r.method() === 'POST' && /\/(missions|sim|operator|authority)\//.test(r.url())) commands.push(r.url()); });
  const graph = () => page.getByRole('group', { name: 'Interactive mission knowledge graph', exact: true });
  const node = id => graph().locator(`[data-node-id="${id}"]`);
  const inspector = page.getByTestId('graph-inspector');
  try {
    await page.goto(base + '/authority');
    await graph().waitFor();
    const runId = await page.getByLabel('Knowledge graph run').inputValue();
    const source = await (await page.request.get(base + '/api/knowledge/runs/' + runId)).json();
    assert.equal(source.facts.length, 25);
    assert.equal(await graph().locator('[data-node-kind]').count(), 5);
    assert.ok((await node('decision-APPROVED').textContent()).includes('25 observations'));
    assert.equal(await graph().locator('[data-node-id="policy"]').count(), 0);
    checks.push('Real 25-decision source renders as five connected nodes; zero policy hits produce no invented policy node');
    await node('mission').click();
    await inspector.getByText(source.facts[0].mission_id, { exact: true }).waitFor();
    assert.equal(await node('mission').getAttribute('aria-pressed'), 'true');
    assert.equal(await node('location').getAttribute('opacity'), '0.35');
    await node('run').focus();
    await page.keyboard.press('Enter');
    assert.equal(await node('run').getAttribute('aria-pressed'), 'true');
    await page.keyboard.press('Escape');
    assert.equal(await node('run').getAttribute('aria-pressed'), 'false');
    await page.keyboard.press('Space');
    assert.equal(await node('run').getAttribute('aria-pressed'), 'true');
    checks.push('Pointer, Tab-focus/Enter/Space selection and Escape clearing expose evidence and highlight immediate connections');
    await page.getByRole('button', { name: 'Inspect a decision', exact: true }).click();
    assert.equal(await page.getByLabel('Decision to inspect').locator('option').count(), 25);
    await inspector.getByText(source.facts[0].event_id, { exact: true }).waitFor();
    await page.getByLabel('Decision to inspect').selectOption(source.facts[4].event_id);
    await inspector.getByText(source.facts[4].event_id, { exact: true }).waitFor();
    await inspector.getByText('Source context and integrity', { exact: true }).click();
    await inspector.getByText(source.facts[4].event_hash, { exact: true }).waitFor();
    assert.equal(await inspector.getByRole('link', { name: 'Open mission record ↗' }).getAttribute('href'), '/runs/' + runId);
    checks.push('Single-decision picker preserves actual event, receipt, integrity hash and mission link');
    await page.getByLabel('Graph decision filter').selectOption('blocked');
    await page.getByText('No decisions match this filter.', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Show all decisions', exact: true }).click();
    await graph().waitFor();
    await page.getByRole('button', { name: 'Mission overview', exact: true }).click();
    await page.getByRole('button', { name: 'Zoom in graph', exact: true }).click();
    assert.equal(await graph().evaluate(el => el.style.width), '125%');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
    await page.getByRole('button', { name: 'Fit view', exact: true }).click();
    assert.equal(await graph().evaluate(el => el.style.width), '100%');
    checks.push('Empty filter is explained and recoverable; zoom stays inside the graph and Fit view resets it');
    for (const width of [390, 768, 1440]) {
      await page.setViewportSize({ width, height: 1100 });
      await graph().scrollIntoViewIfNeeded();
      await page.waitForFunction(() => {
        const svg = document.querySelector('[aria-label="Interactive mission knowledge graph"]');
        return svg.dataset.layout === (svg.parentElement.clientWidth < 580 ? 'compact' : 'wide');
      });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
      const overlaps = await graph().locator('[data-node-kind]').evaluateAll(nodes => {
        const bounds = nodes.map(n => n.getBoundingClientRect());
        return bounds.some((a, i) => bounds.some((b, j) => i < j && a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top));
      });
      assert.equal(overlaps, false);
      await page.screenshot({ path: path.join(out, `live-graph-${width}.png`) });
    }
    checks.push('Real graph reflows on phone/tablet/desktop with no overlapping nodes or page overflow');
    // Explicitly synthetic API response, used only for branches absent from the live run.
    const fixture = { ...source, facts: Array.from({ length: 30 }, (_, i) => ({
      ...source.facts[i % source.facts.length], event_id: 'fixture-event-' + i, receipt_id: i + 1,
      decision: ['APPROVED', 'DENIED', 'NEEDS_REVIEW'][i % 3],
      policy_hits: i % 3 === 0 ? [] : i % 3 === 1 ? ['HAZARD_EXCLUSION_08'] : ['UNCERTAINTY_04'],
    })) };
    await page.route('**/api/knowledge/runs/*', route => route.fulfill({ json: fixture }));
    await page.reload(); await graph().waitFor();
    assert.equal(await graph().locator('[data-node-kind]').count(), 8);
    await node('policy').click();
    await inspector.getByText('Hazard exclusion', { exact: true }).waitFor();
    await inspector.getByText('Uncertain perception', { exact: true }).waitFor();
    await page.getByLabel('Graph decision filter').selectOption('blocked');
    assert.equal(await graph().locator('[data-node-id="decision-APPROVED"]').count(), 0);
    await node('decision-DENIED').click();
    await inspector.getByRole('button', { name: 'Inspect this decision', exact: true }).first().click();
    assert.equal(await page.getByLabel('Decision to inspect').locator('option').count(), 20);
    await node('policy').click();
    await inspector.getByText('HAZARD_EXCLUSION_08', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Mission overview', exact: true }).click();
    await page.getByLabel('Graph decision filter').selectOption('all');
    await page.setViewportSize({ width: 390, height: 1100 });
    await graph().scrollIntoViewIfNeeded();
    await page.waitForFunction(() => document.querySelector('[aria-label="Interactive mission knowledge graph"]').dataset.layout === 'compact');
    const crossingNodes = await graph().evaluate(svg => {
      const nodes = [...svg.querySelectorAll('[data-node-id]')];
      return [...svg.querySelectorAll('path[data-edge-from]')].some(path => {
        const unrelated = nodes.filter(n => n.dataset.nodeId !== path.dataset.edgeFrom && n.dataset.nodeId !== path.dataset.edgeTo);
        const length = path.getTotalLength();
        return Array.from({ length: 40 }, (_, i) => path.getPointAtLength(length * i / 39)).some(point => {
          const screen = new DOMPoint(point.x, point.y).matrixTransform(path.getScreenCTM());
          return unrelated.some(n => { const r = n.getBoundingClientRect(); return screen.x > r.left && screen.x < r.right && screen.y > r.top && screen.y < r.bottom; });
        });
      });
    });
    assert.equal(crossingNodes, false);
    await page.screenshot({ path: path.join(out, 'fixture-mixed-decisions-mobile.png') });
    checks.push('Explicit synthetic mixed-verdict fixture exercises policy connections and filtering; arrows avoid unrelated nodes on mobile');
    assert.deepEqual(commands, []); assert.deepEqual(errors, []);
    checks.push('Graph exploration sends no robot commands and has no browser errors');
    fs.writeFileSync(path.join(out, 'browser-report.json'), JSON.stringify({ passed: checks.length, checks, errors }, null, 2));
    console.log(JSON.stringify({ passed: checks.length, checks, errors }, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
