"use client";

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  checkCrossRunIntegrity, getBenchmarks, getDecisionStats, getReceipts, getScoreTrends, getSigningKey,
  listRuns, verifyAuditChain, verifyReceipt,
} from "@/lib/api";
import { EvidenceNav } from "@/components/EvidenceNav";
import { Bar, Button, Empty, KV, Mono, Notice, Page, PageHeader, Panel, Pill, Stat, Tabs, Verdict, cx } from "@/components/ui";

type Arm = Record<string, number | null>;
type Suite = {
  id: string; title: string; summary: string; planner: string; rounds: number; seeds_per_round: number;
  generated_at: string; wall_time_s: number; execution: string; source_commit?: string;
  totals: Record<string, Arm>; rounds_detail: Array<{ round: number; lessons_available: number; arms: Record<string, Arm> }>;
  model_usage?: { by_model?: Array<any> };
};

const ARMS: Array<{ id: string; label: string }> = [
  { id: "ungoverned", label: "No gate" },
  { id: "governed", label: "Gate" },
  { id: "learning", label: "Gate + learning" },
];

const pct = (v: number | null | undefined) => (v == null ? "—" : `${(v * 100).toFixed(v < 0.1 && v > 0 ? 1 : 0)}%`);
const num = (v: number | null | undefined) => (v == null ? "—" : v.toLocaleString());

export default function EvidencePage() {
  type TabId = "bench" | "receipts" | "ops";
  const [tab, setTabState] = useState<TabId>("bench");
  const setTab = (id: string) => setTabState(id as TabId);
  return (
    <Page wide>
      <PageHeader eyebrow="Evidence" title="What the gate prevented, and how to check it"
        subtitle="Benchmark results committed with the code, signed decision receipts you can verify, and the hash-chained audit trail." />
      <EvidenceNav />
      <Tabs variant="segmented" className="mb-5" value={tab} onChange={setTab}
        tabs={[{ id: "bench", label: "Safety benchmarks" }, { id: "receipts", label: "Receipts & chain" }, { id: "ops", label: "Run quality" }]} />
      {tab === "bench" && <Benchmarks />}
      {tab === "receipts" && <Receipts />}
      {tab === "ops" && <Operations />}
    </Page>
  );
}

/* ── Benchmarks ─────────────────────────────────────────────────────────── */

function Benchmarks() {
  const [suites, setSuites] = useState<Suite[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { getBenchmarks().then((d) => setSuites(d.suites || [])).catch((e) => setErr(e.message)); }, []);
  if (err) return <Notice tone="stop">{err}</Notice>;
  if (!suites) return <div className="text-sm text-mc-dim">Loading benchmark results…</div>;
  const order = ["nemotron", "rule_based", "reckless"];
  return (
    <div className="space-y-6">
      <Notice tone="info">
        A move is labelled unsafe by fixed safety floors in code, not by the rules under test. Person contacts are physical
        (bodies within 0.7 m while the robot moves); &ldquo;while braking&rdquo; means the gate had already told the robot to stop.
      </Notice>
      {order.map((id) => suites.find((s) => s.id === id)).filter(Boolean).map((s) => <SuiteCard key={s!.id} s={s!} />)}
    </div>
  );
}

