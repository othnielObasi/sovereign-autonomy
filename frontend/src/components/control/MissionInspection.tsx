"use client";
import dynamic from 'next/dynamic';
import { useEffect, useState } from 'react';
import { getExecutedPath, getRiskHeatmap } from '@/lib/api';
const Warehouse3D=dynamic(()=>import('@/components/twin/Warehouse3D'),{ssr:false});

/** Retains the original inspection tools directly inside the operational workspace. */
export default function MissionInspection({world,telemetry,runId,goal,events,live,onGoalPick,pickingGoal}:any){
  const [recorded,setRecorded]=useState<any[]>([]),[executed,setExecuted]=useState<any[]>([]),[risk,setRisk]=useState<any[]>([]);
  const [hover,setHover]=useState<number|null>(null),[showPlan,setShowPlan]=useState(true),[showExecuted,setShowExecuted]=useState(true);
  useEffect(()=>{
    setRecorded([]);setExecuted([]);setRisk([]);
    if(!runId)return;
    let disposed=false,timer:ReturnType<typeof setTimeout>;
    const poll=async()=>{
      const rows=await Promise.allSettled([fetch(`${process.env.NEXT_PUBLIC_API_BASE||'/api'}/runs/${runId}/events?limit=500&latest=true`).then(r=>{if(!r.ok)throw Error();return r.json();}),getExecutedPath(runId),getRiskHeatmap(runId)]);
      if(disposed)return;
      if(rows[0].status==='fulfilled')setRecorded(rows[0].value);
      if(rows[1].status==='fulfilled')setExecuted(rows[1].value.executed_path||[]);
      if(rows[2].status==='fulfilled')setRisk(rows[2].value.cells||[]);
      timer=setTimeout(poll,3000);
    };void poll();return()=>{disposed=true;clearTimeout(timer);};
  },[runId]);
  const source=recorded.length?recorded:events;
  const planEvent=[...source].reverse().find((e:any)=>e.type==='PLAN');
  const waypoints=planEvent?.payload?.plan?.waypoints||[];
  const decisionEvent=[...events].reverse().find((e:any)=>e.type==='DECISION');
  const decision=decisionEvent?.payload?.governance;
  const latestChange=[...source].reverse().find((e:any)=>e.type==='ENVIRONMENT_CHANGE');
  const target=Array.isArray(telemetry?.target)?{x:telemetry.target[0],y:telemetry.target[1]}:telemetry?.target;
  const sameMap=(!planEvent?.payload?.map_version||planEvent.payload.map_version===telemetry?.map_version)&&(!latestChange||!planEvent||Date.parse(latestChange.ts)<=Date.parse(planEvent.ts));
  return <section className="sa-inspection" aria-label="Detailed mission inspection">
    <p className="sa-inspection-note">{live?'Live robot telemetry':'Telemetry is stale'} · Plan and travelled path are recorded evidence. Every new move requires a current permit.</p>
    <div className="sa-inspection-view"><Warehouse3D world={world} telemetry={telemetry} quality="low" goal={goal} pickingGoal={pickingGoal} onGoalPick={onGoalPick}
      pathPoints={target&&telemetry?[{x:telemetry.x,y:telemetry.y},target]:null} planWaypoints={showPlan&&sameMap?waypoints:[]} executedPath={showExecuted?executed:[]} trailPoints={executed} riskCells={risk}
      hoveredWaypointIdx={hover} safetyState={decision?.policy_state} verdict={decision?.decision} verdictText={decision?.reasons?.join(' ')} proposal={decisionEvent?.payload?.proposal}/></div>
    <div className="sa-inspection-options"><label><input type="checkbox" checked={showPlan} onChange={e=>setShowPlan(e.target.checked)}/> Recorded plan</label><label><input type="checkbox" checked={showExecuted} onChange={e=>setShowExecuted(e.target.checked)}/> Travelled path ({executed.length} samples)</label></div>
    <div className="sa-inspection-grid"><div><h3>Recorded waypoints</h3>{!sameMap?<p>Map changed. Previous plan hidden.</p>:waypoints.length?<ol className="sa-waypoint-list">{waypoints.map((p:any,i:number)=><li key={i}><button onFocus={()=>setHover(i)} onBlur={()=>setHover(null)} onMouseEnter={()=>setHover(i)} onMouseLeave={()=>setHover(null)}>{i+1}. X {Number(p.x).toFixed(2)} · Y {Number(p.y).toFixed(2)} · {Number(p.max_speed??0).toFixed(2)} m/s cap</button></li>)}</ol>:<p>No recorded plan for this robot.</p>}</div>
    <div><h3>Latest recorded decision</h3>{decision?<><strong>{decision.decision}</strong><ul>{(decision.reasons||[]).map((r:string,i:number)=><li key={i}>{r}</li>)}</ul><p>Policies: {(decision.policy_hits||[]).join(', ')||'No policy hits'}</p>{decision.required_action&&<p>Required action: {decision.required_action}</p>}</>:<p>No decision recorded.</p>}<h3>Current platform and clearance</h3><p>{telemetry?.robot_profile?.label||'Robot'} · {telemetry?.robot_profile?.role||'Navigation'}</p><p>Obstacle clearance: {Number.isFinite(telemetry?.nearest_obstacle_m)?Number(telemetry.nearest_obstacle_m).toFixed(2)+' m':'Unavailable'}</p><p>Profile: {telemetry?.capability_profile_version||'Unavailable'}</p></div></div>
  </section>;
}
