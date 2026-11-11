"use client";

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { learningRequest, storedSession } from '@/lib/api';
import { Page, PageHeader, Panel } from '@/components/ui';

type Evidence = { id: string; source_robot_id: string; i: number; j: number; delay_s: number; run_id: string };
type Lesson = { lesson_id: string; version: number; digest: string; title: string; notice: string; source_url: string; origin_robot_id: string; status: string; context: Record<string, string>; expires_at: number; evidence_ids: string[]; evaluation?: { passed: boolean; reason?: string; scope: string }; history: { id: string; action: string; actor: string; at: number }[] };
type Overview = { robot_id: string; context: Record<string, string>; evidence: Evidence[]; lessons: Lesson[]; memory_integrity_error: string | null; eligibility: { accepted: { lesson_id: string; version: number; recipient_robot_id: string }[]; excluded: { lesson_id: string; version: number; reason: string }[] } };
const field = 'mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-slate-900';
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
  const single = [...groups].filter(([, rows]) => nearbyRobots(rows).size < 2);
  const now = Date.now() / 1000;
  const allLessons = [...(data?.lessons || [])].reverse();
  const isCurrent = (l: Lesson) => now < l.expires_at && l.status !== 'withdrawn';
  const currentLessons = allLessons.filter(isCurrent), pastLessons = allLessons.filter(l => !isCurrent(l));
  const statusText: Record<string, string> = { candidate: 'Proposed · waiting for evaluation', evaluated: 'Evaluated · waiting for approval', approved: 'Approved · ready to release', released: 'Released to the fleet', rejected: 'Rejected at evaluation', withdrawn: 'Withdrawn' };
  const cell = ([key, rows]: [string, Evidence[]]) => <label key={key} className="flex gap-3 rounded border border-slate-300 bg-white p-3 text-slate-800">
    <input type="checkbox" checked={rows.every(r => selected.includes(r.id))} onChange={e => setSelected(old => e.target.checked ? [...new Set([...old, ...rows.map(r => r.id)])] : old.filter(id => !rows.some(r => r.id === id)))} />
    <span>Area {key} · {nearbyRobots(rows).size >= 2 ? 'confirmed by two robots' : 'seen by one robot'}<br /><small className="text-slate-500">{rows.map(r => `${r.source_robot_id} delayed ${r.delay_s}s`).join(' · ')}</small></span>
  </label>;
  const renderLesson = (lesson: Lesson) => {
    const latest = !data?.lessons.some(other => other.lesson_id === lesson.lesson_id && other.version > lesson.version);
    const expired = now >= lesson.expires_at;
    const received = data?.eligibility.accepted.some(r => r.lesson_id === lesson.lesson_id && r.version === lesson.version);
    const excluded = data?.eligibility.excluded.find(r => r.lesson_id === lesson.lesson_id && r.version === lesson.version);
    const step = ['candidate', 'evaluated', 'approved'].indexOf(lesson.status);
    const next = step >= 0 ? (['evaluate', 'approve', 'release'] as const)[step] : null;
    const label = { evaluate: 'Evaluate evidence', approve: 'Approve this version', release: 'Release to the fleet' };
    const live = latest && !expired && canWrite;
    const quiet = 'rounded-md border border-slate-300 px-4 py-2 text-sm text-slate-700 disabled:opacity-40';
    return <article key={`${lesson.lesson_id}:${lesson.version}`} className="rounded-lg border border-slate-300 bg-white p-4" data-lesson-status={lesson.status}>
      <h3 className="text-lg font-semibold text-slate-900">{lesson.title} <span className="text-sm font-normal text-slate-500">v{lesson.version}</span></h3>
      <p className="my-1 font-medium text-violet-800">{expired ? 'Expired' : statusText[lesson.status] || lesson.status}</p>
      {lesson.status === 'released' && !expired && <p className="text-sm text-slate-700">{received ? `${data?.robot_id} will use it on its next route plan.` : `Not used by ${data?.robot_id}: ${excluded?.reason || 'not compatible'}`}</p>}
      {lesson.evaluation && !lesson.evaluation.passed && <p className="mt-1 text-sm text-slate-700">Reason: {lesson.evaluation.reason}</p>}
      {live && <div className="mt-3 flex flex-wrap gap-2">
        {next && <button className={button} disabled={busy} onClick={() => transition(lesson, next)}>{label[next]}</button>}
        {lesson.status !== 'withdrawn' && <button className={quiet} disabled={busy} onClick={() => transition(lesson, 'withdraw')}>Withdraw</button>}
        <button className={quiet} disabled={busy} onClick={() => { setRevision(lesson); setTitle(lesson.title); setNotice(lesson.notice); setSource(lesson.source_url); setSelected(lesson.evidence_ids); }}>Revise</button>
      </div>}
      <details className="mt-3 text-sm text-slate-600"><summary className="cursor-pointer">Technical details</summary>
        <p className="mt-2">Origin robot: {lesson.origin_robot_id}</p>
        <p className="break-all">Digest: {lesson.digest}</p><pre className="my-2 whitespace-pre-wrap break-all">{JSON.stringify(lesson.context, null, 2)}</pre>
        <p className="whitespace-pre-wrap">External note (untrusted): {lesson.notice || 'none'}</p><p className="break-all">Source reference: {lesson.source_url || 'none'}</p>
        <p>Expires: {new Date(lesson.expires_at * 1000).toLocaleString()}</p>
        <ul className="mt-3 space-y-1">{lesson.history.map(event => <li key={event.id}>{event.action} · {event.actor} · {new Date(event.at * 1000).toLocaleString()}</li>)}</ul>
      </details>
    </article>;
  };
  return <Page>
    <PageHeader eyebrow="Fleet learning" title="Robots learn from each other, with your sign-off"
      subtitle="When two robots are delayed in the same area, that can become a lesson for the whole fleet. Nothing is shared until you evaluate, approve and release it, and robots still check every move." />
    <ol className="mb-6 grid gap-3 text-sm text-slate-700 sm:grid-cols-4">{['Robots report where they were delayed', 'Propose a lesson from areas two robots confirmed', 'Evaluate it, then approve it', 'Release it to compatible robots'].map((t, i) => <li key={t} className="rounded-lg border border-slate-300 bg-white p-3"><strong className="mr-1 text-violet-800">{i + 1}.</strong>{t}</li>)}</ol>
    <details className="mb-6 text-sm text-slate-700"><summary className="cursor-pointer">Viewing as {data?.robot_id || '…'} · change robot</summary>
    <form className="mt-3 flex flex-wrap items-end gap-3" onSubmit={e => { e.preventDefault(); perform(() => load(robot)); }}>
      <label className="text-sm font-medium text-slate-700">Robot ID<input className={field} value={robot} onChange={e => setRobot(e.target.value)} placeholder="robot-2" required maxLength={128} /></label>
      <button className={button} disabled={busy}>Show this robot</button>
      {data && <span className="text-slate-500">Profile {data.context.capability_profile_version}</span>}
    </form></details>
    {error && <p role="alert" className="mb-5 rounded border border-red-400 bg-red-950 p-4 text-red-100">{error}. Approving and releasing lessons needs an operator sign-in.</p>}
    {message && <p role="status" className="mb-5 rounded border border-emerald-500 bg-emerald-950 p-4 text-emerald-100">{message}</p>}
    {data?.memory_integrity_error && <p role="alert" className="text-red-700">Source memory integrity failed. No evidence can be released: {data.memory_integrity_error}</p>}
    <div className="grid gap-6 xl:grid-cols-2">
      <Panel title={revision ? `Revise: ${revision.title}` : 'Propose a lesson'} subtitle="Pick areas where robots were delayed. Only areas confirmed by two robots can be shared.">
        <form className="space-y-4" onSubmit={e => { e.preventDefault(); perform(async () => {
          const result = await learningRequest('/candidates', { robot_id: data?.robot_id, title, notice, source_url: source, evidence_ids: selected,
            ...(revision ? { lesson_id: revision.lesson_id, expected_digest: revision.digest } : {}) });
          setMessage(`Lesson proposed (v${result.version}). Next: evaluate it.`);
          setRevision(null); setSelected([]); await load(data?.robot_id);
        }); }}>
          <label className="block text-sm font-medium text-slate-700">Title<input className={field} value={title} onChange={e => setTitle(e.target.value)} required maxLength={120} /></label>
          <label className="block text-sm font-medium text-slate-700">Note for operators (optional)<textarea className={field} value={notice} onChange={e => setNotice(e.target.value)} maxLength={700} rows={3} /></label>
          <label className="block text-sm font-medium text-slate-700">Source link (optional, never opened by the system)<input className={field} value={source} onChange={e => setSource(e.target.value)} maxLength={400} /></label>
          <fieldset className="space-y-2"><legend className="mb-2 font-semibold text-slate-900">Delay areas</legend>
            {corroborated.length > 0 && <div className="flex flex-wrap items-center gap-3 text-sm text-slate-700">
              <span>{corroborated.length} area(s) confirmed by two robots.</span>
              <button type="button" className={button} disabled={busy || !originCorroborated.length} onClick={() => setSelected(originCorroborated.flatMap(([, rows]) => rows.map(r => r.id)))}>Select confirmed areas</button>
              {!originCorroborated.length && <span>Switch to one of the robots that saw them to propose a lesson.</span>}
            </div>}
            {!groups.size && <p className="text-slate-600">No delays recorded yet. Run missions with two robots through the same busy area, then come back.</p>}
            {corroborated.length > 0 && <details className="text-sm text-slate-600"><summary className="cursor-pointer">Choose areas one by one</summary><div className="mt-2 space-y-2">{corroborated.map(cell)}</div></details>}
            {selected.length > 0 && <p className="text-sm text-slate-700">{selected.length} observation(s) selected.</p>}
            {single.length > 0 && <details className="text-sm text-slate-600"><summary className="cursor-pointer">{single.length} area(s) seen by only one robot (cannot be shared yet)</summary><div className="mt-2 space-y-2">{single.map(cell)}</div></details>}
          </fieldset>
          <p className="text-sm text-slate-600">Proposed by {data?.robot_id || '…'}. Lessons expire after one hour.</p>
          <button className={button} disabled={busy || !canWrite || !selected.length || !data}>{revision ? 'Save revision (replaces the previous version)' : 'Propose lesson'}</button>
          {revision && <button className="ml-3 text-violet-700" type="button" onClick={() => setRevision(null)}>Cancel revision</button>}
        </form>
      </Panel>
      <Panel title="Lessons" subtitle="Each version is reviewed on its own. A revision needs a fresh approval.">
        {!currentLessons.length && <p className="text-slate-600">No current lessons. Propose one from confirmed delay areas.</p>}
        <div className="space-y-4">{currentLessons.map(renderLesson)}</div>
        {pastLessons.length > 0 && <details className="mt-4 text-sm text-slate-600"><summary className="cursor-pointer">{pastLessons.length} expired or withdrawn lesson(s)</summary><div className="mt-3 space-y-4">{pastLessons.map(renderLesson)}</div></details>}
      </Panel>
    </div>
  </Page>;
}
