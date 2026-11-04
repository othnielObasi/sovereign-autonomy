/* Fleet-learning interaction is an illustration. Evidence below is a separate, read-only record. */
Object.assign(v2Transfer, {version:1,history:[],evaluationVersion:null,approvalVersion:null});
Object.assign(v2TransferCopy[0], {
  title:'Robot A finds an obstacle.<br>A candidate lesson begins.',
  description:'In this illustration, Robot A encounters a blocked north aisle. An external facility notice adds context about recurring congestion. Neither one observation nor outside text is enough to release a fleet-wide lesson.',
  evidence:'Example discovery and candidate v1',
  quote:'Robot A observed a blocked north aisle. A facility notice reports recurring congestion. Candidate: consider the south aisle when the same conditions recur; always check the current route.',
  checks:['Illustrative source observation: Robot A held movement','External notice: untrusted supporting context','Candidate: bounded route advice, not a permanent obstacle rule']
});
Object.assign(v2TransferCopy[1], {description:'The scripted evaluation screens the notice, checks bounded route advice against the mission and compares independent signed observations. Evaluation belongs to this lesson version; a revised version must be evaluated again.'});
Object.assign(v2TransferCopy[2], {description:'Review the evidence, version and operating scope. Here the example operator approves this exact knowledge version for sharing. The decision does not approve a robot action.'});
Object.assign(v2TransferCopy[3], {title:'Release this version.<br>Check each receiving robot.',description:'Robots B and C can receive the same approved version when their site, map, rule version and capability profile match. Change Robot C’s context to see incompatible knowledge withheld.'});
Object.assign(v2TransferCopy[4], {description:'Robots B and C can consider a matching, approved lesson. They still need independent checks of their present conditions. Toggle Robot B’s obstacle to separate knowledge receipt from permission to move.',checks:['Approved lesson version: retained with evaluation and provenance','Recipient contexts: checked independently','Mission destination: unchanged','Current safety decision and controller permit: still mandatory']});
const v3BaseTransferRender=v2RenderTransfer;
function v3ResetVersion(){Object.assign(v2Transfer,{version:1,history:[],evaluationVersion:null,approvalVersion:null});v2ById('recipient-context').value='matching';}
v2RenderTransfer=function(){
  v3BaseTransferRender();
  const state=v2Transfer, version=state.version;
  if(state.evaluated&&state.evaluationVersion===null)state.evaluationVersion=version;
  if(state.approved&&state.approvalVersion===null)state.approvalVersion=version;
  const approved=state.approved&&!state.unsafe&&state.approvalVersion===version&&state.evaluationVersion===version;
  const shared=approved&&state.released;
  let entry=state.history.find(row=>row.version===version);
  if(!entry){entry={version,withdrawn:false};state.history.push(entry);}
  entry.evaluated=state.evaluated;entry.approved=approved;entry.released=shared;entry.rejected=state.evaluated&&state.unsafe;
  const packageNode=v2ById('knowledge-version');packageNode.textContent='L-NORTH-01 / v'+version;
  const small=document.createElement('small');small.textContent='Bounded routing advice · illustrative package';packageNode.append(small);
  const approval=v2ById('knowledge-approval');approval.textContent=shared?'v'+version+' approved & offered':approved?'v'+version+' approved · not released':entry.rejected?'v'+version+' rejected':state.evaluated?'v'+version+' evaluated · review pending':'v'+version+' candidate · not evaluated';
  const binding=document.createElement('small');binding.textContent='Evaluation and approval apply only to this version';approval.append(binding);
  v2ById('knowledge-history').replaceChildren(...state.history.map(row=>{const li=document.createElement('li');li.textContent='v'+row.version+': '+(row.withdrawn?'withdrawn; previous evaluation/approval retained in this example history':row.released?'evaluated, approved and offered to compatible recipients':row.approved?'evaluated and approved; explicit release pending':row.rejected?'evaluation rejected; not approved or released':row.evaluated?'evaluated; operator review pending':'candidate; not evaluated, approved or released');return li;}));
  v2ById('transfer-revise').disabled=!shared;
  const matching=v2ById('recipient-context').value==='matching';
  const mismatch=v2ById('recipient-context').value==='map'?'map version mismatch':'capability profile mismatch';
  const source=v2ById('recipient-source'),recipientB=v2ById('recipient-compatible'),recipientC=v2ById('recipient-different');
  source.textContent=shared?'Source evidence retained with approved v'+version+'.':approved?'v'+version+' approved; explicit release pending.':entry.rejected?'v'+version+' rejected; nothing offered.':state.evaluated?'v'+version+' evaluated; awaiting operator review.':'Obstacle observed; v'+version+' candidate only.';
  recipientB.textContent=shared?'Received approved v'+version+' · site, map and AMR profile match.':'No lesson offered. Waiting for version-specific approval and release.';
  recipientC.textContent=shared?(matching?'Received approved v'+version+' · site, map and AMR profile match.':'v'+version+' withheld · '+mismatch+'.'):'No lesson offered. Recipient context will be checked at release.';
  recipientB.dataset.tone=shared?'pass':'';recipientC.dataset.tone=shared?(matching?'pass':'stop'):'';
  recipientB.closest('article').dataset.received=String(shared);recipientC.closest('article').dataset.received=String(shared&&matching);recipientC.closest('article').dataset.mismatch=String(shared&&!matching);
  v2ById('recipient-b-movement').textContent=shared?(v2ById('transfer-obstacle').checked?'Movement: held by Robot B’s current obstacle.':'Movement: path clear in this example; fresh policy approval and controller permit still required.'):'Movement authority: unchanged.';
  v2ById('recipient-c-movement').textContent=shared&&matching?'Movement: awaiting Robot C’s own current checks and permit.':'Movement authority: unchanged.';
  v2ById('recipient-flow').textContent=shared?'Approved v'+version+' offered to Robot B'+(matching?' and Robot C.':' only; Robot C failed its context check.')+' Knowledge receipt does not authorize movement.':'Robot A discovers → evaluate v'+version+' → approve v'+version+' → explicitly release compatible advice to Robots B and C.';
  if(state.step===0)v2ById('transfer-evidence-title').textContent='Example discovery and candidate v'+version;
  if(state.step===4){v2ById('transfer-status').textContent='Approved v'+version+' was offered to '+(matching?'both matching recipients.':'Robot B; Robot C was excluded for a context mismatch.')+' '+(v2ById('transfer-obstacle').checked?'Robot B’s obstacle still holds movement.':'A clear example route still needs fresh policy approval and controller admission.');}
};
function v3ReviseLesson(){
  const state=v2Transfer;
  state.history.forEach(entry=>{if(entry.version===state.version)entry.withdrawn=true;});
  Object.assign(state,{version:state.version+1,step:0,max:0,evaluated:false,approved:false,released:false,unsafe:v2ById('transfer-unsafe').checked,evaluationVersion:null,approvalVersion:null});
  v2RenderTransfer();
  v2ById('transfer-status').textContent='The earlier example version was withdrawn. v'+state.version+' is a new candidate and cannot be shared until evaluated, approved and explicitly released.';
}
v2ById('transfer-revise').addEventListener('click',v3ReviseLesson);
v2ById('recipient-context').addEventListener('change',v2RenderTransfer);
v2ById('transfer-obstacle').addEventListener('change',()=>v2RenderTransfer());
v2ById('transfer-reset').addEventListener('click',()=>{v3ResetVersion();v2RenderTransfer();});
const v3OriginalReset=v2ResetTransfer;
v2ResetTransfer=function(){v3OriginalReset();v3ResetVersion();v2RenderTransfer();};
v2ById('transfer-unsafe').addEventListener('change',()=>{if(v2Transfer.approved||v2Transfer.released)v3ReviseLesson();v2Transfer.evaluationVersion=null;v2Transfer.approvalVersion=null;},true);
// Returning to discovery and re-evaluating invalidates the previous approval as well.
v2ById('transfer-action').addEventListener('click',()=>{if(v2Transfer.step===1){v2Transfer.approvalVersion=null;v2Transfer.evaluationVersion=v2Transfer.version;}v2RenderTransfer();});
v2RenderTransfer();

