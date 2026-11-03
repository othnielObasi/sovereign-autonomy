const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const base='http://127.0.0.1:19310';
const out=path.resolve('docs/validation/2026-11-03-original-design-study');
fs.mkdirSync(out,{recursive:true});
const report={revision:'2d3a984',scope:'Original source, original dark palette, factory simulator, isolated state; no model calls',rendering:'Original 3D inspection and robot-eye screenshots captured separately; detailed workflow uses WebGL fallback because software rendering reached about 1 FPS',steps:[],pageErrors:[],screens:[]};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function until(fn,timeout=45000){const end=Date.now()+timeout;while(Date.now()<end){const v=await fn();if(v)return v;await sleep(500);}return null;}
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const context=await browser.newContext({viewport:{width:1380,height:980},reducedMotion:'reduce'});
 context.setDefaultTimeout(45000);
 await context.addInitScript(()=>{window.requestAnimationFrame=cb=>setTimeout(()=>cb(performance.now()),200);window.cancelAnimationFrame=id=>clearTimeout(id);});
 await context.addInitScript(()=>{const original=HTMLCanvasElement.prototype.getContext;HTMLCanvasElement.prototype.getContext=function(kind,...args){if(String(kind).includes('webgl'))return null;return original.call(this,kind,...args);};});
 const page=await context.newPage();page.on('pageerror',e=>{if(!/WebGL|R3F|THREE/i.test(e.message))report.pageErrors.push(e.message);});
 let runId,headers;
 const get=async p=>(await context.request.get(base+'/api'+p)).json();
 const shot=async name=>{await page.screenshot({path:path.join(out,name+'.png'),fullPage:true,timeout:30000});report.screens.push(name+'.png');};
 try{
  const token=await (await context.request.post(base+'/api/auth/dev-token?role=admin')).json();headers={Authorization:`Bearer ${token.access_token}`};
  await page.goto(base+'/twin?q=low');
  await page.getByRole('button',{name:'Plan mission',exact:true}).waitFor();
  report.steps.push({name:'Original 3D views inspected separately',screens:['01-original-twin-inspection.png','02-original-robot-eye.png']});
  await page.getByRole('button',{name:'Plan mission',exact:true}).click();
  await page.getByLabel('Destination bay').selectOption('L-05');
  await page.getByLabel('Mission instruction').fill('Original design study: factory line-side delivery');
  await shot('03-original-mission-draft');
  await page.getByRole('button',{name:'Save mission draft',exact:true}).click();
  await page.getByRole('button',{name:'Start governed run',exact:true}).waitFor();
  report.steps.push({name:'Draft checkpoint',observed:await page.getByRole('complementary',{name:'Mission controls'}).innerText()});
  await page.getByRole('button',{name:'Start governed run',exact:true}).click();
  await page.waitForURL(/\/runs\//);runId=new URL(page.url()).pathname.split('/').pop();
  await page.goto(base+'/runs/'+runId+'?q=low');
  await page.getByRole('button',{name:'Floor plan',exact:true}).click();
  const events=()=>get('/runs/'+runId+'/events?limit=1000');
  await until(async()=>(await events()).some(e=>e.type==='DECISION'));
  const before=await events();
  report.steps.push({name:'Start navigates into detailed run',runId,eventTypes:[...new Set(before.map(e=>e.type))],latestDecision:before.filter(e=>e.type==='DECISION').at(-1)?.payload});
  await context.request.post(base+'/api/runs/'+runId+'/pause',{headers});
  await page.reload();await page.getByRole('button',{name:/Override & Resume/}).waitFor();await page.getByRole('button',{name:'Floor plan',exact:true}).click();
  await shot('04-original-active-run');
  for(const tab of ['Learning & task','Chain & telemetry','Alerts','Analysis']){
   await page.getByRole('tab',{name:tab,exact:tab!=='Alerts'}).click();
   await page.waitForTimeout(350);
   report.steps.push({name:'Run tab: '+tab,observed:(await page.locator('body').innerText()).slice(-9000)});
   await shot('05-'+tab.toLowerCase().replace(/[^a-z]+/g,'-'));
  }
  await page.getByRole('button',{name:/Override & Resume/}).click();
  await until(async()=>(await get('/runs/'+runId)).status==='running');
  await page.getByRole('button',{name:/Blocked/}).click();
  await until(async()=>(await events()).some(e=>e.type==='ENVIRONMENT_CHANGE'));
  const after=await events();
  report.steps.push({name:'Blocked-route response',environmentEvents:after.filter(e=>e.type==='ENVIRONMENT_CHANGE').map(e=>e.payload),recentDecisions:after.filter(e=>e.type==='DECISION').slice(-2).map(e=>e.payload.governance)});
  await shot('06-original-blocked-route');
  await page.getByRole('button',{name:/Clear/}).click();
  await page.getByRole('tab',{name:'Chain & telemetry',exact:true}).click();
  const pause=await context.request.post(base+'/api/runs/'+runId+'/pause',{headers});
  report.steps.push({name:'Paused run',responseStatus:pause.status(),state:await get('/runs/'+runId)});
  await page.reload();await page.getByRole('button',{name:/Override & Resume/}).waitFor();
  await page.getByRole('button',{name:'Floor plan',exact:true}).click();
  await shot('07-original-paused-run');
  report.completed=true;
 }catch(e){report.completed=false;report.failure=String(e.stack||e);report.failurePage=await page.locator('body').innerText().catch(()=>null);await shot('failure').catch(()=>{});process.exitCode=1;}
 finally{
  if(runId&&headers)await context.request.post(base+'/api/runs/'+runId+'/stop',{headers}).catch(()=>{});
  fs.writeFileSync(path.join(out,'study-report.json'),JSON.stringify(report,null,2));await browser.close();
 }
 console.log(JSON.stringify({completed:report.completed,steps:report.steps.map(s=>s.name),pageErrors:report.pageErrors,failure:report.failure},null,2));
})();
