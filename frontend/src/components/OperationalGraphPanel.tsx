"use client";

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { getKnowledgeStatus, getKnowledgeRun, listRuns, syncKnowledge } from '@/lib/api';
import { Button, Empty, Notice, Panel, Pill } from '@/components/ui';

type Fact = { event_id: string; run_id: string; robot_id: string; x: number; y: number;
  decision: string; policy_hits: string[]; context: { site_id: string }; receipt_id: number };

export function OperationalGraphPanel() {
  const [status, setStatus] = useState<any>(null);
  const [runs, setRuns] = useState<any[]>([]);
  const [selected, setSelected] = useState('');
  const [history, setHistory] = useState<{ facts: Fact[]; excluded: number } | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    Promise.all([getKnowledgeStatus(), listRuns()]).then(([s, r]) => {
      if (!active) return;
      setStatus(s);
      const terminal = r.filter((run: any) => ['completed', 'stopped', 'failed', 'failed_safety'].includes(run.status));
      setRuns(terminal);
      setSelected(value => value || terminal[0]?.id || '');
    }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [revision]);
  useEffect(() => {
    let active = true;
    setHistory(null);
    if (selected && status?.state === 'connected') {
      getKnowledgeRun(selected).then(result => { if (active) { setHistory(result); setError(''); } })
        .catch(e => { if (active) setError(e.message); });
    }
    return () => { active = false; };
  }, [selected, status, revision]);

  async function sync() {
    setBusy(true); setError('');
    try { await syncKnowledge(selected || undefined); setRevision(v => v + 1); }
    catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  }
  const connected = status?.state === 'connected';
  return <Panel title="Operational knowledge graph" subtitle="Explore how robot missions, decisions, locations and policies connect"
    actions={<Pill tone={connected ? 'ok' : 'neutral'}>{!status ? 'Checking' : connected ? 'Memgraph connected' : status.state === 'disabled' ? 'Memgraph disabled' : 'Memgraph unavailable'}</Pill>}>
    <p className="text-sm text-mc-mute mb-3">NetworkX calculates routes. Memgraph connects historical evidence; every displayed decision is rechecked against the original signed record.</p>
    {error && <Notice tone="stop">{error}</Notice>}
    {status?.state === 'disabled' && <Notice>Enable Memgraph in the backend configuration to explore mission relationships. Existing routing and execution remain available.</Notice>}
    {status?.enabled && <>
      <div className="flex flex-wrap gap-3 items-end my-3">
        <label className="text-sm text-mc-mute flex-1 min-w-0">Recorded mission run
          <select aria-label="Knowledge graph run" value={selected} onChange={e => setSelected(e.target.value)}
            className="mt-1 block w-full rounded-lg border border-mc-line bg-mc-panel p-2 text-mc-ink">
            {!runs.length && <option value="">No finished runs</option>}
            {runs.map(run => <option key={run.id} value={run.id}>{run.id} · {run.status}</option>)}
          </select>
        </label>
        <Button onClick={sync} disabled={busy}>{busy ? 'Syncing…' : 'Sync evidence'}</Button>
      </div>
      <div className="text-xs text-mc-dim mb-3">{status.runs ?? '—'} projected runs · {status.decisions ?? '—'} decision references · latest 30 matching observations shown</div>
      <div aria-label="Knowledge graph relationships" className="flex flex-wrap gap-2 text-xs text-mc-mute mb-3">
        {['Robot → Run', 'Run → Decision', 'Decision → Location', 'Decision → Policy'].map(label => <span key={label} className="rounded border border-mc-line px-2 py-1">{label}</span>)}
      </div>
      {history && !history.facts.length && <Empty title="No verified graph evidence for this run">Sync the run to project eligible signed decisions. Older, unsigned or invalid evidence is excluded.</Empty>}
      {!!history?.facts.length && <details className="rounded-lg border border-mc-line p-3">
        <summary className="cursor-pointer text-sm text-mc-ink">View {history.facts.length} verified decision connections</summary>
        <div className="overflow-auto max-h-96 mt-3">
        <table className="w-full text-left text-sm"><caption className="text-left text-xs text-mc-dim pb-2">Historical sample for investigation and planning context. It grants no execution permission.</caption>
          <thead className="text-mc-mute"><tr><th className="py-2">Robot / location</th><th>Decision / policies</th><th>Evidence</th></tr></thead>
          <tbody>{history.facts.map(f => <tr key={f.event_id} className="border-t border-mc-line text-mc-ink">
            <td className="py-2 pr-3">{f.robot_id}<div className="text-xs text-mc-mute">{f.context.site_id} · ({f.x.toFixed(1)}, {f.y.toFixed(1)})</div></td>
            <td className="pr-3">{f.decision}<div className="text-xs text-mc-mute">{f.policy_hits.join(', ') || 'No policy hits'}</div></td>
            <td><Link className="text-mc-accent underline" href={`/runs/${f.run_id}`}>{f.event_id}</Link><div className="text-xs text-mc-mute">Signed receipt {f.receipt_id}</div></td>
          </tr>)}</tbody>
        </table>
        </div>
      </details>}
      {!!history?.excluded && <p className="text-xs text-mc-mute mt-2">{history.excluded} stale or invalid graph references excluded.</p>}
    </>}
  </Panel>;
}