/* Inspect exact recorded artefacts. SHA-256 checks apply to individual original event bodies. */
let evData=null,evTab='suite',evMoment=2,evTimer=null;
const evPanel=document.getElementById('ev-panel');
const evTabs=[...document.querySelectorAll('[data-ev-tab]')];
function evEl(tag,attributes={},text){const node=document.createElement(tag);for(const[key,value]of Object.entries(attributes))node.setAttribute(key,value);if(text!==undefined)node.textContent=String(text);return node;}
function evText(tag,text,className){return evEl(tag,className?{class:className}:{},text);}
function evLink(text,href){return evEl('a',{href,target:'_blank',rel:'noopener'},text);}
function evStop(){if(evTimer!==null){clearInterval(evTimer);evTimer=null;}const button=document.getElementById('ev-play');if(button)button.textContent='Play recorded moments';}
function evChoose(tab,scroll=false){evStop();evTab=tab;evTabs.forEach(button=>{const selected=button.dataset.evTab===tab;button.setAttribute('aria-selected',String(selected));button.tabIndex=selected?0:-1;});evPanel.setAttribute('aria-labelledby','ev-tab-'+tab);evRender();if(scroll)document.getElementById('evidence-inspector').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});}
function evFact(value,label){const card=evEl('div',{class:'ev-fact'});card.append(evText('strong',value),evText('span',label));return card;}
function evNote(text,tone=''){return evText('div',text,'ev-note'+(tone?' '+tone:''));}
function evRender(){
  evPanel.replaceChildren();
  if(!evData){evPanel.append(evText('p','Loading recorded artefacts…'));return;}
  if(evTab==='suite'){
    const report=evData.validation;
    evPanel.append(evText('h4',report.backend.passed+' backend tests · recorded validation'),evText('p',report.date+' · '+report.scope,'ev-meta'));
    const facts=evEl('div',{class:'ev-facts'});facts.append(evFact(report.backend.passed,'tests recorded as passed'),evFact(report.backend.duration_s+' s','recorded test duration'),evFact(report.backend.oversight_cases_included,'oversight cases included'));evPanel.append(facts);
    evPanel.append(evText('p','Command recorded with this result:'),evText('pre',report.backend.command,'ev-command'),evNote('This artefact is an aggregate recorded test summary. It does not contain individual backend test-case logs, and opening it does not run the suite.'));
    evPanel.append(evText('h5','Scope of this validation batch'));
    const list=evEl('ul');report.limitations.filter(text=>text!=='No commit or push performed').forEach(text=>list.append(evText('li',text)));list.className='ev-command';evPanel.append(list,evLink('Open the original recorded summary ↗','/landing/validation.json'),evText('p','The separate live Meta mission and receipt checks are available under Chain & signatures.','ev-meta'));
  }else if(evTab==='browser'){
    const count=evData.browser_reports.reduce((n,report)=>n+report.checks.length,0);
    evPanel.append(evText('h4',count+' recorded browser checks, not '+count+' scenarios'),evText('p','10 Mission Control checks + 5 operator-oversight checks. Each statement below comes from its saved report. These are recorded outcomes, not checks running in this browser.'));
    evData.browser_reports.forEach(report=>{const details=evEl('details',{class:'ev-report',open:''});details.append(evText('summary',report.label+' · '+report.checks.length+' recorded checks · '+(report.passed?'passed':'inspect result')));const list=evEl('ul');report.checks.forEach(text=>list.append(evText('li',text)));details.append(list,evLink('Inspect original repository report ↗','https://github.com/othnielObasi/sovereign-autonomy/blob/main/'+report.source));evPanel.append(details);});
  }else if(evTab==='signatures'){
    const fresh=evData.live_validation,valid=fresh.receipt_verification.filter(row=>row.valid).length;
    evPanel.append(evText('h4','Two records. Their verification limits stay visible.'),evText('p','Fresh Meta mission: '+fresh.run_id,'ev-meta'));
    const facts=evEl('div',{class:'ev-facts'});facts.append(evFact(fresh.verification.total_entries,'events in the verified Meta mission chain'),evFact(valid+'/'+fresh.receipt_verification.length,'recorded Ed25519 signature checks valid'),evFact(fresh.verification.chain_valid?'Valid':'Inspect','recorded chain verification result'));evPanel.append(facts);
    evPanel.append(evNote('These signature checks were recorded by the backend. This viewer does not rerun Ed25519 verification. The replay tab can independently recompute the SHA-256 hash of each selected archived event.','success'));
    const signatures=evEl('div',{class:'ev-signatures'});const list=evEl('ol');fresh.receipt_verification.forEach(row=>list.append(evText('li','Receipt '+row.receipt_id+' · '+row.algorithm+' · '+(row.valid?'valid':'invalid')+' · '+row.reason)));signatures.append(list);evPanel.append(signatures,evLink('Inspect full Meta mission and signed receipts ↗','https://github.com/othnielObasi/sovereign-autonomy/blob/main/docs/validation/2026-11-03-live-integrations/mission.json'));
    evPanel.append(evNote('Separate fallback replay: '+evData.mission.event_count+' archived events; '+evData.mission.ordering_gaps+' chronological linkage gaps. Individual content hashes were verified, but this archive is not a fully continuous chain.','warning'));
  }else evRenderReplay();
}
function evEventCard(event){
  const card=evEl('article',{class:'ev-event'}),fields=event.fields,header=evEl('div',{class:'ev-event-header'});
  header.append(evText('strong',event.type));
  const verdict=fields.governance?.decision||fields.event||(fields.result?fields.result.ok?'ACKNOWLEDGED':'INSPECT RESULT':null);
  if(verdict)header.append(evText('span',verdict,'ev-verdict'+(verdict==='DENIED'||verdict.includes('refused')?' stop':'')));
  card.append(header,evText('p',event.id+' · '+event.ts,'ev-event-id'));
  const facts=evEl('dl');function fact(label,value){if(value===undefined||value===null)return;const row=evEl('div');row.append(evText('dt',label),evText('dd',typeof value==='string'?value:JSON.stringify(value)));facts.append(row);}
  if(fields.proposal){fact('Proposed action',fields.proposal.intent);fact('Exact parameters',fields.proposal.params);fact('Planner rationale',fields.proposal.rationale);}
  if(fields.governance){fact('Policy decision',fields.governance.decision);fact('Policies triggered',fields.governance.policy_hits.length?fields.governance.policy_hits.join(', '):'None recorded');fact('Reason',fields.governance.reasons.length?fields.governance.reasons.join(' '):'No blocking reason recorded. Approval alone is not evidence of motion.');}
  if(fields.command){fact('Controller command',fields.command.intent);fact('Exact command parameters',fields.command.params);fact('Recorded controller response',fields.result);}
  if(fields.event){fact('Authority event',fields.event);fact('Exact action reference',fields.action_id);fact('Reason',fields.reason);}
  if(fields.plan){fact('Plan waypoints',fields.plan.waypoints?.length);fact('Recorded model',fields.plan.model_used);}
  fact('Original source-event hash',event.source_event_hash);card.append(facts);
  const verify=evText('button','Verify this source event','ev-verify');verify.type='button';
  const result=evText('p','Uses the complete original canonical body, not just the fields displayed above.','ev-hash-result');result.setAttribute('role','status');
  verify.addEventListener('click',async()=>{verify.disabled=true;result.textContent='Computing SHA-256 locally…';try{const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(event.canonical_source_body));const hash='sha256:'+[...new Uint8Array(digest)].map(byte=>byte.toString(16).padStart(2,'0')).join('');const valid=hash===event.source_event_hash;result.dataset.valid=String(valid);result.textContent=valid?'SHA-256 matches the original event hash. This verifies this event’s contents, not full chain continuity.':'Hash mismatch: these event contents do not match the saved original hash.';}catch{result.dataset.valid='false';result.textContent='Local hash verification unavailable. Inspect the source artefact directly.';}finally{verify.disabled=false;}});
  card.append(verify,result);return card;
}
function evCloneMap(){
  const source=document.getElementById('story-map'),map=source.cloneNode(true),ids=new Map();
  [map,...map.querySelectorAll('[id]')].forEach(node=>{if(node.id){ids.set(node.id,'ev-copy-'+node.id);node.id='ev-copy-'+node.id;}});
  [map,...map.querySelectorAll('*')].forEach(node=>{for(const attr of [...node.attributes]){let value=attr.value;for(const[from,to]of ids){value=value.replaceAll('url(#'+from+')','url(#'+to+')');if(value==='#'+from)value='#'+to;if(['aria-labelledby','aria-describedby'].includes(attr.name))value=value.split(' ').map(id=>ids.get(id)||id).join(' ');}if(value!==attr.value)node.setAttribute(attr.name,value);}});
  map.id='ev-replay-map';map.setAttribute('role','img');map.setAttribute('aria-label','Archived facility floor plan and recorded robot position for the selected moment');return map;
}
function evShowMoment(index,manual=true){if(manual)evStop();evMoment=Math.max(0,Math.min(4,index));evRenderReplay();if(manual)evPanel.querySelectorAll('.ev-moment')[evMoment]?.focus({preventScroll:true});}
function evRenderReplay(){
  evPanel.replaceChildren();const mission=evData.mission,step=mission.summary.steps[evMoment];
  evPanel.append(evText('h4','Replay recorded decisions. Inspect what was allowed or blocked.'),evText('p',mission.run_id+' · fallback planner · 3 November 2026 · selected historical moments','ev-meta'));
  evPanel.append(evNote('This archive has '+mission.ordering_gaps+' chronological linkage gaps. Individual event hashes can be checked below, but the full archived chain is not continuous. Playback is historical; it sends no robot commands.','warning'));
  const toolbar=evEl('div',{class:'ev-replay-toolbar'});toolbar.append(evText('p','Moment '+(evMoment+1)+' / 5 · '+step.title));const play=evText('button',evTimer===null?'Play recorded moments':'Pause playback','ev-play');play.id='ev-play';play.type='button';play.addEventListener('click',()=>{if(evTimer!==null){evStop();return;}evMoment=0;evTimer=setInterval(()=>{if(evMoment>=4){evStop();return;}evMoment++;evRenderReplay();},2300);evRenderReplay();});toolbar.append(play);evPanel.append(toolbar);
  const controls=evEl('div',{class:'ev-replay-controls','aria-label':'Recorded mission moments'});mission.summary.steps.forEach((moment,i)=>{const button=evText('button',moment.label,'ev-moment');button.type='button';button.setAttribute('aria-pressed',String(i===evMoment));button.addEventListener('click',()=>evShowMoment(i));controls.append(button);});evPanel.append(controls);
  // Reuse the original archive renderer; the copied map has unique IDs and no control bindings.
  document.querySelectorAll('#mission-story [data-story-step]')[evMoment].click();
  const layout=evEl('div',{class:'ev-replay-layout'}),mapWrap=evEl('div',{class:'ev-map-wrap'}),mapScroll=evEl('div',{class:'ev-map-scroll',tabindex:'0','aria-label':'Scrollable recorded floor plan'});mapScroll.append(evCloneMap());mapWrap.append(mapScroll,evText('p',step.fact+' · '+step.title+'. This floor plan uses the selected archived observation, not live telemetry.','ev-map-caption'));
  const events=evEl('div');step.event_ids.forEach(id=>{const event=mission.events.find(row=>row.id===id);if(event)events.append(evEventCard(event));});layout.append(mapWrap,events);evPanel.append(layout);
}
evTabs.forEach((tab,i)=>{tab.addEventListener('click',()=>evChoose(tab.dataset.evTab));tab.addEventListener('keydown',event=>{let next;if(event.key==='ArrowRight')next=(i+1)%evTabs.length;else if(event.key==='ArrowLeft')next=(i+evTabs.length-1)%evTabs.length;else if(event.key==='Home')next=0;else if(event.key==='End')next=evTabs.length-1;else return;event.preventDefault();evChoose(evTabs[next].dataset.evTab);evTabs[next].focus();});});
document.querySelectorAll('[data-ev-open]').forEach(button=>button.addEventListener('click',()=>evChoose(button.dataset.evOpen,true)));
document.addEventListener('visibilitychange',()=>{if(document.hidden)evStop();});
window.addEventListener('pagehide',evStop);
fetch('/home/evidence/recorded-results.json',{cache:'no-store'}).then(response=>{if(!response.ok)throw Error('Recorded artefact unavailable');return response.json();}).then(data=>{evData=data;evRender();}).catch(()=>{evPanel.replaceChildren(evText('p','Recorded artefacts could not load. Use the source links below to inspect the original files.'));});
