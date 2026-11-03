"use client";
import { useEffect, useState } from 'react';
import { getPolicyProposals, policyWorkflow, storedSession } from '@/lib/api';
import { useRuntimeCapabilities } from './RuntimeCapabilities';
import { Button, Notice, Panel, Verdict } from './ui';

export function RulesWorkflow({ active, onChange }: { active: any; onChange: () => void }) {
  const health = useRuntimeCapabilities();
  const [proposals, setProposals] = useState<any[]>([]), [path, setPath] = useState('');
  const [value, setValue] = useState(''), [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false), [message, setMessage] = useState(''), [error, setError] = useState('');
  const [session, setSession] = useState<ReturnType<typeof storedSession>>(null);
  const refresh = () => getPolicyProposals().then(setProposals).catch(e => setError(e.message));
  useEffect(() => { void refresh(); const t = setInterval(() => { setSession(storedSession()); }, 1000); setSession(storedSession()); return () => clearInterval(t); }, []);
  const dev = health?.environment === 'development' && !session;
  const operator = dev || ['operator', 'admin'].includes(session?.role || '');
  const admin = dev || session?.role === 'admin';
  const writable = !!health && !health.public_demo && operator;
  const spec = active?.changeable?.[path];
  async function act(action: string, body: any, id?: string) {
    setBusy(true); setMessage(''); setError('');
    try { await policyWorkflow(action, body, id); await refresh(); onChange(); setMessage(`${action} recorded. Review the result before the next stage.`); }
    catch (e: any) { setError(e.message || 'Request failed'); }
    finally { setBusy(false); }
  }
  return <Panel title="Governed rule changes" subtitle="Every stage is explicit. Replay, benchmark and separate approval must pass before activation.">
    {!writable && <Notice>{!health ? 'Checking deployment permissions.' : health.public_demo ? 'Rule editing is read-only in this public workspace.' : 'Sign in as an operator to propose and evaluate changes. An administrator activates them.'}</Notice>}
    {dev && <Notice>Development authentication is enabled. Actions use the development token identity; a different signed-in operator must approve its proposals.</Notice>}
    <form className="grid gap-3 my-3" onSubmit={e => { e.preventDefault(); void act('create', { changes: { [path]: Number(value) }, description: reason }); }}>
      <label className="text-sm">Threshold<select aria-label="Rule threshold" className="block w-full border rounded p-2 bg-mc-panel" value={path} onChange={e => { setPath(e.target.value); setValue(''); }} disabled={!writable || busy}><option value="">Choose a threshold</option>{Object.keys(active?.changeable || {}).map(k => <option key={k}>{k}</option>)}</select></label>
      <label className="text-sm">Proposed value {spec && `(${spec.min} to ${spec.max} ${spec.unit || ''})`}<input aria-label="Proposed value" className="block w-full border rounded p-2 bg-mc-panel" type="number" step="any" min={spec?.min} max={spec?.max} value={value} onChange={e => setValue(e.target.value)} disabled={!writable || busy} required /></label>
      <label className="text-sm">Reason / review note<input aria-label="Rule change reason" className="block w-full border rounded p-2 bg-mc-panel" value={reason} onChange={e => setReason(e.target.value)} minLength={5} required disabled={!writable || busy} /></label>
      <Button type="submit" disabled={!writable || busy || !spec || !value || reason.trim().length < 5}>Create proposal</Button>
    </form>
    {error && <Notice tone="stop">{error}</Notice>}{message && <Notice>{message}</Notice>}
    {busy && <p role="status" className="text-sm my-2">Waiting for the requested stage. Benchmarking may take several seconds.</p>}
    <div className="space-y-3">{proposals.map(p => <article key={p.id} className="border border-mc-line rounded p-3 min-w-0">
      <div className="flex flex-wrap gap-2"><Verdict value={p.status} /><span className="text-sm break-all">{p.id} · proposed by {p.created_by}</span></div>
      <p className="text-sm my-2">{p.description}</p><pre className="text-xs whitespace-pre-wrap break-all">{JSON.stringify(p.changes, null, 2)}</pre>
      {p.evaluation && <details className="my-2 text-xs"><summary>Replay & benchmark results</summary><pre className="whitespace-pre-wrap break-all">{JSON.stringify(p.evaluation, null, 2)}</pre></details>}
      <div className="flex flex-wrap gap-2 mt-2">
        {['draft','evaluated','failed_evaluation'].includes(p.status) && <Button disabled={!writable || busy} onClick={() => act('evaluate', { limit: 5000 }, p.id)}>Replay evaluation</Button>}
        {['evaluated','failed_evaluation'].includes(p.status) && <Button disabled={!writable || busy} onClick={() => act('benchmark', { seeds: 5 }, p.id)}>Run benchmark · 5 seeds</Button>}
        {p.status === 'evaluated' && <Button disabled={!writable || busy || !session || session.user === p.created_by || (p.evaluation?.relaxes_any_rule && p.evaluation?.benchmark?.status !== 'passed')} onClick={() => act('approve', { note: reason }, p.id)}>Approve as {session?.user || 'a separate operator'}</Button>}
        {p.status === 'approved' && <Button disabled={!writable || !admin || busy} onClick={() => act('activate', {}, p.id)}>Activate approved rules</Button>}
        {['draft','evaluated','failed_evaluation','approved'].includes(p.status) && <Button disabled={!writable || busy || reason.trim().length < 5} onClick={() => act('reject', { reason }, p.id)}>Reject with reason</Button>}
      </div>
    </article>)}</div>
    {!active?.is_default && <div className="mt-3"><Button disabled={!writable || !admin || busy || reason.trim().length < 5} onClick={() => act('rollback', { reason })}>Roll back to default rules</Button><p className="text-xs mt-2 text-mc-mute">Requires a reason above. The server refuses activation or rollback while runs are active.</p></div>}
  </Panel>;
}
