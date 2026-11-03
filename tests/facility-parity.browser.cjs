// Real isolated stack: BROWSER_SITE_LAYOUT=pharma python scripts/browser_validation_stack.py
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = 'http://127.0.0.1:19300';
const out = path.resolve(process.env.BROWSER_EVIDENCE_DIR || 'docs/validation/2026-11-03-facility-parity');
fs.mkdirSync(out, { recursive: true });
const report = { checks: [], errors: [], scope: 'Shared static facility geometry in real Mission Control and run canvases; isolated pharma simulator; no model calls' };

// Inspect mounted Three objects through React's standard development-tools hook.
// This tests the actual scene graph without adding test interfaces to the product.
function installSceneProbe() {
  const roots = new Set();
  window.__REACT_DEVTOOLS_GLOBAL_HOOK__ = {
    supportsFiber: true, inject: () => 1, onCommitFiberUnmount() {},
    onCommitFiberRoot(_id, root) { roots.add(root); },
  };
  window.facilitySnapshot = () => {
    const visited = new Set();
    function find(fiber) {
      if (!fiber || visited.has(fiber)) return null;
      visited.add(fiber);
      const instance = fiber.stateNode?.object || fiber.stateNode;
      if (instance?.isObject3D && instance.name === 'facility-environment') {
        const meshes = [];
        instance.updateMatrixWorld(true);
        instance.traverse(object => {
          if (!object.isMesh) return;
          // Shapes have random UUIDs per mount; compare their contents instead.
          const parameters = JSON.parse(JSON.stringify(object.geometry.parameters || {}, (key, value) => key === 'uuid' ? undefined : value));
          object.geometry.computeBoundingBox();
          const containers = [];
          for (let parent=object.parent;parent && parent!==instance;parent=parent.parent) if(parent.name) containers.push(parent.name);
          meshes.push({ geometry: object.geometry.type, parameters,
            containers, worldMinY: object.geometry.boundingBox.clone().applyMatrix4(object.matrixWorld).min.y,
            bounds: [object.geometry.boundingBox.min.toArray(), object.geometry.boundingBox.max.toArray()],
            position: object.position.toArray(), rotation: object.rotation.toArray(),
            worldMatrix: object.matrixWorld.toArray(),
            color: object.material?.color?.getHexString() });
        });
        return meshes;
      }
      return find(fiber.child) || find(fiber.sibling);
    }
    for (const root of roots) { const result = find(root.current); if (result?.length) return result; }
    return null;
  };
  // Software-rendered test host: limit rendering, not simulator or telemetry.
  window.requestAnimationFrame = cb => setTimeout(() => cb(performance.now()), 200);
  window.cancelAnimationFrame = id => clearTimeout(id);
}

