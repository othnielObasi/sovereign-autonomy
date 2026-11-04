"use client";

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { learningRequest, storedSession } from '@/lib/api';
import { Page, PageHeader, Panel } from '@/components/ui';

type Evidence = { id: string; source_robot_id: string; i: number; j: number; delay_s: number; run_id: string };
type Lesson = { lesson_id: string; version: number; digest: string; title: string; notice: string; source_url: string; origin_robot_id: string; status: string; context: Record<string, string>; expires_at: number; evidence_ids: string[]; evaluation?: { passed: boolean; reason?: string; scope: string }; history: { id: string; action: string; actor: string; at: number }[] };
type Overview = { robot_id: string; context: Record<string, string>; evidence: Evidence[]; lessons: Lesson[]; memory_integrity_error: string | null; eligibility: { accepted: { lesson_id: string; version: number; recipient_robot_id: string }[]; excluded: { lesson_id: string; version: number; reason: string }[] } };
const field = 'w-full rounded-md border border-slate-500 bg-slate-950 px-3 py-2 text-slate-100';
const button = 'rounded-md border border-violet-400 bg-violet-800 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40';

export default function LearningPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [robot, setRobot] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [title, setTitle] = useState('Review recurring corridor congestion');
  const [notice, setNotice] = useState('');
  const [source, setSource] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [revision, setRevision] = useState<Lesson | null>(null);
  const [canWrite, setCanWrite] = useState(true);
  const load = useCallback(async (id = '') => {
    const next = await learningRequest(id ? `?robot_id=${encodeURIComponent(id)}` : '');
    setData(next); setRobot(next.robot_id);
    const session = storedSession();
    setCanWrite(!session || ['operator', 'admin'].includes(session.role));
  }, []);
  useEffect(() => { load().catch(e => setError(e.message)); }, [load]);
  async function perform(task: () => Promise<void>) {
    setBusy(true); setError(''); setMessage('');
    try { await task(); } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }
  async function transition(lesson: Lesson, action: string) {
    await perform(async () => {
      const result = await learningRequest(`/${lesson.lesson_id}/${lesson.version}/${action}`, { robot_id: data?.robot_id || robot, expected_digest: lesson.digest });
      setMessage(`${lesson.title} / v${lesson.version}: ${result.status}${result.evaluation?.reason ? ' — ' + result.evaluation.reason : ''}`);
      await load(data?.robot_id);
    });
  }
  const groups = new Map<string, Evidence[]>();
  for (const row of data?.evidence || []) { const key = `${row.i},${row.j}`; groups.set(key, [...(groups.get(key) || []), row]); }
  // Same rule as the server: another robot was delayed in this cell or a touching one (about 0.75 m)
  const nearbyRobots = (rows: Evidence[]) => new Set((data?.evidence || []).filter(o => rows.some(r => Math.abs(o.i - r.i) <= 1 && Math.abs(o.j - r.j) <= 1)).map(o => o.source_robot_id));
  const corroborated = [...groups].filter(([, rows]) => nearbyRobots(rows).size >= 2);
  const originCorroborated = corroborated.filter(([, rows]) => [...nearbyRobots(rows)].includes(data?.robot_id || ''));
  return <Page>
    <PageHeader eyebrow="Governed collective learning" title="Review knowledge before the fleet reuses it"
      subtitle="Create a bounded congestion caution from signed robot observations. Evaluate, approve and release one version; each receiving robot must still pass its own movement checks." />
    <div className="flex gap-5 mb-5 text-violet-200"><Link href="/authority#route-learning">Route memory &amp; execution authority →</Link><Link href="/missions">Collect evidence through missions →</Link></div>
    <p className="mb-5 rounded-lg border border-slate-500 bg-slate-900 p-4 text-slate-200">This workspace uses persistent backend records. External text remains untrusted context. Sharing requires signed evidence from at least two robot identities per cell. Approval adds only a bounded positive congestion margin; it never authorises movement or relaxes a safety rule.</p>
    <form className="mb-6 flex flex-wrap items-end gap-3" onSubmit={e => { e.preventDefault(); perform(() => load(robot)); }}>
      <label className="text-sm text-slate-200">Inspect a receiving robot<input className={field} value={robot} onChange={e => setRobot(e.target.value)} placeholder="Robot ID" required maxLength={128} /></label>
      <button className={button} disabled={busy}>Refresh current context</button>
      {data && <p className="text-sm text-slate-300">Loaded: {data.robot_id} · {data.context.capability_profile_version}</p>}
    </form>
    {error && <p role="alert" className="mb-5 rounded border border-red-400 bg-red-950 p-4 text-red-100">{error}. Sign in through Operator access if authentication is required.</p>}
    {message && <p role="status" className="mb-5 rounded border border-emerald-500 bg-emerald-950 p-4 text-emerald-100">{message}</p>}
    {data?.memory_integrity_error && <p role="alert" className="text-red-200">Source memory integrity failed. No evidence can be released: {data.memory_integrity_error}</p>}
    <div className="grid gap-6 xl:grid-cols-2">
      <Panel title={revision ? `Revise ${revision.title} / next version` : 'Propose a congestion caution'} subtitle="Use real signed observations; the server verifies them again at evaluation, approval, release and retrieval.">
        <form className="space-y-4" onSubmit={e => { e.preventDefault(); perform(async () => {
          const result = await learningRequest('/candidates', { robot_id: data?.robot_id, title, notice, source_url: source, evidence_ids: selected,
            ...(revision ? { lesson_id: revision.lesson_id, expected_digest: revision.digest } : {}) });
          setMessage(`Candidate v${result.version} persisted. Evaluation and operator approval are still required.`);
          setRevision(null); setSelected([]); await load(data?.robot_id);
        }); }}>
          <label className="block text-sm text-slate-200">Title<input className={field} value={title} onChange={e => setTitle(e.target.value)} required maxLength={120} /></label>
          <label className="block text-sm text-slate-200">External notice or operational context (optional)<textarea className={field} value={notice} onChange={e => setNotice(e.target.value)} maxLength={700} rows={3} /></label>
          <label className="block text-sm text-slate-200">Source reference (optional; stored, never fetched)<input className={field} value={source} onChange={e => setSource(e.target.value)} maxLength={400} /></label>
          <fieldset className="space-y-2"><legend className="mb-2 font-semibold text-slate-100">Verified source cells</legend>
            {corroborated.length > 0 && <div className="flex flex-wrap items-center gap-3 text-sm text-slate-200">
              <span>{corroborated.length} cell(s) corroborated by two or more robots.</span>
              <button type="button" className={button} disabled={busy || !originCorroborated.length} onClick={() => setSelected(originCorroborated.flatMap(([, rows]) => rows.map(r => r.id)))}>Select corroborated cells</button>
              {!originCorroborated.length && <span>Inspect one of the robots that observed them to propose.</span>}
            </div>}
            {!groups.size && <p className="text-slate-300">No eligible signed observations for this context yet. Complete missions with two compatible robot identities that independently observe congestion in the same area, then refresh. No example evidence is manufactured here.</p>}
            {[...groups].map(([key, rows]) => <label key={key} className="flex gap-3 rounded border border-slate-600 p-3 text-slate-200">
              <input type="checkbox" checked={rows.every(r => selected.includes(r.id))} onChange={e => setSelected(old => e.target.checked ? [...new Set([...old, ...rows.map(r => r.id)])] : old.filter(id => !rows.some(r => r.id === id)))} />
              <span>Cell {key} · {new Set(rows.map(r => r.source_robot_id)).size} source robot(s) here · {nearbyRobots(rows).size >= 2 ? 'corroborated nearby' : 'needs a second robot nearby'}<br /><small>{rows.map(r => `${r.source_robot_id}: ${r.delay_s}s (${r.run_id})`).join(' · ')}</small></span>
            </label>)}
          </fieldset>
          <p className="text-sm text-slate-300">Origin: {data?.robot_id || 'unavailable'}. Expiry: one hour. The origin must be represented in the selected signed evidence.</p>
          <button className={button} disabled={busy || !canWrite || !selected.length || !data}>{revision ? 'Create revision & withdraw previous version' : 'Persist candidate'}</button>
          {revision && <button className="ml-3 text-violet-200" type="button" onClick={() => setRevision(null)}>Cancel revision</button>}
        </form>
      </Panel>
      <Panel title="Versioned review & release" subtitle="Approval and release are separate signed audit events. Revisions cannot inherit approval.">
        {!data?.lessons.length && <p className="text-slate-300">No candidate versions have been created.</p>}
        <div className="space-y-4">{[...(data?.lessons || [])].reverse().map(lesson => {
          const latest = !data?.lessons.some(other => other.lesson_id === lesson.lesson_id && other.version > lesson.version);
          const expired = Date.now() / 1000 >= lesson.expires_at;
          const received = data?.eligibility.accepted.some(r => r.lesson_id === lesson.lesson_id && r.version === lesson.version);
          const excluded = data?.eligibility.excluded.find(r => r.lesson_id === lesson.lesson_id && r.version === lesson.version);
          return <article key={`${lesson.lesson_id}:${lesson.version}`} className="rounded-lg border border-slate-500 bg-slate-900 p-4" data-lesson-status={lesson.status}>
            <h3 className="text-lg font-semibold text-white">{lesson.title} / v{lesson.version}</h3>
            <p className="my-2 text-violet-200">{lesson.status}{expired ? ' · expired' : ''} · origin {lesson.origin_robot_id}</p>
            <p className="text-sm text-slate-200">{received ? `${data?.robot_id}: eligible for this released version at the next route plan.` : `Not offered: ${excluded?.reason || 'pending'}`}</p>
            {lesson.evaluation && <p className="mt-2 text-sm text-slate-200">Evaluation: {lesson.evaluation.passed ? 'passed' : 'rejected'} {lesson.evaluation.reason}</p>}
            <div className="mt-4 flex flex-wrap gap-2">{['evaluate', 'approve', 'release'].map((action, i) => <button key={action} className={button} disabled={busy || !canWrite || !latest || expired || lesson.status !== ['candidate', 'evaluated', 'approved'][i]} onClick={() => transition(lesson, action)}>{action === 'evaluate' ? 'Evaluate evidence' : action === 'approve' ? 'Approve this version' : 'Release to compatible planners'}</button>)}
              <button className={button} disabled={busy || !canWrite || !latest || lesson.status === 'withdrawn'} onClick={() => transition(lesson, 'withdraw')}>Withdraw</button>
              <button className={button} disabled={busy || !canWrite || !latest} onClick={() => { setRevision(lesson); setTitle(lesson.title); setNotice(lesson.notice); setSource(lesson.source_url); setSelected(lesson.evidence_ids); }}>Prepare revision</button>
            </div>
            <details className="mt-4 text-sm text-slate-200"><summary className="cursor-pointer">Inspect provenance, context and audit history</summary>
              <p className="mt-2 break-all">Digest: {lesson.digest}</p><pre className="my-2 whitespace-pre-wrap break-all">{JSON.stringify(lesson.context, null, 2)}</pre>
              <p className="whitespace-pre-wrap">Untrusted context: {lesson.notice || 'none'}</p><p className="break-all">Source reference: {lesson.source_url || 'none'}</p>
              <p>Expires: {new Date(lesson.expires_at * 1000).toLocaleString()}</p>
              <ul className="mt-3 space-y-1">{lesson.history.map(event => <li key={event.id}>{event.action} · {event.actor} · {new Date(event.at * 1000).toLocaleString()}</li>)}</ul>
            </details>
          </article>;
        })}</div>
      </Panel>
    </div>
  </Page>;
}
