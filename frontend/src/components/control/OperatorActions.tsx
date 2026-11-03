"use client";
import {useEffect,useState} from 'react';
import {getOperatorReview,operatorOverride} from '@/lib/api';

export function OperatorActions({runId,status,onChange}: {runId:string;status:string;onChange?:()=>void|Promise<void>}){
  const [review,setReview]=useState<any>(null),[reason,setReason]=useState(''),[busy,setBusy]=useState(''),[message,setMessage]=useState(''),[error,setError]=useState(false);
  useEffect(()=>{
    setReview(null);let live=true,timer:ReturnType<typeof setTimeout>;
    const poll=async()=>{try{const r=await getOperatorReview(runId);if(live)setReview(r);}catch{if(live)setReview(null);}finally{if(live)timer=setTimeout(poll,2000);}};
    if(status==='paused')void poll();
    return()=>{live=false;clearTimeout(timer);};
  },[runId,status]);
  if(!['running','paused'].includes(status))return null;
  async function act(action:string){
    setBusy(action);setMessage('');
    try{
      const result=await operatorOverride(runId,action,reason.trim(),action==='force_approve'?review?.decision_event_id:undefined);
      setError(false);setMessage(result.action==='holding_no_route'?'No clear route. Robot remains paused.':action==='replan'?'Route replaced. Robot remains paused; resume separately.':'Review approved and mission resumed. Every move still needs current permission.');
      setReview(null);await onChange?.();
    }catch(e:any){setError(true);setMessage(e.message||'Operator action failed. Check the mission state.');}
    finally{setBusy('');}
  }
  return <section className="sa-operator-actions" aria-label="Operator oversight">
    <strong>Operator oversight</strong>
    <label>Reason for intervention<textarea aria-label="Reason for intervention" value={reason} onChange={e=>setReason(e.target.value)} rows={2} maxLength={1000} placeholder="Explain the review or route change (at least 5 characters)" disabled={!!busy}/></label>
    <div className="sa-operator-buttons"><button type="button" className="sa-button" disabled={!!busy||reason.trim().length<5} onClick={()=>act('replan')}>{busy==='replan'?'Replacing route...':'Replan and hold'}</button>
      {status==='paused'&&<button type="button" className="sa-button" disabled={!!busy||!review?.eligible||reason.trim().length<5} onClick={()=>act('force_approve')}>{busy==='force_approve'?'Checking review...':'Approve review and resume'}</button>}</div>
    {status==='paused'&&<p>{review?.eligible?'Only this recorded uncertainty review can be approved. Safety-limit violations remain blocked.':review?.reason||'Checking the latest review...'}</p>}
    {message&&<p role={error?'alert':'status'}>{message}</p>}
  </section>;
}
