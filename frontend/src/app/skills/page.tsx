"use client";

import dynamic from 'next/dynamic';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { Page, PageHeader, Panel } from '@/components/ui';
import { skillRequest } from '@/lib/api';
const SkillBench=dynamic(()=>import('@/components/skills/SkillBench'),{ssr:false,loading:()=> <div className="h-72 rounded bg-slate-900 p-5 text-slate-200">Loading the physics replay…</div>});
const button='rounded-md border border-violet-400 bg-violet-800 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40';

export default function SkillsPage(){
  const [data,setData]=useState<any>(null), [error,setError]=useState(''), [message,setMessage]=useState(''), [busy,setBusy]=useState(false);
  const [robot,setRobot]=useState('arm-b'), [version,setVersion]=useState(0), [result,setResult]=useState<any>(null);
  const load=async()=>{const next=await skillRequest();setData(next);setVersion(v=>v||next.versions?.at(-1)?.version||0);};
  useEffect(()=>{load().catch(e=>setError(e.message));},[]);
  const selected=data?.versions?.find((v:any)=>v.version===version);
  async function act(path:string,body:unknown={},done?: (r:any)=>void){
    setBusy(true);setError('');setMessage('');
    try{const response=await skillRequest(path,body);done?.(response);setMessage('Operation recorded.');await load();}
    catch(e:any){setError(e.message);}finally{setBusy(false);}
  }
  async function execute(){
    if(!selected)return;
    setBusy(true);setError('');setMessage('Requesting a bounded grant, then executing the learned policy on the CPU…');
    try{const grant=await skillRequest(`/${version}/grant`,{digest:selected.digest,robot_id:robot,seed:12001});
      const attempt=await skillRequest('/execute',grant);setResult(attempt);setMessage(`Execution recorded: ${attempt.result.reason}`);await load();
    }catch(e:any){setError(e.message);}finally{setBusy(false);}
  }
  const attempt=(result?.version===version&&result?.robot_id===robot ? result : null) ||
    [...(data?.attempts||[])].reverse().find((a:any)=>a.action==='finished'&&a.version===version&&a.robot_id===robot);
  return <Page>
    <PageHeader eyebrow="CPU skill lab · experimental" title="Learn once. Evaluate. Release. Try on another robot."
      subtitle="Two identical Cartesian grippers share a small learned pick-and-place policy. MuJoCo computes contacts and object motion on the CPU; no Isaac or dedicated GPU is required."/>
    <div className="mb-5 flex flex-wrap gap-4 text-violet-700"><Link href="/learning">Routing knowledge</Link><Link href="/mission-control">Warehouse operations</Link></div>
    <p className="mb-5 rounded-lg bg-slate-900 p-4 text-sm leading-relaxed text-slate-200">This is a separate bench experiment inside the operations workspace. It uses measured object coordinates, eight fixed task phases and learned continuous joint/gripper targets. It does not demonstrate vision-based manipulation, humanoid skills or physical hardware readiness. The views replay measured physics results after each operation.</p>
    {error&&<p role="alert" className="mb-4 rounded bg-red-950 p-4 text-red-100">{error}</p>}
    {message&&<p role="status" className="mb-4 rounded bg-slate-900 p-4 text-slate-100">{message}</p>}
    {data&&!data.enabled&&<Panel title="CPU lab is not enabled"><p>Your workspace administrator can enable this optional physics lab. Warehouse operations continue independently. Sign in as an operator to train, release and execute skills when the lab is enabled.</p></Panel>}
    <div className="mb-6 grid gap-5 xl:grid-cols-2"><SkillBench trace={selected?.demonstration} label="Robot A · expert demonstration"/><SkillBench trace={attempt?.result} label={`${attempt?.robot_id||'Robot B'} · learned-policy execution`}/></div>
    <div className="grid gap-5 xl:grid-cols-2">
      <Panel title="1 · Collect and learn" subtitle="Training records actual expert physics trajectories from Robot A; it does not copy a playback into Robot B.">
        <p className="mb-4 text-sm leading-relaxed">Twelve seeded demonstrations train an affine imitation policy on the CPU. Every version has a model digest and a retained, hashed dataset.</p>
        <button className={button} disabled={busy||!data?.enabled} onClick={()=>act('/train',{},r=>setVersion(r.version))}>{busy?'Working…':'Collect demonstrations and train'}</button>
        {data?.versions?.length>0&&<label className="mt-4 block text-sm font-medium">Inspect a version<select className="ml-3 rounded border border-slate-400 bg-white p-2 text-slate-900" value={version} onChange={e=>{setVersion(Number(e.target.value));setResult(null);}}>{data.versions.map((v:any)=><option key={v.version} value={v.version}>v{v.version} · {v.status}</option>)}</select></label>}
        {selected&&<div className="mt-4 space-y-2 text-sm"><p>{selected.training.samples} samples · {selected.training.demonstrations} demonstrations · {selected.training.training_wall_s.toFixed(2)} s training</p><p className="break-all">Model digest: {selected.digest}</p><p>State: <strong>{selected.status}</strong></p></div>}
      </Panel>
      <Panel title="2 · Evaluate and release" subtitle="Each action applies to the exact model digest. Installation never starts motion.">
        <div className="flex flex-wrap gap-2">{['evaluate','approve','release','withdraw'].map((action,i)=><button key={action} className={button} disabled={!selected||(action!=='withdraw'&&busy)||(action!=='withdraw'&&selected.status!==['trained','evaluated','approved'][i])||selected.status==='withdrawn'} onClick={()=>act(`/${version}/${action}`,{digest:selected.digest})}>{action==='evaluate'?'Run held-out evaluation':action==='approve'?'Approve version':action==='release'?'Release for one hour':'Withdraw'}</button>)}</div>
        {selected?.evaluation&&<div className="mt-4 text-sm leading-relaxed"><p><strong>{selected.evaluation.successes}/{selected.evaluation.trials}</strong> held-out trials succeeded · {selected.evaluation.passed?'evaluation passed':'evaluation failed'}</p><p>No-grip ablation: {selected.evaluation.no_grip_ablation_success?'unexpected success':'failed as expected'}</p><details className="mt-2"><summary>Inspect evaluation evidence</summary><pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(selected.evaluation,null,2)}</pre></details></div>}
      </Panel>
      <Panel title="3 · Install on a recipient" subtitle="A matching robot receives the same weights and executes in a fresh physics world.">
        <label className="block text-sm font-medium">Recipient<select className="ml-3 rounded border border-slate-400 bg-white p-2 text-slate-900" value={robot} onChange={e=>setRobot(e.target.value)}><option value="arm-b">Robot B · compatible gantry</option><option value="arm-a">Robot A · source gantry</option><option value="arm-c">Robot C · incompatible profile</option></select></label>
        <div className="mt-4 flex flex-wrap gap-2"><button className={button} disabled={!selected||busy||selected.status!=='released'} onClick={()=>act(`/${version}/install`,{digest:selected.digest,robot_id:robot})}>Install exact version</button><button className={button} disabled={!selected||busy||selected.status!=='released'||data?.stopped} onClick={execute}>Authorise and execute once</button></div>
        <p className="mt-3 text-sm">Installed version: {data?.installed?.[robot]?.version||'none'} · execution uses a new held-out source and destination.</p>
      </Panel>
      <Panel title="4 · Stop and inspect" subtitle="Local checks bound targets, velocity, actuator force, duration and release eligibility.">
        <div className="flex flex-wrap gap-2"><button className="rounded bg-red-800 px-4 py-2 font-semibold text-white" disabled={!data?.enabled} onClick={()=>act('/stop')}>Stop CPU lab</button><button className={button} disabled={!data?.stopped} onClick={()=>act('/reset')}>Operator reset</button><button className={button} onClick={()=>load().catch(e=>setError(e.message))}>Refresh evidence</button></div>
        <p className="mt-3 text-sm">{data?.stopped?'Stop is latched. Reset does not start a skill.':'No lab stop latched.'} A fleet-wide stop also blocks the lab.</p>
        {attempt?.result&&<div className="mt-3 space-y-1 text-sm"><p>Measured result: <strong>{attempt.result.success?'success':'failed / stopped'}</strong></p><p>Placement error: {(attempt.result.placement_error_m*1000).toFixed(3)} mm · peak object height: {attempt.result.max_object_height_m.toFixed(3)} m</p><p>{attempt.result.physics_steps} physics steps · {attempt.result.wall_s.toFixed(2)} s CPU wall time</p><p>Contact samples: {attempt.result.contact_samples} · peak actuator force: {attempt.result.max_actuator_force_n.toFixed(2)} N</p></div>}
        {selected&&<details className="mt-4 text-sm"><summary>Version audit history</summary><pre className="overflow-auto whitespace-pre-wrap">{JSON.stringify(selected.history,null,2)}</pre></details>}
      </Panel>
    </div>
  </Page>;
}
