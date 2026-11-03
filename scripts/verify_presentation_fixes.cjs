// Isolated preview only. Mutates a short test mission; never use against port 19300.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.PUBLIC_BASE_URL || 'http://127.0.0.1:19310';
assert.equal(new URL(base).port, '19310', 'Use the isolated presentation preview');
const out = path.resolve('docs/validation/2026-11-03-presentation-fixes');
fs.mkdirSync(out, { recursive: true });
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  const errors = [], checks = [], dimensions = [];
  page.on('pageerror', e => errors.push(e.message));
  const check = (name, condition) => { assert.ok(condition, name); checks.push(name); console.log('PASS', name); };
  let runId, headers;
  try {
    const world = await (await page.request.get(base + '/api/sim/world')).json();
    const policies = await (await page.request.get(base + '/api/policies')).json();
    check('Displayed geofence matches the current facility', JSON.stringify(policies.find(p => p.policy_id === 'GEOFENCE_01').parameters) === JSON.stringify(world.geofence));
    await page.goto(base + '/');
    check('Outcome headline and full lifecycle are visible', await page.getByRole('heading', { name: /Give robots a mission/ }).count() && await page.locator('#mission-lifecycle').count());
    check('Live proof supplements the original fallback disclosure', (await page.locator('body').innerText()).includes('88 audit events') && (await page.locator('body').innerText()).includes('fallback planner'));
    await page.screenshot({ path: path.join(out, 'landing-desktop.png'), fullPage: true });
    await page.goto(base + '/how-it-works');
    await page.getByRole('link', { name: /workspace/i }).first().waitFor();
    const links = await page.locator('#cap-results a').evaluateAll(es => es.map(e => e.getAttribute('href')));
    check('All 22 guide capability cards link to workspace tools', links.length === 22);
    check('Site intelligence opens run site/vision inspection', links.includes('/runs?inspect=intel'));
    check('Memory opens memory inspection', links.includes('/runs?inspect=memory'));
    await page.goto(base + '/missions');
    await page.getByRole('button', { name: /^Navigate to/ }).first().waitFor();
    const presetLabels = await page.getByRole('button', { name: /^Navigate to/ }).allTextContents();
    check('Presets use destinations from the current facility', presetLabels.length > 0 && presetLabels.every(t => world.bays.some(b => t.includes(b.label || b.id))));
    check('Planner status reports fallback consistently', (await page.locator('main').innerText()).includes('deterministic fallback'));
    await page.goto(base + '/authority');
    await page.getByRole('button', { name: 'Voice not configured' }).waitFor();
    check('Unconfigured voice control is disabled', await page.getByRole('button', { name: 'Voice not configured' }).isDisabled());
    // Populate the original mobile failure case using a clearly labelled response fixture.
    await page.route('**/api/authority/evidence*', route => route.fulfill({ json: { events: [{ kind: 'permit_used', action_id: 'presentation-fixture-run:' + 'long-action-id-'.repeat(12), timestamp: 1793730000 }] } }));
    const token = (await (await page.request.post(base + '/api/auth/dev-token?role=admin')).json()).access_token;
    headers = { Authorization: 'Bearer ' + token };
    const telemetry = await (await page.request.get(base + '/api/sim/telemetry')).json();
    const mission = await (await page.request.post(base + '/api/missions', { headers, data: { title: 'Presentation validation: short navigation', robot_id: 'robot-1', goal: { x: telemetry.x, y: telemetry.y - 1 } } })).json();
    const started = await page.request.post(base + '/api/missions/' + mission.id + '/start', { headers, data: { mission_id: mission.id } });
    check('Short isolated mission starts through existing API', started.ok());
    runId = (await started.json()).run_id;
    await page.goto(base + '/runs?inspect=memory');
    await page.getByText('Choose a run to inspect memory.', { exact: false }).waitFor();
    const runLink = page.locator(`a[href*="${runId}"][href*="focus=memory"]`).first();
    await runLink.click();
    await page.getByPlaceholder('Search agent memory...').waitFor();
    check('Memory link opens run Analysis and memory search', page.url().includes('tab=analysis') && await page.getByPlaceholder('Search agent memory...').isVisible());
    await page.goto(base + '/runs/' + runId + '?view=2d');
    await page.locator('section[aria-label="Recorded execution progress"]').waitFor();
    await page.waitForTimeout(1800);
    const progress = page.locator('section[aria-label="Recorded execution progress"]');
    check('Execution progress renders recorded evidence', (await progress.innerText()).includes('Admission:'));
    // Approved decision + controller refusal must never become an executing banner.
    await page.route('**/api/runs/*/presentation', route => route.fulfill({ json: {
      run_id: runId, status: 'running', plan: { payload: { source: 'fallback', plan: { model_used: 'site_router', graph_history: { state: 'ready', offered_event_ids: ['presentation-fixture-history-event'] } } } }, first_admission: { id: 'old-admission' },
      decision: { payload: { governance: { decision: 'APPROVED' } } },
      authority: { ts: '2026-11-03T20:00:00', payload: { event: 'permit_refused', reason: 'trajectory_obstacle_clearance' } },
      execution: { ts: '2026-11-03T20:00:01', payload: { command: { intent: 'MOVE_TO' }, result: { ok: false, rejected: true, reason: 'trajectory_obstacle_clearance' }, verified: false } }
    } }));
    await page.route('**/api/runs/' + runId, route => route.fulfill({ json: { id: runId, mission_id: mission.id, status: 'running' } }));
    await page.reload();
    await page.getByText('Movement refused', { exact: true }).first().waitFor();
    check('Graph provenance reads the saved plan metadata', (await page.locator('#planner-context').innerText()).includes('presentation-fixture-history-event'));
    check('Approved but refused action is shown as refused', (await progress.innerText()).includes('trajectory obstacle clearance'));
    await page.screenshot({ path: path.join(out, 'run-refused-desktop.png'), fullPage: false });
    await page.goto(base + '/mission-control?view=2d&panel=scenarios#mission-evidence');
    await page.getByRole('button', { name: 'Floor plan', exact: true }).waitFor();
    check('Scenario deep link opens the correct tab', await page.getByRole('tab', { name: 'Scenario lab' }).getAttribute('aria-selected') === 'true');
    check('Floor view query is honored', await page.getByRole('button', { name: 'Floor plan', exact: true }).getAttribute('aria-pressed') === 'true');
    await page.goto(base + '/policies?tab=rules');
    await page.getByLabel('Rule threshold').waitFor();
    check('Rules deep link exposes staged controls', await page.getByRole('button', { name: 'Create proposal' }).count());
    await page.getByLabel('Rule threshold').selectOption('HUMAN_STOP_RADIUS_M');
    await page.getByLabel('Proposed value').fill('2');
    await page.getByLabel('Rule change reason').fill('Presentation validation fixture; do not activate');
    await page.getByRole('button', { name: 'Create proposal' }).click();
    await page.getByText('create recorded.', { exact: false }).waitFor();
    check('Operator can create a proposal without activating rules', await page.getByRole('button', { name: 'Replay evaluation' }).count() && !(await page.getByRole('button', { name: 'Activate approved rules' }).count()));
    await page.getByRole('button', { name: 'Reject with reason' }).click();
    await page.getByText('reject recorded.', { exact: false }).waitFor();
    const runtime = await (await page.request.get(base + '/api/health')).json();
    await page.route('**/api/health', route => route.fulfill({ json: { ...runtime, public_demo: true } }));
    await page.reload();
    await page.getByText('Rule editing is read-only in this public workspace.', { exact: true }).waitFor();
    check('Public workspace blocks rule mutation controls', await page.getByRole('button', { name: 'Create proposal' }).isDisabled() && await page.getByLabel('Rule threshold').isDisabled());
    await page.unroute('**/api/health');
    for (const route of ['/',  '/how-it-works', '/mission-control?view=2d', '/authority', '/capabilities', '/operations', '/policies?tab=rules', '/runs/' + runId + '?view=2d']) {
      await page.setViewportSize({ width: 390, height: 1000 });
      await page.goto(base + route, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(1400);
      const d = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth }));
      dimensions.push({ route, ...d });
      check('Mobile fits: ' + route, d.document <= d.viewport + 1);
      if (['/authority','/capabilities','/operations','/'].includes(route)) await page.screenshot({ path: path.join(out, (route === '/' ? 'landing' : route.slice(1)) + '-mobile.png'), fullPage: true });
    }
    check('No page JavaScript errors', errors.length === 0);
    fs.writeFileSync(path.join(out, 'checks.json'), JSON.stringify({ base, scope: 'Isolated key-free stack; one short navigation run and rejected rule proposal; refusal and long dispatch IDs use labelled browser fixtures', checks, dimensions, errors }, null, 2));
  } finally {
    if (runId) await page.request.post(base + '/api/runs/' + runId + '/stop', { headers }).catch(() => {});
    await browser.close();
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
