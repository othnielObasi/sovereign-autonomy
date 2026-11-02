"use client";
import { Empty, KV, Mono, Panel, Pill } from "@/components/ui";

export function LearningEvidence({ decisions = [], changes = [], context, security }: {
  decisions?: any[]; changes?: any[]; context?: any; security?: any;
}) {
  return <Panel title="Experience and environment" subtitle="Past experience is advisory. Current conditions decide whether it can be reused.">
    <p className="text-xs text-mc-mute mb-3">Shared routing requires two distinct robot identities. Repeated missions from one robot count as one source.</p>
    {security?.integrity_error && <p role="alert" className="text-sm text-red-300 mb-3">Experience integrity check failed. Learning is disabled until an operator investigates.</p>}
    {security?.source_quarantine?.length > 0 && <div className="text-xs text-amber-300 mb-3" data-testid="source-quarantine">{security.source_quarantine.map((s: any) => <p key={s.id}>Learning quarantined for {s.source_robot_id}: repeated observations disagree with two peers. This is an anomaly flag, not proof of maliciousness.</p>)}</div>}
    {context && <div className="mb-3 text-xs"><KV k="Site" v={context.site_id} mono /><KV k="Map version" v={String(context.map_version || "").slice(0, 12)} mono /></div>}
    <div className="flex gap-2 mb-3"><Pill tone="ok">{decisions.filter(d => d.status === "accepted").length} eligible</Pill><Pill tone="warn">{decisions.filter(d => d.status === "advisory").length} advisory</Pill><Pill tone="warn">{decisions.filter(d => d.status === "excluded").length} excluded</Pill></div>
    {decisions.length === 0 ? <Empty title="No experience considered yet">A mission records which signed experiences its route considered.</Empty> :
      <details open><summary className="text-xs cursor-pointer mb-2">Experience checks</summary><div className="space-y-2 max-h-72 overflow-y-auto" data-testid="experience-checks">
        {decisions.slice(-20).map((d, i) => <div key={d.id || i} className="rounded border border-mc-line p-2 text-xs">
          <div className="flex flex-wrap items-center gap-2"><Pill tone={d.status === "accepted" ? "ok" : "warn"}>{d.status === "accepted" ? "Eligible" : d.status === "advisory" ? "Advisory" : "Excluded"}</Pill><span>{d.source_robot_id || "Unknown source"}</span><span className="text-mc-dim">{Math.round(d.age_s || 0)} s old</span></div>
          <div className="mt-1 break-all"><Mono>{d.id}</Mono></div><div className="text-mc-mute mt-1">{d.reason ? d.reason.replace(/_/g, " ") : "Context and freshness checks passed"}</div>
        </div>)}</div></details>}
    <div className="mt-4 border-t border-mc-line pt-3"><h3 className="text-xs font-semibold mb-2">Environment changes</h3>
      {changes.length === 0 ? <p className="text-xs text-mc-dim">No environment changes recorded.</p> : <div className="space-y-2" data-testid="environment-changes">{changes.slice(0, 10).map((c, i) =>
        <div key={c.id || i} className="text-xs rounded border border-mc-line p-2"><div className="font-semibold">{String(c.reason || c.action || "Environment changed").replace(/_/g, " ")}</div>
          <div className="text-mc-mute break-all mt-1">{String(c.previous?.map_version || c.previous?.context?.map_version || "unknown").slice(0, 12)} → {String(c.current?.map_version || c.current?.context?.map_version || "unknown").slice(0, 12)}</div>
          {c.action && <div className="mt-1">{c.action === "replanned" ? "Old plan discarded; replacement route ready" : "Holding: no valid route"}</div>}
          {c.propagation_ms != null && <div className="text-mc-dim mt-1">Observed after {Math.round(c.propagation_ms)} ms</div>}
        </div>)}</div>}
    </div>
  </Panel>;
}
