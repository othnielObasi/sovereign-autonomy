"use client";

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { getAuthorityStatus, getLearningSummary, getLlmModels, getPerceptionStatus, getRouteLearning, listRuns } from "@/lib/api";
import { Button, Mono, Page, Panel, Pill, Stat, Verdict, cx } from "@/components/ui";

type Run = { id: string; mission_id: string; status: string; started_at: string; ended_at?: string | null };

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "/api";

// "new" = built during the Meta hackathon; "earlier" = carried over from our earlier codebase
const STEPS = [
  { n: "01", title: "See and plan", who: "Muse Spark", tag: "new",
    text: "Plans each mission from the map and the robot's own camera frame, and replans after a denial. Muse Spark Open proposes each step." },
  { n: "02", title: "Perceive", who: "SAM 3.1", tag: "new",
    text: "Segments the camera frame; each detection is projected onto the floor in metres and cross-checked with the sensors. It can only add caution." },
  { n: "03", title: "Decide", who: "Deterministic gate · 11 policies", tag: "earlier",
    text: "Geofence, zone speed, people and vehicles, racking, hazard zones, perception confidence. No model in the loop." },
  { n: "04", title: "Permit", who: "Execution authority", tag: "new",
    text: "An approved move gets a signed, single-use permit for exactly that move after a full-path check. The robot controller checks it again; anything else is refused." },
  { n: "05", title: "Stop", who: "Kill switches · Muse Voice Transcribe", tag: "new",
    text: "Robot, mission, planner or everything: authority revoked in milliseconds, stop verified at the controller. Say “stop” and it stops; voice can never start it." },
];

const UNTRUSTED = [
  { title: "Model plans", text: "Only proposals; no model can issue a permit." },
  { title: "Vision", text: "Cross-checked; can only slow the robot." },
  { title: "Learning memory", text: "Signed; forged records are quarantined." },
  { title: "Hidden instructions", text: "A canary tripwire discards plans that obey them." },
];

