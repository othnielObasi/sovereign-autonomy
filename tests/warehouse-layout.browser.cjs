// Read-only responsive check after facility-parity.browser.cjs on the isolated stack.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const out='docs/validation/2026-11-03-warehouse-ux';
(async()=>{
  const id=JSON.parse(fs.readFileSync(out+'/parity/browser-report.json','utf8')).runId;
  const browser=await chromium.launch({headless:true});
  const page=await browser.newPage({viewport:{width:390,height:844},reducedMotion:'reduce'});
  const report={checks:[],errors:[]};page.on('pageerror',e=>report.errors.push(e.message));
  await page.addInitScript(()=>{window.requestAnimationFrame=cb=>setTimeout(()=>cb(performance.now()),200);window.cancelAnimationFrame=id=>clearTimeout(id);});
  try{
    await page.goto('http://127.0.0.1:19300/runs/'+id+'?q=low');
    await page.getByRole('button',{name:'Display settings',exact:true}).waitFor({timeout:45000});
    for(const viewport of [{width:390,height:844},{width:1440,height:1050}]){
      await page.setViewportSize(viewport);await page.waitForTimeout(1000);
      const result=await page.evaluate(()=>{
        const t=document.querySelector('.warehouse-toolbar').getBoundingClientRect(),c=document.querySelector('.warehouse-scene').getBoundingClientRect();
        return {width:innerWidth,scrollWidth:document.documentElement.scrollWidth,toolbarBottom:t.bottom,sceneTop:c.top};
      });
      assert.ok(result.scrollWidth<=result.width+1,JSON.stringify(result));
      assert.ok(result.toolbarBottom<=result.sceneTop+1);
      await page.getByRole('button',{name:'View guide',exact:true}).click();
      await page.getByRole('button',{name:'Close warehouse options',exact:true}).click();
      await page.screenshot({path:out+`/run-layout-${viewport.width}.png`,fullPage:true});
      report.checks.push({viewport,...result});
    }
    assert.deepEqual(report.errors,[]);report.passed=true;
  }catch(e){report.passed=false;report.failure=String(e.stack||e);process.exitCode=1;}
  finally{fs.writeFileSync(out+'/mobile-run-report.json',JSON.stringify(report,null,2)+'\n');await browser.close();}
  console.log(JSON.stringify(report,null,2));
})().catch(e=>{console.error(e);process.exitCode=1;});
