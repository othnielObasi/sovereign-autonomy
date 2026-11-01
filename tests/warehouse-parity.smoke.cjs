// Exercises the actual run page in both renderers. All API/WS data is a fixture;
// mutations fail the test, so testing map controls cannot execute a robot move.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}),
    args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    page.setDefaultTimeout(90000);
    const errors = [], mutations = [];
    page.on('pageerror', e => { errors.push(e.message); console.error(e.message); });
    const goal = { x: 7, y: 7 };
    const plan = { waypoints: [{ x: 3, y: 4, max_speed: 0.3 }, { x: 7, y: 4, max_speed: 0.4 }, { ...goal, max_speed: 0.3 }], rationale: 'Parity fixture', all_approved: true };
    let telemetry = { x: 3, y: 3.5, theta: 0, speed: 0.3, target: goal,
      human: { x: 5, y: 5, name: 'Primary worker' }, walking_humans: [], obstacles: [], idle_robots: [], site_constraints: [] };
    const world = { geofence: { min_x: 0, max_x: 12, min_y: 0, max_y: 10 },
      racks: [{ id: 'R-1', x1: 9, x2: 11, y: 5, depth: 1 }],
      zones: [{ name: 'aisle', rect: { min_x: 0, max_x: 12, min_y: 0, max_y: 10 } }],
      features: [], bays: [{ id: 'A-01', ...goal, type: 'pick', side: 'north' }] };
    const events = [{ id: 1, type: 'PLAN', ts: new Date().toISOString(), payload: { source: 'nemotron', plan } },
      { id: 2, type: 'DECISION', ts: new Date().toISOString(), payload: { proposal: { intent: 'WAIT', params: {} }, governance: { decision: 'DENIED', risk_score: 0.9, reasons: ['Worker nearby'], required_action: 'STOP', policy_results: [] } } }];
    let socket;
    await page.routeWebSocket('**/ws/runs/parity-fixture', ws => {
      socket = ws;
      ws.onMessage(message => { if (message === 'hello') {
        ws.send(JSON.stringify({ kind: 'telemetry', data: telemetry }));
        ws.send(JSON.stringify({ kind: 'event', data: { policy_state: 'STOP' } }));
      } });
    });
    await page.route('**/api/**', async route => {
      const request = route.request(), path = new URL(request.url()).pathname.replace('/api', '');
      if (request.method() !== 'GET') { mutations.push(path); return route.fulfill({ status: 403, json: { detail: 'Mutations disabled in parity test' } }); }
      const data = path === '/sim/world' ? world : path === '/sim/telemetry' ? telemetry :
        path === '/runs/parity-fixture' ? { id: 'parity-fixture', mission_id: 'parity-mission', status: 'running' } :
        path === '/missions/parity-mission' ? { id: 'parity-mission', title: 'Move to A-01', goal, status: 'executing' } :
        path.endsWith('/events') ? events : path.endsWith('/path_preview') ? { points: [{ x: 3, y: 3.5 }, goal] } :
        path.endsWith('/risk-heatmap') ? { cells: [{ x: 4, y: 4, risk: 0.9 }] } :
        path.endsWith('/executed-path') ? { points: [{ x: 2, y: 3.5 }, { x: 3, y: 3.5 }], destination_bay_id: 'A-01' } :
        path === '/policies/active' ? { parameters: { HUMAN_STOP_RADIUS_M: 1, HUMAN_SLOW_RADIUS_M: 3 } } : null;
      return data === null ? route.fulfill({ status: 404, json: { detail: 'Not in fixture' } }) : route.fulfill({ json: data });
    });
    await page.goto(`${process.env.APP_URL || 'http://127.0.0.1:3000'}/runs/parity-fixture?q=low`, { timeout: 120000, waitUntil: 'domcontentloaded' });
    const summary = page.getByLabel('Warehouse map status');
    await summary.waitFor({ state: 'attached' }).catch(async error => {
      console.error('Run page:', (await page.locator('body').innerText()).slice(0, 6000));
      console.error('WebSocket fixture connected:', !!socket);
      throw error;
    });
    assert.ok(socket, 'the run must connect its shared WebSocket');
    socket.send(JSON.stringify({ kind: 'event', data: { policy_state: 'STOP' } }));
    await summary.filter({ hasText: 'Execution STOP.' }).waitFor({ state: 'attached' });
    await summary.filter({ hasText: 'Risk cells 1.' }).waitFor({ state: 'attached' });
    assert.match(await summary.textContent(), /Proposed path 2 points\. Approved plan 3 waypoints\. Executed path 2 points/);
    console.log('Run data reaches 3D: proposed/approved/executed paths, risk cells, STOP state');
    await page.getByRole('checkbox', { name: 'Heatmap', exact: true }).uncheck();
    await summary.filter({ hasText: 'Heatmap off.' }).waitFor({ state: 'attached' });
    await page.getByRole('checkbox', { name: 'Trail', exact: true }).uncheck();
    await summary.filter({ hasText: 'Trail off.' }).waitFor({ state: 'attached' });
    for (const x of [3.2, 3.4]) {
      telemetry = { ...telemetry, x };
      socket.send(JSON.stringify({ kind: 'telemetry', data: telemetry }));
      await page.waitForTimeout(500);
    }
    await summary.filter({ hasText: /Trail samples ([2-9]|[1-9]\d+)\./ }).waitFor({ state: 'attached' });
    const samples = Number((await summary.textContent()).match(/Trail samples (\d+)/)[1]);
    assert.ok(samples >= 2);
    await page.getByRole('button', { name: 'Floor plan', exact: true }).click();
    await summary.waitFor({ state: 'detached' });
    assert.equal(await page.getByRole('checkbox', { name: 'Heatmap', exact: true }).isChecked(), false);
    await page.getByRole('button', { name: '3D warehouse', exact: true }).click();
    await summary.filter({ hasText: 'Trail off.' }).waitFor({ state: 'attached' });
    assert.ok(Number((await summary.textContent()).match(/Trail samples (\d+)/)[1]) >= samples,
      'switching renderers must retain all samples, including telemetry received during the switch');
    await page.getByRole('checkbox', { name: 'Heatmap', exact: true }).check();
    await page.getByRole('checkbox', { name: 'Trail', exact: true }).check();
    await page.locator('span.cursor-pointer').filter({ hasText: '(3,4)' }).first().hover();
    await page.getByText(/Waypoint 1 · 3\.0, 4\.0 m/).waitFor();
    await page.getByRole('button', { name: 'Minimap', exact: true }).click();
    await page.getByRole('img', { name: /Warehouse minimap/ }).waitFor({ state: 'detached' });
    await page.getByRole('button', { name: 'Minimap', exact: true }).click();
    await page.getByRole('img', { name: /Warehouse minimap/ }).click();
    await page.getByRole('button', { name: 'Fullscreen', exact: true }).click();
    await page.getByRole('button', { name: 'Exit fullscreen', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Exit fullscreen', exact: true }).click();
    assert.deepEqual(mutations, []);
    assert.deepEqual(errors, []);
    console.log('PASS: 2D/3D shared toggles, trail persistence, waypoint hover, minimap navigation, fullscreen; no robot mutations or page errors.');
    await page.close();
  } finally { await Promise.race([browser.close(), new Promise(resolve => setTimeout(resolve, 10000))]); }
})().then(() => process.exit(0)).catch(error => { console.error(error); process.exit(1); });