(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1050 }, reducedMotion: 'reduce' });
  context.setDefaultTimeout(60000);
  await context.addInitScript(installSceneProbe);
  let runId, headers;
  const page = await context.newPage();
  page.on('pageerror', error => report.errors.push(error.message));
  const get = async p => { const r = await context.request.get(base + '/api' + p); assert.ok(r.ok(), p); return r.json(); };
  const post = async (p, data) => { const r = await context.request.post(base + '/api' + p, { headers, data }); assert.ok(r.ok(), `${p}: ${r.status()} ${await r.text()}`); return r.json(); };
  async function snapshot() {
    await page.waitForFunction(() => window.facilitySnapshot()?.length > 100, null, { timeout: 90000 });
    return page.evaluate(() => window.facilitySnapshot());
  }
  try {
    const landing = await context.request.get(base + '/');
    assert.equal(await landing.text(), fs.readFileSync('frontend/public/landing/index.html', 'utf8'));
    await page.goto(base);
    await page.getByRole('heading', { name: /Intelligence that acts/ }).waitFor();
    await page.getByRole('link', { name: /Open the app/ }).first().waitFor();
    await page.screenshot({ path: path.join(out, 'restored-landing.png'), fullPage: true });
    report.checks.push('Root serves the exact restored landing file and original app link');

    const world = await get('/sim/world');
    assert.equal(world.site.name, 'pharma');
    assert.equal(world.racks.filter(r => r.kind === 'partition').length, 16);
    assert.equal(world.racks.filter(r => r.kind === 'bench').length, 12);
    report.world = { site: world.site, geofence: world.geofence, bays: world.bays.map(b => b.id), racks: world.racks.length };
    await page.goto(base + '/mission-control');
    await page.getByRole('heading', { name: 'Meridian Life Sciences' }).waitFor();
    const controlGeometry = await snapshot();
    const groups = [...new Set(controlGeometry.flatMap(mesh => mesh.containers))];
    report.architecture = {
      partitions: groups.filter(name=>name.startsWith('facility-partition-')).length,
      entrances: groups.filter(name=>name.startsWith('facility-open-entrance-')).length,
      perimeterWalls: groups.filter(name=>name.startsWith('facility-perimeter-wall-')).length,
      ceiling: groups.includes('facility-ceiling'),
    };
    assert.deepEqual(report.architecture,{partitions:16,entrances:6,perimeterWalls:4,ceiling:true});
    assert.ok(controlGeometry.filter(mesh=>mesh.containers.some(name=>name.startsWith('facility-open-entrance-'))).every(mesh=>mesh.worldMinY>2.6),'Existing entrances must remain open below 2.6m');
    await page.screenshot({ path: path.join(out, 'mission-control.png'), fullPage: true });
    report.checks.push('Mission Control mounts full cleanroom geometry from the simulator world');
    await page.getByRole('button',{name:'Expand facility',exact:true}).click();
    await page.waitForFunction(()=>!!document.fullscreenElement);
    await page.waitForTimeout(1200);
    await page.screenshot({path:path.join(out,'facility-overview-expanded.png')});
    await page.getByRole('button',{name:'Robot eye',exact:true}).click();
    await page.waitForTimeout(1500);
    await page.screenshot({path:path.join(out,'facility-interior-eye.png')});
    await page.getByRole('button',{name:'Overview',exact:true}).click();
    await page.getByRole('button',{name:'Exit fullscreen',exact:true}).click();
    await page.waitForFunction(()=>!document.fullscreenElement);
    report.checks.push('All 16 partitions, six open entrances, four perimeter walls and ceiling are modeled; expanded overview and interior camera work');

    headers = { Authorization: `Bearer ${(await post('/auth/dev-token?role=admin')).access_token}` };
    const mission = await post('/missions', { title: 'Facility parity visual check', bay_id: 'P-01', robot_id: 'robot-1' });
    runId = (await post('/missions/' + mission.id + '/start')).run_id;
    assert.ok(runId, 'Mission start returns a run identifier');
    report.runId = runId;
    await post('/runs/' + runId + '/pause');
    await page.goto(base + '/runs/' + runId);
    await page.getByText('Facility parity visual check', { exact: true }).first().waitFor();
    const runGeometry = await snapshot();
    assert.deepEqual(runGeometry, controlGeometry, 'Run view must mount exactly the same static meshes, transforms, dimensions and colors');
    report.meshes = runGeometry.length;
    await page.screenshot({ path: path.join(out, 'run-full-facility.png'), fullPage: true });
    await page.getByRole('button', { name: 'Fullscreen', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Reset camera', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Map layers', exact: true }).click();
    await page.getByRole('button', { name: 'Minimap', exact: true }).waitFor();
    const route = page.getByRole('button', { name: /Hide route/ });
    if (await route.count()) {
      await route.click();
      await page.getByRole('button', { name: /Show route/ }).click();
    }
    await page.getByRole('button', { name: 'Close warehouse options', exact: true }).click();
    await page.getByText('Governance Decision', { exact: true }).waitFor();
    report.checks.push('Run mounts identical facility geometry while retaining fullscreen, reset, minimap and governance panel');
    await page.getByRole('button', { name: 'Floor plan', exact: true }).click();
    await page.getByRole('button', { name: '3D warehouse', exact: true }).click();
    assert.deepEqual(await snapshot(), controlGeometry);
    report.checks.push('Switching floor plan to 3D preserves the complete facility');
    assert.deepEqual(report.errors, []);
    report.passed = true;
  } catch (error) {
    report.passed = false; report.failure = String(error.stack || error);
    await page.screenshot({ path: path.join(out, 'failure.png'), fullPage: true, timeout: 15000 }).catch(() => {});
    process.exitCode = 1;
  } finally {
    if (runId && headers) await context.request.post(base + '/api/runs/' + runId + '/stop', { headers }).catch(() => {});
    fs.writeFileSync(path.join(out, 'browser-report.json'), JSON.stringify(report, null, 2) + '\n');
    await browser.close();
  }
  console.log(JSON.stringify(report, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; });
