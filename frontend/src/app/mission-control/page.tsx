"use client";

import dynamic from 'next/dynamic';
import Link from 'next/link';
import React, { Component, useCallback, useEffect, useRef, useState } from 'react';
import { createMission, startRun, stopRun, pauseRun, resumeRun, triggerScenario, resetKillSwitch, runDrills, voiceStop } from '@/lib/api';
import { startRecording, type Recorder } from '@/lib/wav';
import { Icon } from '@/components/control/Icon';
import { OperatorActions } from '@/components/control/OperatorActions';
import { FacilityMap } from '@/components/control/FacilityMap';
import { RunProgressView, useRunPresentation } from '@/components/RunProgress';

const FacilityScene = dynamic(() => import('@/components/control/FacilityScene'), { ssr: false, loading: () => <div className="sa-facility-empty"><span className="sa-loading-orbit"/><strong>Preparing the facility view</strong></div> });
const MissionInspection=dynamic(()=>import('@/components/control/MissionInspection'),{ssr:false});
const API = process.env.NEXT_PUBLIC_API_BASE || '/api';
const activeStatuses = ['planning', 'running', 'paused'];

async function read(path: string) {
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 4500);
  try { const response = await fetch(`${API}${path}`, { cache: 'no-store', signal: controller.signal }); if (!response.ok) throw new Error('Service unavailable'); return await response.json(); }
  finally { clearTimeout(timer); }
}

class ViewBoundary extends Component<{ children: React.ReactNode; onFailure: () => void }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch() { this.props.onFailure(); }
  render() { return this.state.failed ? null : this.props.children; }
}

function eventCopy(event: any) {
  const p = event.payload || {};
  if (event.type === 'DECISION') { const v = p.governance || {}; return { title: v.decision === 'APPROVED' ? 'Move approved' : v.decision === 'NEEDS_REVIEW' ? 'Operator review requested' : 'Move refused', detail: (v.reasons || []).slice(0,1).join(' ') || 'The current move was checked against the active policies.', tone: v.decision === 'APPROVED' ? 'green' : v.decision === 'DENIED' ? 'red' : 'amber', icon: 'shield' }; }
  if (event.type === 'ENVIRONMENT_CHANGE') return { title: p.action === 'replanned' ? 'Replacement route ready' : 'Holding for a clear route', detail: p.action === 'replanned' ? `${p.waypoints} waypoints · old route discarded` : 'The robot is stopped while the route is revalidated.', tone: 'amber', icon: 'route' };
  if (event.type === 'AUTHORITY') return { title: p.event === 'permit_used' ? 'Robot cleared to move' : String(p.event || 'Authority checked').replaceAll('_',' '), detail: p.reason || 'A single-use permit was checked.', tone: p.event === 'permit_used' ? 'green' : 'amber', icon: 'check' };
  if (event.type === 'EXPERIENCE_RETRIEVAL') { const records = p.experience_decisions || []; return { title: 'Checked what other robots learned', detail: `${records.filter((r: any) => r.status === 'accepted').length} lessons used · ${records.filter((r: any) => r.status === 'excluded').length} set aside`, tone: 'sage', icon: 'layers' }; }
  return { title: 'Mission route prepared', detail: `${p.plan?.waypoints?.length || 0} waypoints · ${p.plan?.model_used || p.source || 'planner'}`, tone: 'sage', icon: 'route' };
}

