"use client";
import { Empty, KV, Panel, Pill } from "@/components/ui";

export function LearningEvidence({ decisions = [], changes = [], context, security }: {
  decisions?: any[]; changes?: any[]; context?: any; security?: any;
}) {
  const ver = (v: any) => String(v?.map_version || v?.context?.map_version || "").slice(0, 12);
  const grouped: { c: any; n: number }[] = [];
  for (const c of changes) {
    const last = grouped[grouped.length - 1];
    const same = last && (last.c.reason || last.c.action) === (c.reason || c.action) && ver(last.c.previous) === ver(c.previous) && ver(last.c.current) === ver(c.current);
    if (same) last.n += 1; else grouped.push({ c, n: 1 });
  }
  return <Panel id="learning-evidence" title="What robots learned" subtitle="Past experience is only a hint. Current conditions decide whether it is reused.">
    <p className="text-xs text-mc-mute mb-3">Robots record delays automatically. A lesson changes routing only after it is evaluated, approved and released. Many missions by one robot count as one source.</p>
    {security?.integrity_error && <p role="alert" className="text-sm text-red-300 mb-3">Experience integrity check failed. Learning is disabled until an operator investigates.</p>}
    {security?.source_quarantine?.length > 0 && <div className="text-xs text-amber-300 mb-3" data-testid="source-quarantine">{security.source_quarantine.map((s: any) => <p key={s.id}>Learning quarantined for {s.source_robot_id}: repeated observations disagree with two peers. This is an anomaly flag, not proof of maliciousness.</p>)}</div>}
    {context && <div className="mb-3 text-xs"><KV k="Site" v={context.site_id} mono /></div>}
    <div className="flex gap-2 mb-3"><Pill tone="ok">{decisions.filter(d => d.status === "accepted").length} used</Pill><Pill tone="warn">{decisions.filter(d => d.status === "advisory").length} hints only</Pill><Pill tone="warn">{decisions.filter(d => d.status === "excluded").length} set aside</Pill></div>
    {decisions.length === 0 ? <Empty title="No experience considered yet">A mission records which signed experiences its route considered.</Empty> :
      <details><summary className="text-xs cursor-pointer mb-2">Show each check ({decisions.length})</summary><div className="space-y-2 max-h-72 overflow-y-auto" data-testid="experience-checks">
        {decisions.slice(-20).map((d, i) => <div key={d.id || i} className="rounded border border-mc-line p-2 text-xs">
          <div className="flex flex-wrap items-center gap-2"><Pill tone={d.status === "accepted" ? "ok" : "warn"}>{d.status === "accepted" ? "Used" : d.status === "advisory" ? "Hint only" : "Set aside"}</Pill><span>{d.source_robot_id || "Unknown source"}</span><span className="text-mc-dim">{Math.round(d.age_s || 0)} s old</span></div>
          <div className="text-mc-mute mt-1" title={d.id}>{d.reason ? d.reason.replace(/_/g, " ") : "Context and freshness checks passed"}</div>
        </div>)}</div></details>}
    <div className="mt-4 border-t border-mc-line pt-3"><h3 className="text-xs font-semibold mb-2">Site changes</h3>
      {changes.length === 0 ? <p className="text-xs text-mc-dim">No site changes recorded.</p> : <div className="space-y-2" data-testid="environment-changes">{grouped.slice(0, 5).map(({ c, n }, i) =>
        <div key={c.id || i} className="text-xs rounded border border-mc-line p-2"><div className="font-semibold">{String(c.reason || c.action || "Site changed").replace(/_/g, " ")}{n > 1 && <span className="ml-2 font-normal text-mc-dim">×{n}</span>}</div>
          {ver(c.previous) !== ver(c.current) && <div className="text-mc-mute mt-1">Map updated, so older lessons were re-checked</div>}
          {c.action && <div className="mt-1">{c.action === "replanned" ? "Old plan discarded; replacement route ready" : "Holding: no valid route"}</div>}
          {c.propagation_ms != null && <div className="text-mc-dim mt-1">Observed after {Math.round(c.propagation_ms)} ms</div>}
        </div>)}</div>}
    </div>
  </Panel>;
}
