"use client";

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { getBenchmarks, getLearningSummary, getLlmModels, getPerceptionStatus, listRuns } from "@/lib/api";
import { Button, Mono, Page, Panel, Pill, Stat, Verdict, cx } from "@/components/ui";

type Suite = { id: string; title: string; execution: string; totals: Record<string, any>; model_usage?: any };
type Run = { id: string; mission_id: string; status: string; started_at: string; ended_at?: string | null };

const fmt = (n: number | null | undefined) => (n == null ? "—" : n.toLocaleString());

const STEPS = [
  { n: "01", title: "Propose", who: "NVIDIA Nemotron 3 Ultra", text: "Plans the mission and replans after a denial. Fast Nemotron models handle per-step calls. Every output is only a proposal." },
  { n: "02", title: "Decide", who: "Deterministic gate · 11 policies", text: "Geofence, zone speed, people and vehicles, racking, hazard zones, perception confidence, operator escalation. No model in the loop." },
  { n: "03", title: "Execute or stop", who: "Robot / simulator", text: "Only approved moves run. Every denial sends STOP, so the robot never continues toward an old target." },
  { n: "04", title: "Prove", who: "Hash chain + Ed25519", text: "Every decision is chained and signed with the rules version it was judged under. Anyone can verify it later." },
];

const UNTRUSTED = [
  { title: "Model plans", text: "Only proposals; every move is judged." },
  { title: "Vision", text: "Cross-checked; can only slow the robot." },
  { title: "The web", text: "Screened; can only tighten hazard zones." },
  { title: "Lessons", text: "From the gate only; never change the rules." },
];