function SuiteCard({ s }: { s: Suite }) {
  const t = s.totals;
  const maxUnsafe = Math.max(1, ...ARMS.map((a) => Number(t[a.id]?.unsafe_executed || 0)));
  const ultra = s.model_usage?.by_model?.find((m: any) => String(m.model).includes("Ultra"));
  const last = s.rounds_detail?.[s.rounds_detail.length - 1];
  return (
    <Panel
      title={s.title}
      subtitle={`${s.summary}${s.generated_at ? ` · ${s.generated_at}` : ""}`}
      actions={
        <div className="flex flex-wrap gap-1.5 justify-end">
          {s.execution === "nebius-serverless-job" && <Pill tone="accent">Nebius Serverless Job</Pill>}
          {s.planner === "nemotron" && <Pill tone="nv">NVIDIA Nemotron</Pill>}
          {s.source_commit && <Pill><Mono className="text-mc-mute">{s.source_commit.slice(0, 7)}</Mono></Pill>}
        </div>
      }>
      <div className="grid lg:grid-cols-5 gap-5">
        {/* headline: unsafe executed */}
        <div className="lg:col-span-2 space-y-3">
          <div className="text-xs font-semibold uppercase tracking-[0.12em] text-mc-dim">Unsafe moves executed</div>
          {ARMS.map((a) => {
            const v = Number(t[a.id]?.unsafe_executed ?? 0);
            return (
              <div key={a.id}>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-mc-mute">{a.label}</span>
                  <span className={cx("font-semibold tabular", a.id === "ungoverned" ? "text-mc-stop" : "text-mc-ok")}>{num(v)}</span>
                </div>
                <Bar value={v} max={maxUnsafe} tone={a.id === "ungoverned" ? "stop" : "ok"} />
              </div>
            );
          })}
          {ultra && (
            <div className="text-xs text-mc-mute pt-1">
              <span className="text-mc-nv">{ultra.ok}/{ultra.calls}</span> Nemotron Ultra calls succeeded · p50 {(ultra.p50_latency_ms / 1000).toFixed(1)} s
              {s.wall_time_s ? ` · ${Math.round(s.wall_time_s / 60)} min` : ""}
            </div>
          )}
        </div>

        {/* full table */}
        <div className="lg:col-span-3 overflow-x-auto mc-scroll">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[11px] uppercase tracking-wider text-mc-dim">
                <th className="text-left font-semibold py-1.5 pr-3">Measure</th>
                {ARMS.map((a) => <th key={a.id} className="text-right font-semibold py-1.5 px-2">{a.label}</th>)}
              </tr>
            </thead>
            <tbody className="tabular">
              <Tr label="Missions" vals={ARMS.map((a) => num(t[a.id]?.scenarios))} />
              <Tr label="Unsafe proposed (per 100 moves)" vals={ARMS.map((a) => `${num(t[a.id]?.unsafe_proposed)} (${t[a.id]?.unsafe_proposed_per_100_moves ?? "—"})`)} />
              <Tr label="Person contacts (while braking)" vals={ARMS.map((a) => `${num(t[a.id]?.person_contacts)} (${num(t[a.id]?.person_contacts_while_braking)})`)} />
              <Tr label="Rack / obstacle contacts" vals={ARMS.map((a) => num(t[a.id]?.structure_contacts))} />
              <Tr label="Missions completed" vals={ARMS.map((a) => pct(t[a.id]?.completion_rate))} />
              <Tr label="Safe moves wrongly blocked" vals={ARMS.map((a) => (a.id === "ungoverned" ? "—" : pct(t[a.id]?.false_block_rate)))} />
              <Tr label="Mean time to goal" vals={ARMS.map((a) => (t[a.id]?.mean_time_to_goal_s == null ? "—" : `${Number(t[a.id]?.mean_time_to_goal_s).toFixed(1)} s`))} />
            </tbody>
          </table>
          {last && s.rounds_detail.length > 1 && (
            <div className="mt-3 text-xs text-mc-mute">
              Round {last.round}, with {last.lessons_available} lessons from earlier rounds: unsafe proposals per 100 moves{" "}
              <span className="text-mc-ink">{last.arms.governed?.unsafe_proposed_per_100_moves ?? "—"}</span> with the gate alone vs{" "}
              <span className="text-mc-ok">{last.arms.learning?.unsafe_proposed_per_100_moves ?? "—"}</span> with learning.
            </div>
          )}
        </div>
      </div>
    </Panel>
  );
}

function Tr({ label, vals }: { label: string; vals: React.ReactNode[] }) {
  return (
    <tr className="border-t border-mc-line/70">
      <td className="py-1.5 pr-3 text-mc-mute">{label}</td>
      {vals.map((v, i) => <td key={i} className="py-1.5 px-2 text-right">{v}</td>)}
    </tr>
  );
}

/* ── Receipts & chain ───────────────────────────────────────────────────── */

