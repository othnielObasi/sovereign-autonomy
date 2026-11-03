"use client";

import { useEffect, useRef, useState } from 'react';

export function FacilityMap({ world, telemetry, fleet = [], goal, path = [], selected, onSelect }: any) {
  const container = useRef<SVGSVGElement>(null);
  const [size,setSize] = useState({width:700,height:450});
  useEffect(()=>{
    if(!container.current)return;
    const observer=new ResizeObserver(entries=>{const box=entries[0].contentRect; if(box.width&&box.height)setSize({width:box.width,height:box.height});});
    observer.observe(container.current); return ()=>observer.disconnect();
  },[!!world]);
  if (!world?.geofence) return <div className="sa-facility-empty"><span className="sa-map-placeholder">＋</span><strong>Waiting for the facility</strong><p>Connect the simulator to see the map, people and robot positions.</p></div>;
  const g = world.geofence;
  const width = g.max_x - g.min_x, height = g.max_y - g.min_y;
  const Y=(y:number)=>g.min_y+g.max_y-y;
  const unit = 1/Math.min(Math.max(size.width,100)/(width+2),Math.max(size.height,100)/(height+2));
  const roomFont=13*unit, detailFont=11*unit;
  const people = telemetry?.walking_humans || world.walking_humans || [];
  return <svg ref={container} className="sa-facility-map" viewBox={`${g.min_x - 1} ${g.min_y - 1} ${width + 2} ${height + 2}`} role="group" aria-label="Facility floor plan, robot positions and current target">
    <defs><pattern id="sa-floor-grid" width="1" height="1" patternUnits="userSpaceOnUse"><path d="M 1 0 L 0 0 0 1" fill="none" stroke="#d7ded2" strokeWidth=".025"/></pattern></defs>
    <rect x={g.min_x} y={g.min_y} width={width} height={height} rx=".3" fill="#e9ede3" stroke="#bac7b3" strokeWidth=".15"/><rect x={g.min_x} y={g.min_y} width={width} height={height} fill="url(#sa-floor-grid)"/>
    {(world.features || []).filter((f:any)=>f.type==='room').map((f:any)=><rect key={f.id} x={f.x-f.width/2} y={Y(f.y+f.depth/2)} width={f.width} height={f.depth} fill={f.tone||'#e8edde'} rx=".2"/>)}
    {(world.racks || []).map((r: any, i: number) => <rect data-layout-id={r.id} key={r.id || i} x={r.x1} data-world-y={r.y} y={Y(r.y+(r.depth||1))} width={r.x2 - r.x1} height={r.depth || 1} rx=".04" fill={r.kind === 'partition' ? '#466d60' : '#f9faf5'} stroke={r.kind==='partition'?'#466d60':'#829584'} strokeWidth={r.kind==='partition'?unit:unit*.8}><title>{r.label || r.id}</title></rect>)}
    {(world.bays || []).map((b: any) => <g key={b.id}><title>{b.id}: {b.label}</title><rect x={b.x - .55} y={Y(b.y+.45)} width="1.1" height=".9" rx=".15" fill="#dce9bc" stroke="#9aaa77" strokeWidth=".05"/>{!fleet.some((r:any)=>Math.hypot(r.x-b.x,r.y-b.y)<1.8)&&<text x={b.x} y={Y(b.y)+1.1} fontSize={detailFont} textAnchor="middle" fill="#304a27" stroke="#f7faf3" strokeWidth={unit*3} paintOrder="stroke">{b.id}</text>}</g>)}
    {(world.features || []).filter((f: any) => f.type === 'room').map((f: any) => {
      const y=f.y<(g.min_y+g.max_y)/2?f.y+3:f.y-3;
      const lines=String(f.label).length*roomFont*.56>f.width-1?String(f.label).split(' '):[f.label];
      return <g key={f.id}><text data-room-label={f.id} x={f.x} y={Y(y)} textAnchor="middle" fill="#243f37" stroke="#f7faf3" strokeWidth={unit*3} paintOrder="stroke" fontSize={roomFont} fontWeight="650"><title>{f.label}</title>{lines.map((line:string,i:number)=><tspan key={i} x={f.x} dy={i?roomFont*1.1:0}>{line}</tspan>)}</text></g>;
    })}
    {path.length > 1 && <polyline points={path.map((p: any) => `${p.x},${Y(p.y)}`).join(' ')} fill="none" stroke="#779e3d" strokeWidth=".18" strokeDasharray=".5 .25"/>}
    {(telemetry?.obstacles || world.obstacles || []).map((o: any, i: number) => <circle key={i} cx={o.x} cy={Y(o.y)} r={o.r || .4} fill={o.type === 'spill' ? '#ddb85b' : '#bd996c'} opacity=".85"/>)}
    {people.map((p: any, i: number) => <g key={p.id || p.name || i}><circle cx={p.x} cy={Y(p.y)} r=".7" fill="#e9bf83" opacity=".2"/><circle cx={p.x} cy={Y(p.y)} r=".2" fill="#be8747"/></g>)}
    {fleet.map((r: any, i: number) => <g key={r.robot_id} role="button" tabIndex={0} aria-label={`Select ${r.robot_id}`} onClick={() => onSelect?.(r.robot_id)} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect?.(r.robot_id); } }} className="sa-map-robot"><circle cx={r.x} cy={Y(r.y)} r={selected === r.robot_id ? 1.1 : .8} fill={r.estopped ? '#b84237' : i === 0 ? '#627f3e' : '#527787'} opacity=".13"/><title>{r.robot_profile?.label || 'Mobile carrier'}</title>{r.robot_kind==='humanoid'?<g data-robot-kind="humanoid" fill="#294f78"><circle cx={r.x} cy={Y(r.y+.25)} r=".18"/><path d={`M ${r.x-.3} ${Y(r.y-.05)} L ${r.x+.3} ${Y(r.y-.05)} M ${r.x} ${Y(r.y+.05)} L ${r.x} ${Y(r.y-.35)} M ${r.x} ${Y(r.y-.35)} L ${r.x-.23} ${Y(r.y-.62)} M ${r.x} ${Y(r.y-.35)} L ${r.x+.23} ${Y(r.y-.62)}`} stroke="#294f78" strokeWidth=".13"/></g>:<rect x={r.x - .38} y={Y(r.y+.38)} width=".76" height=".76" rx=".18" fill={r.estopped ? '#b84237' : i === 0 ? '#365b32' : '#527787'}/>}<text x={r.x} y={Y(r.y)+1.5} textAnchor="middle" fontSize={detailFont} fill="#243f37" stroke="#f7faf3" strokeWidth={unit*2} paintOrder="stroke" fontWeight="600">{r.robot_id}</text></g>)}
    {goal && <g><circle cx={goal.x} cy={Y(goal.y)} r=".8" fill="none" stroke="#7ca145" strokeWidth=".12"/><path d={`M${goal.x-.4} ${Y(goal.y)}h.8M${goal.x} ${Y(goal.y)-.4}v.8`} stroke="#7ca145" strokeWidth=".1"/></g>}
  </svg>;
}