export default function OverviewPage() {
  const [suites, setSuites] = useState<Suite[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [models, setModels] = useState<any>(null);
  const [vision, setVision] = useState<any>(null);
  const [learning, setLearning] = useState<any>(null);

  useEffect(() => {
    getBenchmarks().then((d) => setSuites(d.suites || [])).catch(() => {});
    getLlmModels().then(setModels).catch(() => {});
    getPerceptionStatus().then(setVision).catch(() => {});
    getLearningSummary().then(setLearning).catch(() => {});
    const loadRuns = () => listRuns().then((d: any) => setRuns(Array.isArray(d) ? d : d.runs || [])).catch(() => {});
    loadRuns();
    const id = setInterval(loadRuns, 10000);
    return () => clearInterval(id);
  }, []);

  const nemo = suites.find((s) => s.id === "nemotron");
  const lastRound: any = (nemo as any)?.rounds_detail?.[(nemo as any)?.rounds_detail?.length - 1];
  const latestEnded = runs.filter((r) => ["stopped", "completed"].includes(r.status))
    .sort((a, b) => (b.started_at || "").localeCompare(a.started_at || ""))[0];
  const rule = suites.find((s) => s.id === "rule_based");
  const ultra = nemo?.model_usage?.by_model?.find((m: any) => String(m.model).includes("Ultra"));
  const active = runs.find((r) => ["running", "planning", "paused"].includes(r.status));
  const recent = useMemo(() => [...runs].sort((a, b) => (b.started_at || "").localeCompare(a.started_at || "")).slice(0, 6), [runs]);

  return (
    <div className="mc-grid-bg">
      <Page wide>
        {/* ── Hero ─────────────────────────────────────────────────────── */}
        <section className="grid lg:grid-cols-5 gap-8 items-center pt-4 pb-10">
          <div className="lg:col-span-3">
            <div className="flex flex-wrap gap-2 mb-4">
              <Pill tone="nv">NVIDIA Nemotron</Pill>
              <Pill tone="accent">Nebius Token Factory · AI Cloud</Pill>
              <Pill>Physical AI</Pill>
            </div>
            <h1 className="text-4xl sm:text-5xl font-semibold tracking-tight leading-[1.05]">
              Every robot move,<br /><span className="text-mc-accent">proven safe</span> before it happens.
            </h1>
            <p className="mt-5 text-base sm:text-lg text-mc-mute max-w-2xl leading-relaxed">
              An NVIDIA Nemotron planner proposes. A deterministic governance gate decides. Every decision leaves a signed,
              hash-chained receipt. The AI can be brilliant or wrong; the robot only ever does what the rules allow.
            </p>
            <div className="mt-7 flex flex-wrap gap-3">
              <Button variant="primary" href={active ? `/runs/${active.id}` : "/twin"} className="px-5 py-2.5">
                {active ? "Watch the mission in progress" : "Open the live warehouse"}
              </Button>
              <Button href="/demo" className="px-5 py-2.5">Guided demo</Button>
              <Button variant="ghost" href="/evidence">See the evidence →</Button>
            </div>
            {active && (
              <div className="mt-4 text-xs text-mc-mute">
                <span className="text-mc-accent">●</span> A mission is running now: <Link className="text-mc-accent hover:underline" href={`/runs/${active.id}`}><Mono>{active.id}</Mono></Link>.
                The demo robot is shared, so one mission runs at a time.
              </div>
            )}
          </div>

          {/* Proof */}
          <div className="lg:col-span-2 grid grid-cols-2 gap-3">
            <Stat className="col-span-2" label="Unsafe moves executed · Nemotron planner"
              value={<span>{fmt(nemo?.totals?.ungoverned?.unsafe_executed)} <span className="text-mc-dim text-lg">→</span> <span className="text-mc-ok">{fmt(nemo?.totals?.governed?.unsafe_executed)}</span></span>}
              hint={nemo ? "Without the gate → with it. 20 seeded missions per arm, run on Nebius Serverless Jobs." : "Loading benchmark…"} />
            <Stat label="Rule-based planner" tone="ok"
              value={<span><span className="text-mc-ink">{fmt(rule?.totals?.ungoverned?.unsafe_executed)}</span> <span className="text-mc-dim text-base">→</span> {fmt(rule?.totals?.governed?.unsafe_executed)}</span>}
              hint="150 missions per arm" />
            <Stat label="Ultra calls on Token Factory" tone="nv"
              value={ultra ? `${ultra.ok}/${ultra.calls}` : "—"} hint={ultra ? `p50 ${(ultra.p50_latency_ms / 1000).toFixed(1)} s · benchmark run` : "benchmark run"} />
          </div>
        </section>

        {/* ── How it works ─────────────────────────────────────────────── */}
        <section className="mb-10">
          <h2 className="text-[13px] font-semibold uppercase tracking-[0.12em] text-mc-dim mb-3">How it works</h2>
          <div className="grid md:grid-cols-2 xl:grid-cols-4 gap-3">
            {STEPS.map((s, i) => (
              <div key={s.n} className="relative rounded-xl border border-mc-line bg-mc-panel p-4">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs text-mc-accent">{s.n}</span>
                  {i < 3 && <span className="hidden xl:block absolute -right-2.5 top-1/2 -translate-y-1/2 text-mc-line2 z-10">▸</span>}
                </div>
                <div className="mt-2 text-lg font-semibold">{s.title}</div>
                <div className={cx("text-xs font-medium mt-0.5", i === 0 ? "text-mc-nv" : "text-mc-accent")}>{s.who}</div>
                <p className="mt-2 text-sm text-mc-mute leading-relaxed">{s.text}</p>
              </div>
            ))}
          </div>
        </section>

        {/* ── Learns from the gate, stays on task ───────────────────────── */}
        <section className="mb-10">
          <h2 className="text-[13px] font-semibold uppercase tracking-[0.12em] text-mc-dim mb-3">It learns, and it stays on task</h2>
          <div className="grid lg:grid-cols-2 gap-4">
            <Panel title="Adaptive learning" subtitle="The planner learns from the gate. The gate never drifts.">
              <ul className="space-y-1.5 text-sm text-mc-mute mb-4">
                <li><span className="text-mc-ink">Denials become lessons</span>, by place and policy.</li>
                <li><span className="text-mc-ink">Lessons near the route</span> go to <span className="text-mc-nv">Nemotron Ultra</span> before it plans.</li>
                <li><span className="text-mc-ink">Only the gate teaches</span>; lessons never change the rules.</li>
              </ul>
              <div className="grid grid-cols-3 gap-2">
                <MiniStat label="Lessons learned" value={learning?.lessons} />
                <MiniStat label="Plans shaped by lessons" value={learning?.plans_with_lessons} />
                <MiniStat label="Unsafe proposals / 100 moves" tone="ok"
                  value={lastRound ? <>{lastRound.arms?.governed?.unsafe_proposed_per_100_moves} → {lastRound.arms?.learning?.unsafe_proposed_per_100_moves}</> : undefined}
                  hint="benchmark, round 2, with vs without lessons" />
              </div>
            </Panel>
            <Panel title="Task-drift control" subtitle="Every plan and replan is checked before the robot uses it.">
              <ul className="space-y-1.5 text-sm text-mc-mute mb-4">
                <li><span className="text-mc-ink">Must end at the mission&apos;s destination</span>, never one the model picks.</li>
                <li><span className="text-mc-ink">No wandering</span>: at most twice the aisle route.</li>
                <li><span className="text-mc-ink">A failing plan isn&apos;t used</span>; the aisle route is taken instead.</li>
              </ul>
              <div className="grid grid-cols-3 gap-2">
                <MiniStat label="Plans checked" value={learning?.task_checks} />
                <MiniStat label="Drift caught" value={learning?.drift_caught} tone={learning?.drift_caught ? "warn" : "ok"} />
                <MiniStat label="Replans after a denial" value={learning?.replans} />
              </div>
            </Panel>
          </div>
          <div className="mt-3 text-xs text-mc-dim">
            Watch it happen: open any run and the <span className="text-mc-ink">Learning &amp; task</span> tab shows the lessons Nemotron was given, every replan and every task check
            {latestEnded && <> (<Link href={`/runs/${latestEnded.id}`} className="text-mc-accent hover:underline">latest run</Link>)</>}. All lessons: <Link href="/policies" className="text-mc-accent hover:underline">Governance</Link>.
          </div>
        </section>

        <section className="grid lg:grid-cols-3 gap-4 mb-10 lg:items-start">
          {/* ── Untrusted by default ─────────────────────────────────── */}
          <Panel title="Untrusted by default" subtitle="Every outside input can add caution. None can remove it." className="lg:col-span-2">
            <div className="grid sm:grid-cols-2 gap-x-6 gap-y-3">
              {UNTRUSTED.map((u) => (
                <div key={u.title} className="flex gap-2.5">
                  <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-mc-accent shrink-0" />
                  <div><div className="text-sm font-semibold">{u.title}</div><p className="text-xs text-mc-mute">{u.text}</p></div>
                </div>
              ))}
            </div>
          </Panel>

          {/* ── Live system ─────────────────────────────────────────── */}
          <Panel title="Live system" subtitle="What is running behind this page">
            <div className="space-y-2.5 text-sm">
              <Row k="Mission planning" v={<span className="text-mc-nv">{short(models?.tiers?.reasoning)}</span>} />
              <Row k="Per-step proposals" v={<span className="text-mc-nv">{(models?.tiers?.fast || []).map(short).join(", ") || "—"}</span>} />
              <Row k="Vision cross-check" v={<span className="text-mc-nv">{vision?.enabled ? short(vision.model) : "off"}</span>} />
              <Row k="Safety gate" v="11 deterministic policies" />
              <Row k="Hosting" v="Nebius AI Cloud VM" />
              <Row k="Benchmark compute" v="Nebius Serverless Jobs" />
            </div>
          </Panel>
        </section>

        {/* ── Recent runs ──────────────────────────────────────────────── */}
        <Panel title="Recent runs" actions={<Button variant="ghost" href="/runs" className="py-1">All runs →</Button>} padded={false}>
          {recent.length === 0 ? (
            <div className="p-6 text-sm text-mc-dim text-center">No runs yet. <Link href="/twin" className="text-mc-accent hover:underline">Plan the first mission</Link>.</div>
          ) : (
            <ul className="divide-y divide-mc-line">
              {recent.map((r) => (
                <li key={r.id}>
                  <Link href={`/runs/${r.id}`} className="flex items-center justify-between gap-3 px-4 py-2.5 hover:bg-mc-raise/60">
                    <span className="flex items-center gap-3 min-w-0">
                      <Verdict value={r.status} />
                      <Mono>{r.id}</Mono>
                    </span>
                    <span className="text-xs text-mc-dim tabular">{r.started_at ? new Date(r.started_at).toLocaleString() : ""}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </Page>
    </div>
  );
}

function short(m?: string) {
  return String(m || "—").replace(/^nvidia\//, "").replace(/_/g, ".");
}

function MiniStat({ label, value, hint, tone }: { label: string; value: React.ReactNode; hint?: string; tone?: "ok" | "warn" }) {
  return (
    <div className="rounded-lg border border-mc-line bg-mc-raise/60 px-3 py-2.5">
      <div className={cx("text-xl font-semibold tabular", tone === "ok" ? "text-mc-ok" : tone === "warn" ? "text-mc-warn" : "text-mc-ink")}>{value ?? "—"}</div>
      <div className="text-[11px] text-mc-dim leading-tight mt-0.5">{label}</div>
      {hint && <div className="text-[10px] text-mc-dim/80 leading-tight mt-0.5">{hint}</div>}
    </div>
  );
}

function Row({ k, v }: { k: React.ReactNode; v: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-mc-dim text-xs">{k}</span>
      <span className="text-right text-[13px] font-medium">{v}</span>
    </div>
  );
}