export default function OverviewPage() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [models, setModels] = useState<any>(null);
  const [vision, setVision] = useState<any>(null);
  const [learning, setLearning] = useState<any>(null);
  const [authority, setAuthority] = useState<any>(null);
  const [routing, setRouting] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);

  useEffect(() => {
    getLlmModels().then(setModels).catch(() => {});
    getPerceptionStatus().then(setVision).catch(() => {});
    getLearningSummary().then(setLearning).catch(() => {});
    getRouteLearning().then(setRouting).catch(() => {});
    fetch(`${API_BASE}/health`, { cache: "no-store" }).then((r) => r.json()).then(setHealth).catch(() => {});
    const load = () => {
      listRuns().then((d: any) => setRuns(Array.isArray(d) ? d : d.runs || [])).catch(() => {});
      getAuthorityStatus().then(setAuthority).catch(() => {});
    };
    load();
    const id = setInterval(load, 8000);
    return () => clearInterval(id);
  }, []);

  const active = runs.find((r) => ["running", "planning", "paused"].includes(r.status));
  const latestEnded = runs.filter((r) => ["stopped", "completed"].includes(r.status))
    .sort((a, b) => (b.started_at || "").localeCompare(a.started_at || ""))[0];
  const recent = useMemo(() => [...runs].sort((a, b) => (b.started_at || "").localeCompare(a.started_at || "")).slice(0, 6), [runs]);
  const locks = authority?.kill_locks?.length || 0;
  const muse = models?.provider === "muse";

  return (
    <div className="mc-grid-bg">
      <Page wide>
        {/* ── Hero ─────────────────────────────────────────────────────── */}
        <section className="grid lg:grid-cols-5 gap-8 items-center pt-4 pb-10">
          <div className="lg:col-span-3">
            <div className="flex flex-wrap gap-2 mb-4">
              <Pill tone="accent">Muse Spark</Pill>
              <Pill tone="accent">SAM 3.1</Pill>
              <Pill tone="accent">Muse Voice Transcribe</Pill>
              <Pill>Push the Frontier</Pill>
            </div>
            <h1 className="text-4xl sm:text-5xl font-semibold tracking-tight leading-[1.05]">
              AI plans the robot&apos;s moves.<br /><span className="text-mc-accent">Nothing moves</span> without proof it was allowed.
            </h1>
            <p className="mt-5 text-base sm:text-lg text-mc-mute max-w-2xl leading-relaxed">
              Meta&apos;s models see the warehouse and plan the route. A deterministic gate judges every move, and only a signed,
              single-use permit for that exact move lets the robot act. Kill switches and a spoken “stop” revoke authority at once.
            </p>
            <div className="mt-7 flex flex-wrap gap-3">
              <Button variant="primary" href={active ? `/runs/${active.id}` : "/twin"} className="px-5 py-2.5">
                {active ? "Watch the mission in progress" : "Open the live warehouse"}
              </Button>
              <Button href="/authority" className="px-5 py-2.5">Run the security drills</Button>
              <Button variant="ghost" href="/evidence">See the evidence →</Button>
            </div>
            {active && (
              <div className="mt-4 text-xs text-mc-mute">
                <span className="text-mc-accent">●</span> A mission is running now: <Link className="text-mc-accent hover:underline" href={`/runs/${active.id}`}><Mono>{active.id}</Mono></Link>.
                The demo robot is shared, so one mission runs at a time.
              </div>
            )}
          </div>

          {/* Live proof */}
          <div className="lg:col-span-2 grid grid-cols-2 gap-3">
            <Stat className="col-span-2" label="Execution authority"
              tone={!authority ? "neutral" : !authority.enabled || locks ? "stop" : "ok"}
              value={!authority ? "…" : !authority.enabled ? "Not configured" : locks ? `Stopped · ${locks} kill switch${locks > 1 ? "es" : ""}` : "Permits enforced"}
              hint="Every move needs a single-use permit; the robot controller checks it again." />
            <Stat label="Planner" tone={muse ? "accent" : "neutral"} value={muse ? "Muse Spark" : models?.provider || "…"}
              hint={muse ? "camera + map" : "add MODEL_API_KEY"} />
            <Stat label="Quarantined memory" tone={routing?.quarantined ? "warn" : "ok"} value={routing ? routing.quarantined : "—"}
              hint={routing ? `${routing.learned_cells} learned cells` : ""} />
          </div>
        </section>

        {/* ── How it works ─────────────────────────────────────────────── */}
        <section className="mb-10">
          <h2 className="text-[13px] font-semibold uppercase tracking-[0.12em] text-mc-dim mb-3">How it works</h2>
          <div className="grid md:grid-cols-2 xl:grid-cols-5 gap-3">
            {STEPS.map((s, i) => (
              <div key={s.n} className="relative rounded-xl border border-mc-line bg-mc-panel p-4">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs text-mc-accent">{s.n}</span>
                  <Pill tone={s.tag === "new" ? "accent" : "neutral"}>{s.tag === "new" ? "New" : "Earlier work"}</Pill>
                  {i < STEPS.length - 1 && <span className="hidden xl:block absolute -right-2.5 top-1/2 -translate-y-1/2 text-mc-line2 z-10">▸</span>}
                </div>
                <div className="mt-2 text-lg font-semibold">{s.title}</div>
                <div className="text-xs font-medium mt-0.5 text-mc-accent">{s.who}</div>
                <p className="mt-2 text-sm text-mc-mute leading-relaxed">{s.text}</p>
              </div>
            ))}
          </div>
        </section>

        {/* ── Learns, and stays on task ─────────────────────────────────── */}
        <section className="mb-10">
          <h2 className="text-[13px] font-semibold uppercase tracking-[0.12em] text-mc-dim mb-3">It learns, and learning can&apos;t be poisoned</h2>
          <div className="grid lg:grid-cols-2 gap-4">
            <Panel title="Learned routing" subtitle="New · NetworkX over the warehouse floor">
              <ul className="space-y-1.5 text-sm text-mc-mute mb-4">
                <li><span className="text-mc-ink">Where the gate slowed or stopped the robot</span>, the route learns to expect a delay.</li>
                <li><span className="text-mc-ink">Racking and hazard zones are hard limits</span> that learning can never open.</li>
                <li><span className="text-mc-ink">Every record is signed</span>; a planted or edited one is quarantined.</li>
              </ul>
              <div className="grid grid-cols-3 gap-2">
                <MiniStat label="Router" value={routing?.last_route?.router || "—"} />
                <MiniStat label="Learned cells" value={routing?.learned_cells} />
                <MiniStat label="Quarantined" value={routing?.quarantined} tone={routing?.quarantined ? "warn" : "ok"} />
              </div>
            </Panel>
            <Panel title="Lessons and task-drift control" subtitle="Earlier work · now feeding Muse Spark">
              <ul className="space-y-1.5 text-sm text-mc-mute mb-4">
                <li><span className="text-mc-ink">Denials become lessons</span>, given to the planner before it plans.</li>
                <li><span className="text-mc-ink">Every plan must end at the mission&apos;s destination</span> and stay near the aisle route.</li>
                <li><span className="text-mc-ink">A failing plan isn&apos;t used</span>; the aisle route is taken instead.</li>
              </ul>
              <div className="grid grid-cols-3 gap-2">
                <MiniStat label="Lessons learned" value={learning?.lessons} />
                <MiniStat label="Plans checked" value={learning?.task_checks} />
                <MiniStat label="Drift caught" value={learning?.drift_caught} tone={learning?.drift_caught ? "warn" : "ok"} />
              </div>
            </Panel>
          </div>
          <div className="mt-3 text-xs text-mc-dim">
            Open any run to see each permit used, every replan and every task check
            {latestEnded && <> (<Link href={`/runs/${latestEnded.id}`} className="text-mc-accent hover:underline">latest run</Link>)</>}.
          </div>
        </section>

        <section className="grid lg:grid-cols-3 gap-4 mb-10 lg:items-start">
          <Panel title="Untrusted by default" subtitle="Every input can add caution. None can authorize a move." className="lg:col-span-2">
            <div className="grid sm:grid-cols-2 gap-x-6 gap-y-3">
              {UNTRUSTED.map((u) => (
                <div key={u.title} className="flex gap-2.5">
                  <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-mc-accent shrink-0" />
                  <div><div className="text-sm font-semibold">{u.title}</div><p className="text-xs text-mc-mute">{u.text}</p></div>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Live system" subtitle="What is running behind this page">
            <div className="space-y-2.5 text-sm">
              <Row k="Mission planning" v={<span className="text-mc-accent">{short(models?.tiers?.reasoning || models?.primary)}</span>} />
              <Row k="Per-step proposals" v={<span className="text-mc-accent">{(models?.tiers?.fast || []).map(short).join(", ") || "—"}</span>} />
              <Row k="Perception" v={<span className="text-mc-accent">{vision?.enabled ? short(vision.model) : "off"}</span>} />
              <Row k="Voice stop" v={health?.voice_enabled ? "Muse Voice Transcribe" : "off (needs MODEL_API_KEY)"} />
              <Row k="Execution authority" v={authority?.enabled ? "permits enforced" : "not configured"} />
              <Row k="Safety gate" v="11 deterministic policies" />
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
  return String(m || "—").replace(/^nvidia\//, "").replace(/^meta-models\//, "").replace(/_/g, ".");
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
