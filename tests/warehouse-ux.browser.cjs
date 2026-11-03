// Against the isolated pharma validation stack only. Real controller, no model calls.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const base='http://127.0.0.1:19300';
const out=path.resolve('docs/validation/2026-11-03-warehouse-ux');
fs.mkdirSync(out,{recursive:true});
const report={checks:[],errors:[],samples:[],scope:'Real isolated simulator/backend, HTTP fallback with WebSockets unavailable, software WebGL; no model calls'};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function until(fn,label,timeout=60000){const end=Date.now()+timeout;while(Date.now()<end){const value=await fn();if(value)return value;await sleep(500);}throw new Error(label);}
function probes(){
  const roots=new Set();
  window.__REACT_DEVTOOLS_GLOBAL_HOOK__={supportsFiber:true,inject:()=>1,onCommitFiberUnmount(){},onCommitFiberRoot(_id,root){roots.add(root);}};
  window.facilityProbe=()=>{
    const seen=new Set();
    function find(f){if(!f||seen.has(f))return null;seen.add(f);const o=f.stateNode?.object||f.stateNode;if(o?.isObject3D&&o.name==='facility-environment')return o;return find(f.child)||find(f.sibling);}
    for(const root of roots){const o=find(root.current);if(!o)continue;o.updateMatrixWorld(true);const parts=[],ceilings=[];o.traverse(n=>{
      if(n.name.startsWith('facility-partition-')){const boxes=[];let glass=0;n.traverse(m=>{if(m.isMesh){m.geometry.computeBoundingBox();const b=m.geometry.boundingBox.clone().applyMatrix4(m.matrixWorld);boxes.push([b.min.toArray(),b.max.toArray()]);if(m.material.transparent){const isPlane=m.geometry.type==='PlaneGeometry';glass+=isPlane?1:100;}}});parts.push({id:n.name.replace('facility-partition-',''),boxes,glass});}
      if(n.name==='facility-ceiling')ceilings.push(n.visible);
    });return {parts,ceilings};}return null;
  };
  // Force a real supported fallback case without sending traffic to another app.
  window.WebSocket=class {constructor(){setTimeout(()=>{this.onerror?.({});this.onclose?.({});},30);}send(){}close(){}};
  window.requestAnimationFrame=callback=>setTimeout(()=>callback(performance.now()),200);
  window.cancelAnimationFrame=id=>clearTimeout(id);
}
(async()=>{
  const browser=await chromium.launch({headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const context=await browser.newContext({viewport:{width:1440,height:1050},deviceScaleFactor:2,reducedMotion:'reduce'});
  context.setDefaultTimeout(45000);await context.addInitScript(probes);
  const page=await context.newPage();page.on('pageerror',e=>report.errors.push(e.message));
  let runId,headers;
  const get=async p=>{const r=await context.request.get(base+'/api'+p);assert.ok(r.ok(),p);return r.json();};
  const post=async(p,data)=>{const r=await context.request.post(base+'/api'+p,{headers,data});assert.ok(r.ok(),`${p}: ${r.status()} ${await r.text()}`);return r.json();};
  const shot=async name=>page.screenshot({path:path.join(out,name+'.png'),fullPage:true,timeout:30000});
  try{
    const world=await get('/sim/world');
    await page.goto(base+'/mission-control');
    await page.getByRole('button',{name:'Floor plan',exact:true}).click();
    await page.locator('[data-room-label]').first().waitFor();
    const geometry=()=>page.locator('[data-layout-id]').evaluateAll(nodes=>nodes.map(n=>({id:n.dataset.layoutId,x:+n.getAttribute('x'),y:+n.dataset.worldY,screenY:+n.getAttribute('y'),width:+n.getAttribute('width'),height:+n.getAttribute('height')})));
    const before=await geometry();assert.equal(before.length,world.racks.length);
    for(const shape of before){const rack=world.racks.find(r=>r.id===shape.id);assert.deepEqual(shape,{id:rack.id,x:rack.x1,y:rack.y,screenY:world.geofence.min_y+world.geofence.max_y-(rack.y+(rack.depth||1)),width:rack.x2-rack.x1,height:rack.depth||1});}
    await page.waitForTimeout(2200);assert.deepEqual(await geometry(),before);
    for(const viewport of [{width:1440,height:1050},{width:390,height:844}]){
      await page.setViewportSize(viewport);await page.waitForTimeout(600);
      const labels=await page.locator('[data-room-label]').evaluateAll(nodes=>nodes.map(n=>({text:n.textContent,height:n.getBoundingClientRect().height,lines:n.querySelectorAll('tspan').length})));
      assert.equal(labels.length,6);assert.ok(labels.every(l=>l.height/l.lines>=11));
      await shot(viewport.width===390?'floor-plan-mobile':'floor-plan-desktop');
    }
    report.checks.push('All 28 layout footprints match the world and stay stationary across refresh; six room labels readable at desktop and mobile sizes');
    await page.setViewportSize({width:1440,height:1050});
    const token=(await post('/auth/dev-token?role=admin')).access_token;headers={Authorization:`Bearer ${token}`};
    await page.evaluate(token=>localStorage.setItem('sovereign-autonomy.session.v1',JSON.stringify({token,user:'validation',role:'admin'})),token);
    const mission=await post('/missions',{title:'Warehouse UX robot-2 delivery',bay_id:'Q-01',robot_id:'robot-2'});
    runId=(await post('/missions/'+mission.id+'/start')).run_id;report.runId=runId;
    await post('/runs/'+runId+'/pause');
    await page.goto(base+'/runs/'+runId+'?q=low');
    await page.getByText('Live polling',{exact:true}).waitFor();
    await page.waitForFunction(()=>window.facilityProbe()?.parts.length===16);
    const structure=await page.evaluate(()=>window.facilityProbe());assert.ok(structure.parts.every(p=>p.glass===1));
    for(const partition of structure.parts){const rack=world.racks.find(r=>r.id===partition.id);const xs=partition.boxes.flatMap(b=>[b[0][0],b[1][0]]),zs=partition.boxes.flatMap(b=>[b[0][2],b[1][2]]);assert.ok(Math.abs(Math.min(...xs)-rack.x1)<.001);assert.ok(Math.abs(Math.max(...xs)-rack.x2)<.001);assert.ok(Math.abs(Math.min(...zs)+rack.y+rack.depth)<.001);assert.ok(Math.abs(Math.max(...zs)+rack.y)<.001);}
    await page.waitForTimeout(1500);assert.deepEqual((await page.evaluate(()=>window.facilityProbe())).parts,structure.parts);
    report.checks.push('All 16 3D partition footprints match collision geometry and remain stable; glass uses non-overlapping single surfaces');
    await page.getByRole('button',{name:'Display settings',exact:true}).click();
    await page.getByLabel('Roof visibility').selectOption('show');
    await page.waitForFunction(()=>window.facilityProbe()?.ceilings[0]===true);
    await shot('roof-visible');
    await page.getByLabel('Roof visibility').selectOption('hide');
    await page.waitForFunction(()=>window.facilityProbe()?.ceilings[0]===false);
    await page.getByLabel('Roof visibility').selectOption('auto');
    await page.getByRole('button',{name:'Close warehouse options',exact:true}).click();
    await page.getByRole('button',{name:'Robot eye',exact:true}).click();
    await page.waitForFunction(()=>window.facilityProbe()?.ceilings[0]===true);
    await shot('interior-roof-and-lights');
    await page.getByRole('button',{name:'Overview',exact:true}).click();
    await page.waitForFunction(()=>window.facilityProbe()?.ceilings[0]===false);
    await page.getByRole('button',{name:'View guide',exact:true}).click();
    await page.getByText('A delay does not mean the robot has stopped.',{exact:false}).waitFor();
    await shot('warehouse-view-guide');
    await page.getByRole('button',{name:'Close warehouse options',exact:true}).click();
    await page.getByRole('button',{name:'Map layers',exact:true}).click();
    await page.getByRole('button',{name:'Minimap',exact:true}).click();
    await page.getByRole('button',{name:'Minimap',exact:true}).click();
    await page.getByRole('button',{name:'Close warehouse options',exact:true}).click();
    report.checks.push('Toolbar separates camera, layers, display and guide; manual roof states and automatic interior/overview ceiling transitions work');
    await page.getByRole('button',{name:'Floor plan',exact:true}).click();
    const canvas=page.locator('canvas').first();
    assert.ok(await canvas.evaluate(c=>c.width>=c.getBoundingClientRect().width*1.9),'Retina drawing buffer');
    await shot('run-floor-plan');
    await page.getByRole('button',{name:'3D warehouse',exact:true}).click();
    await page.getByRole('button',{name:'Inspect robot',exact:true}).click();
    const start=await get('/sim/telemetry?robot_id=robot-2');
    await page.getByText(`Position: ${start.x.toFixed(2)}, ${start.y.toFixed(2)} m`,{exact:true}).waitFor();
    await page.route('**/api/sim/telemetry*',route=>route.abort());
    await page.getByText(/Data delayed/).waitFor({timeout:20000});
    await page.unroute('**/api/sim/telemetry*');
    await page.getByText('Live robot data',{exact:true}).waitFor();
    report.checks.push('With WebSockets unavailable, robot-2 telemetry refreshes through HTTP; interrupted HTTP becomes stale and recovers accurately');
    await page.getByRole('button',{name:'Close inspection',exact:true}).click();
    await page.getByRole('button',{name:/Override & Resume/}).click();
    await until(async()=>{const t=await get('/sim/telemetry?robot_id=robot-2');return Math.hypot(t.x-start.x,t.y-start.y)>.3;},'Robot did not move');
    await post('/runs/'+runId+'/pause');
    await until(async()=>Math.abs((await get('/sim/telemetry?robot_id=robot-2')).speed)<.001,'Pause did not stop robot');
    const held=await get('/sim/telemetry?robot_id=robot-2');await sleep(1200);const held2=await get('/sim/telemetry?robot_id=robot-2');assert.ok(Math.hypot(held.x-held2.x,held.y-held2.y)<.03);
    await post('/runs/'+runId+'/resume');
    await until(async()=>{const t=await get('/sim/telemetry?robot_id=robot-2');report.samples.push({x:t.x,y:t.y,speed:t.speed,t:t.t});return (await get('/runs/'+runId)).status==='completed';},'Delivery did not reach completed state',300000);
    const end=await get('/sim/telemetry?robot_id=robot-2');assert.equal(end.robot_contacts,0);
    const events=await get('/runs/'+runId+'/events?limit=1000');assert.ok(events.some(e=>e.type==='AUTHORITY'&&e.payload?.event==='permit_used'));
    const arrival=events.filter(e=>e.type==='DECISION'&&e.payload?.proposal?.intent==='STOP').at(-1)?.payload?.context?.telemetry;
    assert.ok(arrival&&arrival.robot_id==='robot-2'&&Math.hypot(arrival.x-18,arrival.y-2.5)<.4,'Controller-recorded arrival before automatic simulator parking reset');
    report.motion={start:{x:start.x,y:start.y},arrival:{x:arrival.x,y:arrival.y},afterCompletion:{x:end.x,y:end.y},automaticParkingReset:true,permitsUsed:events.filter(e=>e.type==='AUTHORITY'&&e.payload?.event==='permit_used').length,contacts:end.robot_contacts};
    await shot('completed-delivery');
    report.checks.push('Actual robot-2 moves under used signed permits, stops while paused, resumes and completes at Quality lab with zero robot contacts');
    assert.deepEqual(report.errors,[]);report.passed=true;
  }catch(error){report.passed=false;report.failure=String(error.stack||error);await shot('failure').catch(()=>{});process.exitCode=1;}
  finally{if(runId&&headers){const r=await get('/runs/'+runId).catch(()=>null);if(r&&['planning','running','paused'].includes(r.status))await context.request.post(base+'/api/runs/'+runId+'/stop',{headers}).catch(()=>{});}fs.writeFileSync(path.join(out,'browser-report.json'),JSON.stringify(report,null,2)+'\n');await browser.close();}
  console.log(JSON.stringify({...report,samples:report.samples.length},null,2));
})().catch(e=>{console.error(e);process.exitCode=1;});
