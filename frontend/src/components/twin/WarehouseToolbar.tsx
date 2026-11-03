"use client";

import { useState } from 'react';

/** Operator controls occupy their own space; the facility is never a text backdrop. */
export function WarehouseToolbar(p: any) {
  const [panel,setPanel] = useState('');
  const toggle=(name:string)=>setPanel(panel===name?'':name);
  const fresh=p.age!==null&&p.age<4;
  return <div className="warehouse-toolbar" aria-label="Warehouse controls">
    <div className="warehouse-toolbar-row">
      <div role="group" aria-label="Camera view" className="warehouse-camera-tabs">
        {[['overview','Overview'],['follow','Follow'],['robot','Robot eye']].map(([key,label])=><button key={key} aria-pressed={p.mode===key} onClick={()=>p.setMode(key)}>{label}</button>)}
      </div>
      <span role="status" className={`warehouse-feed ${fresh?'is-live':'is-stale'}`}>{p.age===null?'Waiting for robot data':fresh?'Live robot data':`Data delayed · ${p.age}s since update`}</span>
      <button onClick={p.toggleFullscreen} aria-label={p.fullscreen?'Exit fullscreen':'Fullscreen'}>{p.fullscreen?'Exit fullscreen':'Fullscreen'}</button>
    </div>
    <div className="warehouse-toolbar-row">
      <button onClick={p.reset} title="Return to the default position for this camera">Reset camera</button>
      <button onClick={p.inspect} title="Show position, speed, clearance and the latest gate decision">Inspect robot</button>
      <button aria-expanded={panel==='layers'} onClick={()=>toggle('layers')}>Map layers</button>
      <button aria-expanded={panel==='display'} onClick={()=>toggle('display')}>Display settings</button>
      <button aria-expanded={panel==='help'} onClick={()=>toggle('help')}>View guide</button>
    </div>
    {panel&&<section className="warehouse-tool-panel" aria-label={`${panel} options`}>
      <button aria-label="Close warehouse options" className="warehouse-close-options" onClick={()=>setPanel('')}>Close</button>
      {panel==='layers'&&<>
        <strong>Map layers</strong><p>Choose the navigation and safety information shown over the facility.</p>
        <div className="warehouse-toolbar-row">
          <button aria-pressed={p.showMap} onClick={p.toggleMap}>Minimap</button>
          {p.toggleHeatmap&&<button aria-pressed={p.heatmap} onClick={p.toggleHeatmap}>Heatmap</button>}
          {p.toggleTrail&&<button aria-pressed={p.trail} onClick={p.toggleTrail}>Trail</button>}
          <button aria-pressed={p.overlay} onClick={p.toggleOverlay}>Safety overlays</button>
          {!!p.waypoints&&<button aria-pressed={p.showRoutes} onClick={p.toggleRoutes}>{p.showRoutes?'Hide route':'Show route'} · {p.waypoints} waypoints</button>}
        </div>
        <p>Minimap locates the camera. Route points describe a plan; permission to move is checked for each action.</p>
      </>}
      {panel==='display'&&<>
        <strong>Display settings</strong><p>These settings change graphics only.</p>
        <div className="warehouse-toolbar-row"><label>Graphics quality <select aria-label="Rendering quality" value={p.qualityChoice} onChange={e=>p.setQuality(e.target.value)}><option value="auto">Auto</option><option value="high">High</option><option value="low">Low</option></select></label>
        {p.cleanroom&&<label>Roof <select aria-label="Roof visibility" value={p.roofMode} onChange={e=>p.setRoofMode(e.target.value)}><option value="auto">Automatic cutaway</option><option value="show">Show roof</option><option value="hide">Hide roof</option></select></label>}</div>
        <p>Automatic cutaway shows the ceiling from inside and removes it for overhead inspection.</p>
        <output aria-label="Graphics diagnostics">Rendering: {p.fps===null?'measuring':`${p.fps} FPS`} · {p.quality} quality. FPS measures graphics speed, not robot speed.</output>
      </>}
      {panel==='help'&&<>
        <strong>View guide</strong>
        <dl><dt>Overview</dt><dd>Orbit the facility by dragging; scroll to zoom. Click actors or route points to inspect them.</dd><dt>Follow / Robot eye</dt><dd>Follow the selected robot or see from its camera height. Roof and lights appear when inside.</dd><dt>Live robot data</dt><dd>Reports freshness of received telemetry. A delay does not mean the robot has stopped.</dd><dt>Reset camera / Inspect robot</dt><dd>Restore the camera position or open measured robot details.</dd><dt>Map layers / Display settings</dt><dd>Control routes, minimap and safety graphics, or adjust rendering quality and roof visibility.</dd></dl>
      </>}
    </section>}
  </div>;
}