function Receipts() {
  const [runs, setRuns] = useState<any[]>([]);
  const [runId, setRunId] = useState<string>("");
  const [receipts, setReceipts] = useState<any[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [chain, setChain] = useState<any>(null);
  const [key, setKey] = useState<any>(null);
  const [checks, setChecks] = useState<Record<string, any>>({});

  useEffect(() => {
    listRuns().then((d: any) => {
      const list = (Array.isArray(d) ? d : d.runs || []).sort((a: any, b: any) => (b.started_at || "").localeCompare(a.started_at || ""));
      setRuns(list);
      if (list[0]) setRunId(list[0].id);
    }).catch(() => {});
    getSigningKey().then(setKey).catch(() => {});
  }, []);

  useEffect(() => {
    if (!runId) return;
    setReceipts([]); setStats(null); setChain(null); setChecks({});
    getReceipts(runId).then((d: any) => setReceipts(Array.isArray(d) ? d : d.receipts || [])).catch(() => {});
    getDecisionStats(runId).then(setStats).catch(() => {});
    verifyAuditChain(runId).then(setChain).catch(() => {});
  }, [runId]);

  async function check(id: string) {
    setChecks((c) => ({ ...c, [id]: { pending: true } }));
    try { const r = await verifyReceipt(runId, id); setChecks((c) => ({ ...c, [id]: r })); }
    catch (e: any) { setChecks((c) => ({ ...c, [id]: { valid: false, reason: e.message } })); }
  }

  if (!runs.length) return <Empty title="No runs yet">Run a mission in the live warehouse to produce receipts.</Empty>;

  return (
    <div className="grid lg:grid-cols-3 gap-4">
      <div className="space-y-4">
        <Panel title="Run">
          <label className="block text-xs text-mc-dim mb-1" htmlFor="ev-run">Choose a run</label>
          <select id="ev-run" value={runId} onChange={(e) => setRunId(e.target.value)}
            className="w-full rounded-lg bg-mc-raise border border-mc-line2 px-3 py-2 text-sm font-mono">
            {runs.map((r) => <option key={r.id} value={r.id}>{r.id} · {r.status}</option>)}
          </select>
          <div className="mt-3">
            <Button variant="ghost" href={`/runs/${runId}`} className="px-0">Open run →</Button>
          </div>
        </Panel>
        <Panel title="Hash chain">
          {!chain ? <div className="text-xs text-mc-dim">Verifying…</div> : (
            <>
              <div className="mb-2"><Verdict value={chain.chain_valid ? "VALID" : "INVALID"} /></div>
              <KV k="Entries" v={chain.total_entries} />
              <KV k="First hash" v={chain.first_hash} mono />
              <KV k="Last hash" v={chain.last_hash} mono />
            </>
          )}
        </Panel>
        <Panel title="Decisions">
          {!stats ? <div className="text-xs text-mc-dim">Loading…</div> : (
            <>
              <KV k="Total" v={stats.total} />
              <KV k="Approved" v={<span className="text-mc-ok">{stats.approved}</span>} />
              <KV k="Denied" v={<span className="text-mc-stop">{stats.denied}</span>} />
              <KV k="Needs review" v={<span className="text-mc-warn">{stats.needs_review}</span>} />
              <KV k="Max risk" v={stats.max_risk_score?.toFixed?.(2)} />
            </>
          )}
        </Panel>
        {key && (
          <Panel title="Signing key">
            <KV k="Algorithm" v={key.algorithm} />
            <KV k="Key id" v={key.key_id} mono />
            <div className="mt-2 text-[11px] font-mono text-mc-dim break-all">{key.public_key_b64}</div>
          </Panel>
        )}
      </div>

      <Panel className="lg:col-span-2" title="Signed decision receipts"
        subtitle="Each receipt holds what was proposed, what the gate saw, the rules version and the outcome, signed with Ed25519."
        padded={false}>
        {receipts.length === 0 ? <Empty title="No receipts for this run" /> : (
          <ul className="divide-y divide-mc-line max-h-[640px] overflow-y-auto mc-scroll">
            {receipts.slice(0, 60).map((r) => {
              const id = String(r.receipt_id);
              const c = checks[id];
              const hits: string[] = r.policy_evaluation?.policies_triggered || [];
              return (
                <li key={id} className="px-4 py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Verdict value={r.verdict?.decision} />
                    <span className="text-xs text-mc-mute">{r.proposal?.intent}
                      {r.proposal?.params?.x != null && <> → ({Number(r.proposal.params.x).toFixed(1)}, {Number(r.proposal.params.y).toFixed(1)}) at {r.proposal.params.max_speed} m/s</>}
                    </span>
                    <span className="ml-auto text-[11px] text-mc-dim tabular">#{id} · {r.timestamp ? new Date(r.timestamp).toLocaleTimeString() : ""}</span>
                  </div>
                  {hits.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1">{hits.map((h) => <Pill key={h} tone="stop">{h}</Pill>)}</div>
                  )}
                  <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px]">
                    <span className="text-mc-dim">rules <Mono className="text-mc-mute">{r.integrity?.policy_version}</Mono></span>
                    <span className="text-mc-dim">hash <Mono className="text-mc-mute">{String(r.integrity?.event_hash || "").slice(7, 19)}…</Mono></span>
                    {r.integrity?.signature ? (
                      c?.pending ? <span className="text-mc-dim">checking…</span>
                        : c ? <Pill tone={c.valid ? "ok" : "stop"} dot>{c.valid ? "Signature valid" : `Invalid: ${c.reason}`}</Pill>
                          : <button onClick={() => check(id)} className="text-mc-accent hover:underline">Verify signature</button>
                    ) : <span className="text-mc-dim">unsigned</span>}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </Panel>
    </div>
  );
}

/* ── Run quality ───────────────────────────────────────────────────────── */

function Operations() {
  const [trends, setTrends] = useState<any[]>([]);
  const [integrity, setIntegrity] = useState<any>(null);
  useEffect(() => {
    getScoreTrends(20).then((d: any) => setTrends(d.trends || [])).catch(() => {});
    checkCrossRunIntegrity().then(setIntegrity).catch(() => {});
  }, []);
  const scored = useMemo(() => (integrity?.per_run_summary || []).filter((r: any) => r.scores), [integrity]);
  return (
    <div className="grid lg:grid-cols-3 gap-4">
      <Panel className="lg:col-span-2" title="Run scores" subtitle="Safety, compliance, mission success, efficiency and smoothness per run">
        {scored.length === 0 ? <Empty title="No scored runs yet">Scores appear when runs finish.</Empty> : (
          <div className="overflow-x-auto mc-scroll">
            <table className="w-full text-sm tabular">
              <thead><tr className="text-[11px] uppercase tracking-wider text-mc-dim">
                <th className="text-left py-1.5">Run</th>
                {["safety", "compliance", "mission_success", "efficiency", "smoothness", "composite"].map((k) => <th key={k} className="text-right px-2">{k.replace("_", " ")}</th>)}
              </tr></thead>
              <tbody>
                {scored.map((r: any) => (
                  <tr key={r.run_id} className="border-t border-mc-line/70">
                    <td className="py-1.5"><Link href={`/runs/${r.run_id}`} className="hover:underline"><Mono>{r.run_id}</Mono></Link></td>
                    {["safety", "compliance", "mission_success", "efficiency", "smoothness", "composite"].map((k) => {
                      const v = r.scores[k];
                      return <td key={k} className={cx("text-right px-2", v >= 0.75 ? "text-mc-ok" : v >= 0.5 ? "text-mc-warn" : "text-mc-stop")}>{v == null ? "—" : (v * 100).toFixed(0)}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      <div className="space-y-4">
        <Stat label="Cross-run integrity" tone={integrity?.status === "ok" ? "ok" : integrity ? "warn" : "neutral"}
          value={integrity ? (integrity.status === "ok" ? "Clean" : integrity.status) : "…"}
          hint={integrity ? `${integrity.runs_checked} runs checked · ${(integrity.cross_run_flags || []).length} flags` : "Checking for gaming across runs"} />
        <Stat label="Runs with scores" value={trends.length} hint="Most recent 20 runs" />
      </div>
    </div>
  );
}
