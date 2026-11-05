"use client";

import { useEffect, useMemo, useState } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';

export type SkillFrame = { t: number; phase: string; joints: number[]; container: number[]; quaternion: number[] };
export type SkillTrace = { frames: SkillFrame[]; source: number[]; target: number[]; success: boolean; reason: string };

function Bench({ frame, target }: { frame: SkillFrame; target: number[] }) {
  const [x,y,z,l,r] = frame.joints;
  const [qw,qx,qy,qz] = frame.quaternion;
  return <>
    <ambientLight intensity={1.2}/><directionalLight position={[2,4,2]} intensity={2.2}/>
    <mesh position={[0,-.02,0]}><boxGeometry args={[1.05,.04,.75]}/><meshStandardMaterial color="#475569" roughness={.7}/></mesh>
    {[-.45,.45].map(a=><mesh key={a} position={[a,.26,.26]}><boxGeometry args={[.035,.56,.035]}/><meshStandardMaterial color="#94a3b8" metalness={.6} roughness={.3}/></mesh>)}
    <mesh position={[0,.54,.26]}><boxGeometry args={[.96,.035,.045]}/><meshStandardMaterial color="#cbd5e1"/></mesh>
    <mesh position={[x,.50,-y]}><boxGeometry args={[.08,.04,.08]}/><meshStandardMaterial color="#8b5cf6"/></mesh>
    <mesh position={[x,(.50+.4+z)/2,-y]}><boxGeometry args={[.018,Math.max(.01,.50-(.4+z)),.018]}/><meshStandardMaterial color="#cbd5e1"/></mesh>
    <mesh position={[x,.4+z+.015,-y]}><boxGeometry args={[.15,.03,.10]}/><meshStandardMaterial color="#a78bfa"/></mesh>
    {[x-.065+l,x+.065-r].map((a,i)=><mesh key={i} position={[a,.4+z-.045,-y]}><boxGeometry args={[.016,.07,.07]}/><meshStandardMaterial color="#1e293b"/></mesh>)}
    <mesh position={[frame.container[0],frame.container[2],-frame.container[1]]} quaternion={[qx,qz,-qy,qw]}><boxGeometry args={[.05,.05,.05]}/><meshStandardMaterial color="#22d3ee" roughness={.45}/></mesh>
    <mesh position={[target[0],.001,-target[1]]} rotation={[-Math.PI/2,0,0]}><ringGeometry args={[.045,.052,40]}/><meshBasicMaterial color="#4ade80"/></mesh>
    <OrbitControls target={[0,.16,0]} enablePan={false} minDistance={.6} maxDistance={2.5} maxPolarAngle={1.5}/>
  </>;
}

export default function SkillBench({ trace, label }: { trace?: SkillTrace | null; label: string }) {
  const [index,setIndex] = useState(0), [playing,setPlaying] = useState(false);
  useEffect(()=>{setIndex(0);setPlaying(!!trace?.frames?.length);},[trace]);
  useEffect(()=>{
    if(!playing || !trace?.frames.length) return;
    const timer=setInterval(()=>setIndex(i=>{if(i>=trace.frames.length-1){setPlaying(false);return i;}return i+1;}),60);
    return ()=>clearInterval(timer);
  },[playing,trace]);
  const idle = useMemo(()=>({t:0,phase:'idle',joints:[0,0,-.17,0,0],container:[-.22,0,.025],quaternion:[1,0,0,0]}),[]);
  const frame=trace?.frames[index] || idle;
  return <section className="overflow-hidden rounded-xl border border-slate-600 bg-slate-900 text-slate-100">
    <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3"><h3 className="font-semibold">{label}</h3><span className="text-xs text-cyan-200">{trace ? 'Recorded CPU physics · replay' : 'Ready · no execution'}</span></div>
    <div style={{height:280}}><Canvas frameloop="demand" camera={{position:[.85,.75,.95],fov:45}} dpr={[1,1.3]}><color attach="background" args={['#111827']}/><Bench frame={frame} target={trace?.target||[.22,0]}/></Canvas></div>
    <div className="space-y-2 p-4"><div className="flex items-center gap-3"><button disabled={!trace} className="rounded border border-slate-500 px-3 py-1 disabled:opacity-40" onClick={()=>{if(trace&&index>=trace.frames.length-1)setIndex(0);setPlaying(!playing);}}>{playing?'Pause replay':'Play replay'}</button><span className="text-sm">{frame.phase} · {frame.t.toFixed(2)} s</span></div>
      <input aria-label={`${label} replay position`} type="range" min={0} max={Math.max(0,(trace?.frames.length||1)-1)} value={index} onChange={e=>{setPlaying(false);setIndex(Number(e.target.value));}} className="w-full" disabled={!trace}/>
      <p className="text-sm text-slate-300">{trace ? `${trace.success?'Measured success':'Stopped or failed'} · ${trace.reason}` : 'Physics results will appear here after the operation completes.'}</p>
    </div>
  </section>;
}