export default function MissionControl() {
  const [world, setWorld] = useState<any>(null), [telemetry, setTelemetry] = useState<any>(null), [fleet, setFleet] = useState<any[]>([]);
  const [authority, setAuthority] = useState<any>(null), [learning, setLearning] = useState<any>(null), [health, setHealth] = useState<any>(null);
  const [runs, setRuns] = useState<any[]>([]), [missions, setMissions] = useState<any[]>([]), [runId, setRunId] = useState(''), [events, setEvents] = useState<any[]>([]);
  const [authorityCurrent, setAuthorityCurrent] = useState(false), [fleetCurrent, setFleetCurrent] = useState(false);
  const [receivedAt, setReceivedAt] = useState(0), [now, setNow] = useState(Date.now()), [connectionFailed, setConnectionFailed] = useState(false);
  const [selectedRobot, setSelectedRobot] = useState('robot-1'), [view, setView] = useState<'3d' | '2d'>('3d'), [rendererFailed, setRendererFailed] = useState(false);
  const [bayId, setBayId] = useState(''), [instruction, setInstruction] = useState(''), [draft, setDraft] = useState<any>(null), [busy, setBusy] = useState('');
  const [message, setMessage] = useState<{ text: string; error?: boolean } | null>(null), [detailTab, setDetailTab] = useState('activity');
  const [composing, setComposing] = useState(true);
  const [inspecting,setInspecting]=useState(false),[pickingGoal,setPickingGoal]=useState(false),[floorGoal,setFloorGoal]=useState<any>(null);
  const [recording, setRecording] = useState(false), [drill, setDrill] = useState<any>(null);
  useEffect(() => { const q = new URLSearchParams(window.location.search); if (q.get("view") === "2d") setView("2d"); if (q.get("panel") === "scenarios") setDetailTab("scenarios"); }, []);
  const initialSelection = useRef(false);
  const progress = useRunPresentation(runId);
  const pending = useRef(false), worldVersion = useRef(''), recorder = useRef<Recorder | null>(null);
  const composer = useRef<HTMLDivElement>(null);

  const refresh = useCallback(async () => {
    const result = await Promise.allSettled([read('/runs'), read('/missions'), read('/authority/learning'), read('/health')]);
    if (result[0].status === 'fulfilled') setRuns(Array.isArray(result[0].value) ? result[0].value : result[0].value.runs || []);
    if (result[1].status === 'fulfilled') setMissions(result[1].value || []);
    if (result[2].status === 'fulfilled') setLearning(result[2].value);
    if (result[3].status === 'fulfilled') setHealth(result[3].value);
  }, []);
  useEffect(() => {
    let live = true; let timer: ReturnType<typeof setTimeout>, slowTimer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        if (document.hidden) return;
        const results = await Promise.allSettled([read(`/sim/telemetry?robot_id=${encodeURIComponent(selectedRobot)}`), read('/sim/fleet'), read('/authority/status')]);
        if (!live) return;
        if (results[0].status === 'fulfilled') {
          const t = results[0].value; setTelemetry(t); setReceivedAt(Date.now()); setConnectionFailed(false);
          if (worldVersion.current !== t.map_version || !worldVersion.current) { const w = await read('/sim/world'); if (live) { setWorld(w); worldVersion.current = w.map_version || t.map_version || 'loaded'; } }
        } else setConnectionFailed(true);
        setFleetCurrent(results[1].status === 'fulfilled');
        setAuthorityCurrent(results[2].status === 'fulfilled');
        if (results[1].status === 'fulfilled') setFleet(results[1].value.robots || []);
        if (results[2].status === 'fulfilled') setAuthority(results[2].value);
      } catch { if (live) setConnectionFailed(true); }
      finally { if (live) timer = setTimeout(tick, 850); }
    };
    const slow = async () => { if (!document.hidden && live) await refresh(); if (live) slowTimer = setTimeout(slow, 6000); };
    void tick(); void slow(); const clock = setInterval(() => setNow(Date.now()),1000);
    if (new URLSearchParams(window.location.search).get('showcase') === '1') setDetailTab('scenarios');
    return () => { live = false; clearTimeout(timer); clearTimeout(slowTimer); clearInterval(clock); if (recorder.current) void recorder.current.stop().catch(() => {}); };
  }, [refresh, selectedRobot]);
  useEffect(() => { if (initialSelection.current || !runs.length) return; initialSelection.current = true; const active = runs.find(r => activeStatuses.includes(r.status)); if (active && !runId) { setRunId(active.id); setSelectedRobot(missions.find(m => m.id === active.mission_id)?.goal?.robot_id || 'robot-1'); setComposing(false); } }, [runs, runId, composing, missions]);
  useEffect(() => {
    setEvents([]);
    if (!runId) return;
    let live = true; let timer: ReturnType<typeof setTimeout>;
    const poll = async () => { try { const rows = await read(`/runs/${runId}/events?limit=80&latest=true`); if (live) setEvents(rows); } catch { /* Last recorded evidence remains inspectable. */ } finally { if (live) timer = setTimeout(poll,1600); } };
    void poll(); return () => { live = false; clearTimeout(timer); };
  }, [runId]);

  const live = receivedAt > 0 && now - receivedAt < 4000 && !connectionFailed && fleetCurrent;
  const run = runs.find(r => r.id === runId), active = run && activeStatuses.includes(run.status);
  const mission = missions.find(m => m.id === run?.mission_id);
  const bays = world?.bays || [], destination = floorGoal || bays.find((b: any) => b.id === (bayId || bays[0]?.id));
  const robot = fleet.find(r => r.robot_id === selectedRobot) || fleet[0];
  const selectedTarget = Array.isArray(robot?.target) ? { x: robot.target[0], y: robot.target[1] } : robot?.target;
  const path = selectedTarget && robot ? [{x: robot.x,y: robot.y}, selectedTarget] : [];
  const robotBusy = runs.some(r => activeStatuses.includes(r.status) && (missions.find(m => m.id === r.mission_id)?.goal?.robot_id || 'robot-1') === selectedRobot);
  const goal = active && !composing && (mission?.goal?.robot_id || 'robot-1') === selectedRobot && mission?.goal ? mission.goal : destination;
  const locks = authority?.kill_locks || [];
  const activity = events.filter(e => ['DECISION','AUTHORITY','ENVIRONMENT_CHANGE','PLAN','EXPERIENCE_RETRIEVAL'].includes(e.type)).slice(-8).reverse();
  const age = receivedAt ? Math.max(0, Math.floor((now-receivedAt)/1000)) : null;
  const model = health?.planner_provider === 'muse' && health?.muse_enabled ? 'Muse Spark' : health?.planner_provider === 'gemini' && health?.gemini_enabled ? 'Gemini' : health ? 'Deterministic planner' : 'Checking planner';
  const allowed = live && authorityCurrent && authority?.enabled && !locks.length;

  async function act(name: string, fn: () => Promise<any>, success?: string) {
    if (pending.current) return;
    pending.current = true; setBusy(name); setMessage(null);
    try { const result = await fn(); if (success) setMessage({text: success}); await refresh(); return result; }
    catch (e: any) { setMessage({text: String(e.message || 'The action could not be completed.'), error: true}); }
    finally { pending.current = false; setBusy(''); }
  }
  function selectRobot(id: string) {
    setSelectedRobot(id); setDraft(null);
    const matching = runs.find(r => activeStatuses.includes(r.status) && (missions.find(m => m.id === r.mission_id)?.goal?.robot_id || 'robot-1') === id);
    if (matching) { setRunId(matching.id); setComposing(false); }
    else { setRunId(''); setComposing(true); }
  }
  async function launch() {
    if (!destination || !robot || !allowed || robotBusy) return;
    setPickingGoal(false);
    await act('launch', async () => {
      const m = draft || await createMission({ title: instruction.trim() || `Navigate to ${destination.label || destination.id}`, ...(floorGoal?{robot_id:selectedRobot,goal:{x:floorGoal.x,y:floorGoal.y}}:{bay_id:destination.id,robot_id:selectedRobot}) });
      setDraft(m); const result = await startRun(m.id); setRunId(result.run_id); setComposing(false); setDraft(null); return result;
    }, 'Mission launched. Follow its decisions and controller admissions below.');
  }
  async function scenario(key: string) { await act(key, () => triggerScenario(key), key === 'clear' ? 'Injected obstacles cleared. Watch the route revalidation.' : 'Scenario introduced. Current movement and memory must be revalidated.'); }
  async function voice() {
    if (!recording) {
      try { recorder.current = await startRecording(); setRecording(true); setMessage({text: 'Listening. Say “stop the fleet”, then select the microphone again.'}); }
      catch { setMessage({text: 'Microphone access is unavailable. Use Stop fleet instead.', error: true}); }
      return;
    }
    setRecording(false);
    await act('voice', async () => { const wav = await recorder.current!.stop(); recorder.current = null; const result = await voiceStop(wav); setMessage({text: result.action === 'kill' && result.stop_verified ? 'Spoken stop confirmed by the controller.' : 'No confirmed stop. Use Stop fleet if you need to stop now.', error: !(result.action === 'kill' && result.stop_verified)}); return result; });
  }

  return <div className="sa-control">
    <header className="sa-control-heading"><div><h1>Mission control<span className="sa-heading-dot"/></h1><p>Pick a destination and a robot. The AI plans the route; every move is checked before it happens.</p></div>{active && !composing && <div className="sa-heading-actions"><button className="sa-button sa-button-primary" onClick={() => { setComposing(true); setTimeout(() => { composer.current?.scrollIntoView({behavior: 'smooth',block: 'center'}); composer.current?.querySelector<HTMLSelectElement>('select')?.focus(); },0); }}><Icon name="plus" size={16}/>New mission</button></div>}</header>
    {message && <div role={message.error ? 'alert' : 'status'} className={`sa-action-notice ${message.error ? 'is-error' : ''}`}><Icon name={message.error ? 'alert' : 'check'} size={17}/><span>{message.text}</span><button className="sa-icon-button" aria-label="Dismiss notification" onClick={() => setMessage(null)}><Icon name="cross" size={14}/></button></div>}
    {locks.length > 0 && <div className="sa-lock-banner"><Icon name="stop"/><div><strong>The fleet is stopped</strong><p>A stop was pressed ({locks[0].reason || 'operator stop'}). Only a signed-in operator can release it; paused missions stay paused until resumed.</p></div><button className="sa-button" disabled={!!busy} onClick={() => act('reset', () => resetKillSwitch(locks[0].scope,locks[0].id || locks[0].ident),'Stop released. Paused missions still require an explicit resume.')}>Release stop</button></div>}
    <section className="sa-status-strip" aria-label="Workspace status"><span><i className={live ? 'sa-dot' : 'sa-dot is-offline'}/>{live ? `${fleet.length} robots connected` : 'Connecting to the simulator'}</span><span><Icon name="shield" size={14}/>{!authorityCurrent ? 'Checking safety status' : !authority.enabled ? 'Permits not configured' : locks.length ? 'Fleet stopped' : 'Every move needs a permit'}</span><span><Icon name="bolt" size={14}/>Planner: {model}</span><span><Icon name="route" size={14}/>{active ? run.status === 'paused' ? 'Mission paused' : 'Mission in progress' : 'Ready for a mission'}</span></section>
    
    <div className="sa-operation-grid"><div className="sa-operation-main"><section id="facility" className="sa-facility-card" aria-label="Facility workspace"><div className="sa-card-heading"><div><span className="sa-eyebrow">FACILITY TWIN</span><h2>{world?.site?.title || 'Simulation workspace'}<Icon name="down" size={14}/></h2></div><div className="sa-live-state"><span className={`sa-dot ${live ? '' : 'is-offline'}`}/>{live ? 'Live simulation' : receivedAt ? 'Connection interrupted' : 'Connecting'}<small>{live ? 'Telemetry connected' : age === null ? 'Waiting for simulator' : `Last update ${age}s ago`}</small></div></div>
      <div className="sa-viewport"><div className="sa-map-tools"><div className="sa-segmented" role="group" aria-label="Facility view"><button aria-pressed={view === '3d'} disabled={rendererFailed} onClick={() => setView('3d')}>3D facility</button><button aria-pressed={view === '2d'} onClick={() => setView('2d')}>Floor plan</button></div><span className="sa-map-coordinate">{world ? `${world.geofence.max_x-world.geofence.min_x} × ${world.geofence.max_y-world.geofence.min_y} m` : 'METRIC FLOOR FRAME'}</span></div>
        {world && view === '3d' && !rendererFailed ? <ViewBoundary onFailure={() => { setRendererFailed(true); setView('2d'); }}><FacilityScene live={live} world={world} telemetry={telemetry} fleet={fleet} goal={goal} path={path} selected={selectedRobot} onSelect={selectRobot}/></ViewBoundary> : <FacilityMap world={world} telemetry={telemetry} fleet={fleet} goal={goal} path={path} selected={selectedRobot} onSelect={selectRobot}/>}
        {!live && world && <span className="sa-stale-overlay">{receivedAt ? 'Last received positions · not live' : 'Waiting for telemetry'}</span>}
        {rendererFailed && <span className="sa-render-note">3D unavailable · floor plan and controls remain usable</span>}
        {robot && <div className="sa-robot-callout"><span className="sa-callout-symbol"><Icon name={robot.robot_kind==='humanoid'?'user':'robot'} size={19}/></span><div><strong>{robot.robot_id}<span>{robot.estopped ? 'Stopped' : robot.speed > .01 ? 'Moving' : 'Standby'}</span></strong><small>{robot.robot_profile?.label || 'Mobile carrier'} · {Number(robot.speed || 0).toFixed(2)} m/s</small></div></div>}
      </div><div className="sa-map-caption"><div><span className="sa-legend-dot is-carrier"/>Carrier<span className="sa-legend-dot is-person"/>Person<span className="sa-legend-route"/>Controller target</div><span>{view === '3d' ? 'Drag to orbit · Scroll to zoom' : 'Select a robot to inspect'}</span></div></section>
      <section id="fleet" className="sa-fleet-section"><div className="sa-section-heading"><h2>Your fleet <span>{fleet.length || '—'}</span></h2><span>Movement permissions are checked per robot</span></div><div className="sa-fleet-cards">{fleet.length ? fleet.map((r,i) => <button key={r.robot_id} className={`sa-fleet-card ${selectedRobot === r.robot_id ? 'is-selected' : ''}`} onClick={() => selectRobot(r.robot_id)} aria-pressed={selectedRobot === r.robot_id}><span className={`sa-fleet-avatar ${r.robot_kind==='humanoid'?'is-humanoid':i === 1 ? 'is-blue' : ''}`}><Icon name={r.robot_kind==='humanoid'?'user':'robot'} size={28}/></span><div><strong>{r.robot_id}<span className={`sa-small-status ${r.estopped ? 'is-red' : ''}`}>{r.estopped ? 'Stopped' : r.speed > .01 ? 'Moving' : 'Standby'}</span></strong><p>{r.robot_profile?.label || 'Mobile carrier'}</p><small>{Number(r.speed || 0).toFixed(2)} m/s</small></div><Icon name="chevron" size={15}/></button>) : <div className="sa-empty-fleet">Fleet information appears when telemetry connects.</div>}</div></section>
      
    </div>
    <aside className="sa-mission-rail"><section id="mission-desk" className="sa-mission-desk" ref={composer}><div className="sa-card-heading"><div><span className="sa-eyebrow">MISSION DESK</span><h2>{active && !composing ? 'Mission in progress' : 'Start a mission'}</h2></div><span className="sa-desk-symbol"><Icon name="route"/></span></div>
      {active && !composing ? <div className="sa-active-mission"><span className="sa-state-badge">{run.status}</span><h3>{mission?.title || 'Governed mission'}</h3><p>Each move is approved before the robot takes it. Follow along in the mission log below.</p><RunProgressView value={progress.value} current={progress.current && progress.value?.run_id === runId} telemetry={telemetry} fresh={live} status={run.status}/><div className="sa-mission-actions"><button className="sa-button" disabled={!!busy || !live} onClick={() => act('pause', () => run.status === 'paused' ? resumeRun(runId) : pauseRun(runId),run.status === 'paused' ? 'Mission resumed under fresh authority.' : 'Mission paused. The robot has been instructed to stop.')}><Icon name={run.status === 'paused' ? 'play' : 'pause'} size={14}/>{run.status === 'paused' ? 'Resume' : 'Pause'}</button><button className="sa-button" disabled={!!busy} onClick={() => act('end', () => stopRun(runId),'Mission ended. Its evidence remains available in mission history.')}><Icon name="stop" size={14}/>End mission</button></div><OperatorActions key={runId} runId={runId} status={run.status} onChange={refresh}/><Link className="sa-text-link" href={`/runs/${runId}`}>Open full mission record <Icon name="arrow" size={14}/></Link></div> : <form className="sa-form sa-mission-form" onSubmit={e => { e.preventDefault(); void launch(); }}>{active && composing && <button type="button" className="sa-text-link" onClick={() => { setComposing(false); setSelectedRobot(mission?.goal?.robot_id || 'robot-1'); }}>Back to active mission <Icon name="arrow" size={14}/></button>}<label>Destination<select aria-label="Destination" value={floorGoal?'floor':destination?.id || ''} onChange={e => { setBayId(e.target.value); setFloorGoal(null); setPickingGoal(false); setDraft(null); }} disabled={!!busy || !bays.length}><option value="" disabled>Choose a destination</option>{floorGoal&&<option value="floor">Floor point X {floorGoal.x} / Y {floorGoal.y}</option>}{bays.map((b: any) => <option key={b.id} value={b.id}>{b.label || b.id} · {b.id}</option>)}</select></label><button type="button" className="sa-button" onClick={()=>{setInspecting(true);setView('2d');setPickingGoal(true);}}>Or pick a point on the floor</button>{pickingGoal&&<div className="sa-floor-coordinates"><p role="status">Select open floor in the detailed facility below, or enter coordinates. The backend validates the route before movement.</p><label>Floor X<input aria-label="Floor X" type="number" step=".1" min={world?.geofence?.min_x} max={world?.geofence?.max_x} value={floorGoal?.x??robot?.x??0} onChange={e=>{setFloorGoal({x:Number(e.target.value),y:floorGoal?.y??robot?.y??0,label:'Floor point'});setDraft(null);}}/></label><label>Floor Y<input aria-label="Floor Y" type="number" step=".1" min={world?.geofence?.min_y} max={world?.geofence?.max_y} value={floorGoal?.y??robot?.y??0} onChange={e=>{setFloorGoal({x:floorGoal?.x??robot?.x??0,y:Number(e.target.value),label:'Floor point'});setDraft(null);}}/></label></div>}<label>Assigned robot<select aria-label="Assigned robot" value={selectedRobot} onChange={e => { selectRobot(e.target.value); }} disabled={!!busy || !fleet.length}>{fleet.length ? fleet.map(r => <option key={r.robot_id} value={r.robot_id}>{r.robot_id} · {r.robot_profile?.label || 'Mobile carrier'}</option>) : <option>Waiting for fleet</option>}</select></label><label>Mission instruction <span>Optional</span><textarea rows={2} maxLength={200} placeholder={destination ? `Navigate to ${(destination.label || destination.id).toLowerCase()}` : 'Describe the navigation objective'} value={instruction} onChange={e => { setInstruction(e.target.value); setDraft(null); }} disabled={!!busy}/></label><div className="sa-authority-note"><Icon name="shield" size={16}/><span>Every move is checked before the controller may act.</span></div><button className="sa-button sa-button-primary" disabled={!!busy || !allowed || !destination || !fleet.length || robotBusy}>{busy === 'launch' ? 'Preparing mission…' : draft ? 'Retry launch' : 'Launch mission'}<Icon name="arrow" size={16}/></button>{robotBusy && <p className="sa-form-hint">This robot already has an active mission. Choose another robot or open its mission record.</p>}{!allowed && <p className="sa-form-hint">{locks.length ? 'Release the stop before launching a mission.' : !live ? 'Waiting for live telemetry before launch.' : !authorityCurrent ? 'Waiting for current authority status.' : 'Execution authority is not configured.'}</p>}</form>}
    </section>
    
    </aside></div>
    <section id="mission-evidence" className="sa-activity-card"><div className="sa-activity-heading"><div><h2>Mission log</h2><p>{active ? 'What the system decided during this mission.' : runId ? 'What happened in the selected mission.' : 'Decisions appear here once a mission starts.'}</p></div><div className="sa-detail-tabs" role="tablist" aria-label="Mission evidence"><button role="tab" aria-selected={detailTab==='activity'} onClick={()=>setDetailTab('activity')}>What happened</button><button role="tab" aria-selected={detailTab==='memory'} onClick={()=>setDetailTab('memory')}>What robots learned</button><button role="tab" aria-selected={detailTab==='scenarios'} onClick={()=>setDetailTab('scenarios')}>Try a scenario</button></div></div>
      <div role="tabpanel" className="sa-evidence-content">{detailTab === 'activity' ? activity.length ? <ol className="sa-activity-list">{activity.map(e => {const c = eventCopy(e);return <li key={e.id}><span className={`sa-event-icon is-${c.tone}`}><Icon name={c.icon} size={16}/></span><div><strong>{c.title}</strong><p>{c.detail}</p></div><time dateTime={e.ts}>{new Date(e.ts).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'})}</time></li>;})}</ol> : <div className="sa-empty-state"><Icon name="route" size={25}/><div><strong>Your next mission starts the story.</strong><p>Start a mission to see each planned move, the safety check and the permit.</p></div></div> : detailTab === 'memory' ? <div className="sa-learning-summary"><div><Icon name="layers" size={28}/><h3>Robots share what they learn.</h3><p>A route lesson is only reused after a second robot confirms it and its integrity checks pass.</p><Link className="sa-text-link" href="/learning">See fleet learning <Icon name="arrow" size={14}/></Link></div><dl><div><dt>Lessons in use</dt><dd>{learning?.decisions?.filter((d:any)=>d.status==='accepted').length ?? '—'}</dd></div><div><dt>Hints only</dt><dd>{learning?.advisory ?? '—'}</dd></div><div><dt>Rejected</dt><dd>{learning?.excluded ?? '—'}</dd></div><div><dt>Integrity</dt><dd className={learning?.integrity_error ? 'sa-error' : ''}>{!learning ? 'Checking' : learning.integrity_error ? 'Learning disabled' : 'Verified'}</dd></div></dl></div> : <div className="sa-scenario-grid">{[{key:'human_approach',icon:'user',title:'A person approaches',description:'Watch the proximity rules respond to a moving worker.'},{key:'human_too_close',icon:'user',title:'A person is too close',description:'Check the hard stop response to a nearby person.'},{key:'spill',icon:'alert',title:'A spill appears',description:'Observe hazard exclusion and route revalidation.'},{key:'forklift_crossing',icon:'route',title:'A forklift crosses',description:'Check the moving-obstacle response.'},{key:'path_blocked',icon:'route',title:'The route changes',description:'Place an obstacle ahead. Movement and experience are revalidated.'},{key:'clear',icon:'check',title:'Clear the route',description:'Remove injected hazards and inspect the replacement route.'}].map(s => <button key={s.key} disabled={!live || !!busy} onClick={()=>scenario(s.key)}><Icon name={s.icon} size={22}/><strong>{s.title}</strong><p>{s.description}</p><span>Introduce scenario <Icon name="arrow" size={14}/></span></button>)}<button disabled={!!busy || !!active || !live} onClick={()=>act('drill',async()=>{const r=await runDrills(['poisoning']);setDrill(r);return r;},'Drill complete. See Safety for the full set of drills.')}><Icon name="shield" size={22}/><strong>Challenge shared memory</strong><p>{active ? 'End the active mission before running the isolated poisoning drill.' : 'Test forged records, flooding and deletion in an isolated store.'}</p><span>{drill ? `${drill.passed}/${drill.ran} drills passed` : 'Run poisoning drill'}<Icon name="arrow" size={14}/></span></button></div>}</div>
    </section>
    <section className="sa-inspection-section"><button className="sa-button" aria-expanded={inspecting} onClick={()=>{setInspecting(!inspecting);if(!inspecting)setView('2d');setPickingGoal(false);}}>{inspecting?'Hide sensors and route detail':'Show sensors and route detail'}</button>{inspecting&&world&&<MissionInspection key={selectedRobot} world={world} telemetry={telemetry?.robot_id===selectedRobot?telemetry:null} runId={composing?'':runId} events={composing?[]:events} goal={goal} live={live} pickingGoal={pickingGoal} onGoalPick={(p:any)=>{setFloorGoal({...p,x:+p.x.toFixed(2),y:+p.y.toFixed(2),label:'Floor point'});setDraft(null);setPickingGoal(false);}}/>}</section>
    <footer className="sa-control-footer"><span><span className={`sa-dot ${live ? '' : 'is-offline'}`}/>{live ? 'Connected to the simulation' : 'Waiting for a live connection'}</span><button className={`sa-voice-button ${recording ? 'is-recording' : ''}`} disabled={!!busy || !health?.voice_enabled} onClick={voice} title={health?.voice_enabled ? 'Voice can only stop robots' : 'Voice transcription is not configured. Stop fleet remains available.'}><Icon name="mic" size={15}/>{recording ? 'Listening · select to send' : health?.voice_enabled ? 'Voice stop available' : 'Voice stop not configured'}</button><span>Plans propose. Permits authorize. Evidence stays.</span></footer>
  </div>;
}
