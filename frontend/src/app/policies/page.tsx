"use client";

import React, { useEffect, useMemo, useState } from "react";
import {
  getActivePolicies, getLearningSummary, getLessons, getPolicyActivations, getPolicyProposals, getTuningRecommendations,
  listPolicies, testPolicy,
} from "@/lib/api";
import { Button, Empty, KV, Mono, Notice, Page, PageHeader, Panel, Pill, Tabs, Verdict, cx } from "@/components/ui";
import { DriftDemo } from "@/components/DriftDemo";

type Policy = { policy_id: string; name: string; description: string; severity: string; parameters?: Record<string, any>; trigger?: string; action?: string };
type TabId = "policies" | "rules" | "learning" | "sandbox";

const GROUPS: Array<{ title: string; ids: string[] }> = [
  { title: "Where the robot may go", ids: ["GEOFENCE_01", "PATH_CLEARANCE_07", "OBSTACLE_CLEARANCE_03"] },
  { title: "People and vehicles", ids: ["HUMAN_PROXIMITY_02", "HUMAN_CLEARANCE_02", "WORKER_PROXIMITY_06", "UNCERTAINTY_04"] },
  { title: "Speed and hazards", ids: ["SAFE_SPEED_01", "HAZARD_EXCLUSION_08", "HAZARD_SLOW_09"] },
  { title: "Escalation", ids: ["HITL_05"] },
];

export default function GovernancePage() {
  const [tab, setTabState] = useState<TabId>("policies");
  const setTab = (id: string) => setTabState(id as TabId);
  return (
    <Page wide>
      <PageHeader eyebrow="Governance" title="The rules every move must pass"
        subtitle="Eleven deterministic policies judge every proposal before the robot moves. The rules change only through a governed workflow; the planner learns from the gate, the gate does not drift." />
      <Tabs className="mb-5" value={tab} onChange={setTab} tabs={[
        { id: "policies", label: "Policies" },
        { id: "rules", label: "Rules in force" },
        { id: "learning", label: "Learning & task focus" },
        { id: "sandbox", label: "Test a move or plan" },
      ]} />
      {tab === "policies" && <Policies />}
      {tab === "rules" && <Rules />}
      {tab === "learning" && <Learning />}
      {tab === "sandbox" && <div className="space-y-4"><Sandbox /><DriftDemo /></div>}
    </Page>
  );
}

/* ── Policies ───────────────────────────────────────────────────────────── */

function Policies() {
  const [policies, setPolicies] = useState<Policy[] | null>(null);
  useEffect(() => { listPolicies().then(setPolicies).catch(() => setPolicies([])); }, []);
  if (!policies) return <div className="text-sm text-mc-dim">Loading policies…</div>;
  const byId = Object.fromEntries(policies.map((p) => [p.policy_id, p]));
  const grouped = new Set(GROUPS.flatMap((g) => g.ids));
  const rest = policies.filter((p) => !grouped.has(p.policy_id));
  return (
    <div className="space-y-6">
      {[...GROUPS, ...(rest.length ? [{ title: "Other", ids: rest.map((p) => p.policy_id) }] : [])].map((g) => (
        <section key={g.title}>
          <h2 className="text-[13px] font-semibold uppercase tracking-[0.12em] text-mc-dim mb-2.5">{g.title}</h2>
          <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3">
            {g.ids.map((id) => byId[id]).filter(Boolean).map((p) => (
              <div key={p.policy_id} className="rounded-xl border border-mc-line bg-mc-panel p-4 flex flex-col">
                <div className="flex items-start justify-between gap-2">
                  <Mono>{p.policy_id}</Mono>
                  <Pill tone={p.severity === "HIGH" ? "stop" : p.severity === "MEDIUM" ? "warn" : "neutral"}>{p.severity}</Pill>
                </div>
                <div className="mt-1.5 font-semibold">{p.name}</div>
                <p className="mt-1 text-xs text-mc-mute leading-relaxed flex-1">{p.description}</p>
                <div className="mt-3 pt-3 border-t border-mc-line/70 space-y-1 text-xs">
                  {p.trigger && <div><span className="text-mc-dim">When </span><span className="text-mc-ink">{p.trigger}</span></div>}
                  {p.action && <div><span className="text-mc-dim">Then </span><span className="text-mc-warn font-medium">{p.action}</span></div>}
                  {p.parameters && Object.keys(p.parameters).length > 0 && (
                    <div className="flex flex-wrap gap-1 pt-1">
                      {Object.entries(p.parameters).map(([k, v]) => (
                        <span key={k} className="font-mono text-[10px] text-mc-mute bg-mc-raise border border-mc-line rounded px-1.5 py-0.5">{k}={String(v)}</span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

/* ── Rules in force ─────────────────────────────────────────────────────── */

const WORKFLOW = [
  ["Propose", "A named threshold change, inside hard bounds in code."],
  ["Replay", "Every recorded decision re-judged under the candidate; one unsafe move allowed fails it."],
  ["Benchmark", "Seeded scenarios under both rule sets; required for any relaxation."],
  ["Approve", "A named person who is not the proposer."],
  ["Activate", "Only between runs; append-only record; rollback any time."],
];

function Rules() {
  const [active, setActive] = useState<any>(null);
  const [activations, setActivations] = useState<any[]>([]);
  const [proposals, setProposals] = useState<any[]>([]);
  useEffect(() => {
    getActivePolicies().then(setActive).catch(() => {});
    getPolicyActivations().then((d: any) => setActivations(Array.isArray(d) ? d : d.activations || [])).catch(() => {});
    getPolicyProposals().then((d: any) => setProposals(Array.isArray(d) ? d : d.proposals || [])).catch(() => {});
  }, []);
  const changeable = Object.entries(active?.changeable || {}) as Array<[string, any]>;
  const value = (path: string) => path.split(".").reduce((o: any, k) => (o == null ? o : o[k]), active?.parameters);
  return (
    <div className="grid lg:grid-cols-3 gap-4">
      <div className="lg:col-span-2 space-y-4">
        <Panel title="Changeable thresholds" subtitle="Current value and the hard bounds in code no proposal can cross"
          actions={active && <Pill tone={active.is_default ? "neutral" : "warn"}>version <Mono className="ml-1">{active.version}</Mono></Pill>}>
          {!active ? <div className="text-xs text-mc-dim">Loading…</div> : (
            <div className="overflow-x-auto mc-scroll">
              <table className="w-full text-sm tabular">
                <thead><tr className="text-[11px] uppercase tracking-wider text-mc-dim">
                  <th className="text-left py-1.5">Threshold</th><th className="text-right px-2">Now</th><th className="text-right px-2">Bounds</th><th className="text-right px-2">Tighter is</th>
                </tr></thead>
                <tbody>
                  {changeable.map(([k, spec]) => (
                    <tr key={k} className="border-t border-mc-line/70">
                      <td className="py-1.5"><Mono className="text-mc-ink">{k}</Mono></td>
                      <td className="text-right px-2 text-mc-accent">{String(value(k) ?? "—")} {spec.unit || ""}</td>
                      <td className="text-right px-2 text-mc-mute">{spec.min} – {spec.max}</td>
                      <td className="text-right px-2 text-mc-mute">{spec.tighter}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
        <Panel title="Change history" subtitle="Every activation is an append-only record">
          {activations.length === 0 && proposals.length === 0 ? (
            <Empty title="Running on the default rules">No rule change has been proposed or activated on this deployment.</Empty>
          ) : (
            <ul className="divide-y divide-mc-line text-sm">
              {[...proposals.map((p) => ({ ...p, _kind: "proposal" })), ...activations.map((a) => ({ ...a, _kind: "activation" }))].map((x: any, i) => (
                <li key={i} className="py-2 flex flex-wrap items-center gap-2">
                  <Pill tone={x._kind === "activation" ? "accent" : "neutral"}>{x._kind}</Pill>
                  <Verdict value={x.status || x.action || "recorded"} />
                  <span className="text-xs text-mc-mute">{x.description || x.note || JSON.stringify(x.changes || {})}</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
      <div className="space-y-4">
        <Panel title="How rules change">
          <ol className="space-y-2.5">
            {WORKFLOW.map(([t, d], i) => (
              <li key={t} className="flex gap-3">
                <span className="font-mono text-xs text-mc-accent mt-0.5">{String(i + 1).padStart(2, "0")}</span>
                <span><span className="text-sm font-semibold">{t}</span><span className="block text-xs text-mc-mute">{d}</span></span>
              </li>
            ))}
          </ol>
          <div className="mt-3"><Notice tone="warn">Read-only on the public demo: everyone shares the same rules.</Notice></div>
        </Panel>
        <Panel title="Safety floors" subtitle="Fixed in code; label moves safe or unsafe in replay and benchmarks">
          {active?.safety_floors ? Object.entries(active.safety_floors).filter(([k]) => k !== "geofence").map(([k, v]) => (
            <KV key={k} k={k.replace(/_/g, " ")} v={String(v)} mono />
          )) : <div className="text-xs text-mc-dim">Loading…</div>}
        </Panel>
      </div>
    </div>
  );
}

/* ── Learning ───────────────────────────────────────────────────────────── */

function Learning() {
  const [lessons, setLessons] = useState<any>(null);
  const [tuning, setTuning] = useState<any>(null);
  useEffect(() => {
    getLessons().then(setLessons).catch(() => setLessons({ lessons: [] }));
    getTuningRecommendations().then(setTuning).catch(() => {});
  }, []);
  const list: any[] = lessons?.lessons || [];
  return (
    <div className="grid lg:grid-cols-3 gap-4">
      <Panel className="lg:col-span-2" padded={false}
        title="Lessons the planner receives"
        subtitle="Distilled only from the gate's own decisions; scoped to the rules version; advisory: the gate still judges every move"
        actions={lessons && <Pill>{list.length} lessons · rules <Mono className="ml-1">{lessons.policy_version}</Mono></Pill>}>
        {!lessons ? <div className="p-4 text-xs text-mc-dim">Loading…</div> : list.length === 0 ? (
          <Empty title="No lessons yet">They appear after runs in which the gate denied moves.</Empty>
        ) : (
          <ul className="divide-y divide-mc-line max-h-[620px] overflow-y-auto mc-scroll">
            {list.map((l) => (
              <li key={l.id} className="px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Mono>L{l.id}</Mono>
                  <Pill tone="stop">{l.policy}</Pill>
                  <span className="text-xs text-mc-dim">{l.zone} · cell ({l.cell_x}, {l.cell_y}) · {l.denials} denials · {(l.runs || []).length} run{(l.runs || []).length === 1 ? "" : "s"}</span>
                </div>
                <p className="mt-1.5 text-sm text-mc-mute leading-relaxed">{l.text}</p>
              </li>
            ))}
          </ul>
        )}
      </Panel>
      <div className="space-y-4">
        <Panel title="How learning works">
          <ol className="space-y-2.5 text-xs text-mc-mute">
            <li><span className="text-mc-ink font-semibold">Distil.</span> After each run, denials are grouped by 2 m floor cell and policy, with the fastest speed the gate approved there.</li>
            <li><span className="text-mc-ink font-semibold">Retrieve.</span> Before planning, up to 5 lessons within 4 m of the route go to Nemotron as advice.</li>
            <li><span className="text-mc-ink font-semibold">Audit.</span> Each plan records the lessons that shaped it in the hash chain.</li>
          </ol>
        </Panel>
        <TaskDriftCard />
        <Panel title="Tuning advice" subtitle="Recommend-only; a change still needs the governed workflow">
          {!tuning ? <div className="text-xs text-mc-dim">Loading…</div> : (tuning.recommendations || []).length === 0 ? (
            <div className="text-xs text-mc-dim">No recommendations yet.</div>
          ) : (
            <ul className="space-y-2">
              {tuning.recommendations.slice(0, 5).map((r: any, i: number) => (
                <li key={i} className="rounded-lg bg-mc-raise border border-mc-line p-2.5 text-xs">
                  <div className="flex justify-between gap-2"><Mono className="text-mc-ink">{r.param}</Mono>
                    <span className={cx(r.direction === "decrease" ? "text-mc-ok" : "text-mc-warn")}>{r.current} → {r.suggested}</span></div>
                  <div className="text-mc-mute mt-1">{r.reason}</div>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}

function TaskDriftCard() {
  const [s, setS] = useState<any>(null);
  useEffect(() => { getLearningSummary().then(setS).catch(() => {}); }, []);
  return (
    <Panel title="Task-drift control" subtitle="Every plan and replan is checked before use">
      <ul className="space-y-1.5 text-xs text-mc-mute">
        <li>Ends at the mission destination (from the mission record, never the model)</li>
        <li>Stays inside the site; at most 2× the aisle route + 8 m</li>
        <li>A failing plan is replaced by the aisle route to the same destination</li>
      </ul>
      {s && (
        <div className="mt-3 pt-3 border-t border-mc-line/70">
          <KV k="Plans checked" v={s.task_checks} />
          <KV k="Drift caught" v={<span className={s.drift_caught ? "text-mc-warn" : "text-mc-ok"}>{s.drift_caught}</span>} />
          <KV k="Replans after a denial" v={s.replans} />
          <KV k="Plans shaped by lessons" v={s.plans_with_lessons} />
        </div>
      )}
    </Panel>
  );
}

/* ── Sandbox ────────────────────────────────────────────────────────────── */

const PRESETS = [
  { label: "Clear aisle", tone: "ok" as const,
    telemetry: { x: 14, y: 3.5, zone: "aisle", nearest_obstacle_m: 2.0, human_detected: false, human_conf: 0.0 },
    proposal: { intent: "MOVE_TO", params: { x: 18, y: 3.5, max_speed: 0.5 }, rationale: "Follow the aisle" } },
  { label: "Person 2.5 m, too fast", tone: "warn" as const,
    telemetry: { x: 14, y: 3.5, zone: "aisle", nearest_obstacle_m: 1.5, human_detected: true, human_conf: 0.85, human_distance_m: 2.5 },
    proposal: { intent: "MOVE_TO", params: { x: 16, y: 3.5, max_speed: 0.8 }, rationale: "Approach target" } },
  { label: "Person 0.8 m away", tone: "stop" as const,
    telemetry: { x: 14, y: 3.5, zone: "aisle", nearest_obstacle_m: 1.5, human_detected: true, human_conf: 0.95, human_distance_m: 0.8 },
    proposal: { intent: "MOVE_TO", params: { x: 15, y: 3.5, max_speed: 0.3 }, rationale: "Keep going" } },
  { label: "Straight through racking", tone: "stop" as const,
    telemetry: { x: 3, y: 3.5, zone: "aisle", nearest_obstacle_m: 1.1, human_detected: false, human_conf: 0.0 },
    proposal: { intent: "MOVE_TO", params: { x: 16, y: 23, max_speed: 0.3 }, rationale: "Shortest path" } },
  { label: "Outside the geofence", tone: "stop" as const,
    telemetry: { x: 38, y: 12, zone: "corridor", nearest_obstacle_m: 3.0, human_detected: false, human_conf: 0.0 },
    proposal: { intent: "MOVE_TO", params: { x: 45, y: 12, max_speed: 0.5 }, rationale: "Leave the site" } },
];

function Sandbox() {
  const [idx, setIdx] = useState(1);
  const [tel, setTel] = useState(JSON.stringify(PRESETS[1].telemetry, null, 2));
  const [prop, setProp] = useState(JSON.stringify(PRESETS[1].proposal, null, 2));
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [advanced, setAdvanced] = useState(false);

  function pick(i: number) {
    setIdx(i); setRes(null); setErr(null);
    setTel(JSON.stringify(PRESETS[i].telemetry, null, 2));
    setProp(JSON.stringify(PRESETS[i].proposal, null, 2));
  }
  async function run() {
    setErr(null); setBusy(true);
    try { setRes(await testPolicy({ telemetry: JSON.parse(tel), proposal: JSON.parse(prop) })); }
    catch (e: any) { setErr(e instanceof SyntaxError ? "That isn't valid JSON." : e.message || "Check failed"); }
    setBusy(false);
  }
  const p = useMemo(() => { try { return JSON.parse(prop); } catch { return null; } }, [prop]);
  const t = useMemo(() => { try { return JSON.parse(tel); } catch { return null; } }, [tel]);

  return (
    <div className="grid lg:grid-cols-2 gap-4">
      <Panel title="A proposed move" subtitle="Pick a situation, or edit the raw input">
        <div className="flex flex-wrap gap-2 mb-4">
          {PRESETS.map((s, i) => (
            <button key={s.label} onClick={() => pick(i)}
              className={cx("rounded-lg border px-3 py-1.5 text-xs font-medium", i === idx ? "border-mc-accent bg-mc-accent/10 text-mc-ink" : "border-mc-line2 text-mc-mute hover:text-mc-ink")}>
              <span className={cx("inline-block w-1.5 h-1.5 rounded-full mr-1.5 align-middle", s.tone === "ok" ? "bg-mc-ok" : s.tone === "warn" ? "bg-mc-warn" : "bg-mc-stop")} />{s.label}
            </button>
          ))}
        </div>
        {t && p && (
          <div className="grid grid-cols-2 gap-3 text-xs mb-4">
            <div className="rounded-lg bg-mc-raise border border-mc-line p-3">
              <div className="text-mc-dim uppercase tracking-wider text-[10px] mb-1">Robot sees</div>
              <div>at ({t.x}, {t.y}) in {t.zone}</div>
              <div>nearest obstacle {t.nearest_obstacle_m} m</div>
              <div>{t.human_detected ? `person ${t.human_distance_m ?? "?"} m away (conf ${t.human_conf})` : "no person detected"}</div>
            </div>
            <div className="rounded-lg bg-mc-raise border border-mc-line p-3">
              <div className="text-mc-dim uppercase tracking-wider text-[10px] mb-1">Planner proposes</div>
              <div>{p.intent} → ({p.params?.x}, {p.params?.y})</div>
              <div>at {p.params?.max_speed} m/s</div>
              <div className="text-mc-mute">&ldquo;{p.rationale}&rdquo;</div>
            </div>
          </div>
        )}
        <button onClick={() => setAdvanced(!advanced)} className="text-xs text-mc-accent hover:underline mb-2">{advanced ? "Hide" : "Edit"} raw input</button>
        {advanced && (
          <div className="grid gap-3 mb-3">
            <label className="text-xs text-mc-dim">Telemetry
              <textarea value={tel} onChange={(e) => setTel(e.target.value)} rows={7} spellCheck={false}
                className="mt-1 w-full rounded-lg bg-mc-bg border border-mc-line2 p-2 font-mono text-xs text-mc-ink" /></label>
            <label className="text-xs text-mc-dim">Proposal
              <textarea value={prop} onChange={(e) => setProp(e.target.value)} rows={6} spellCheck={false}
                className="mt-1 w-full rounded-lg bg-mc-bg border border-mc-line2 p-2 font-mono text-xs text-mc-ink" /></label>
          </div>
        )}
        <Button variant="primary" onClick={run} disabled={busy} className="w-full">{busy ? "Checking…" : "Ask the gate"}</Button>
        {err && <div className="mt-2"><Notice tone="stop">{err}</Notice></div>}
      </Panel>

      <Panel title="Gate decision">
        {!res ? <Empty title="No decision yet">The gate&apos;s verdict, the policies that fired and why will appear here.</Empty> : (
          <div>
            <div className="flex items-center gap-3">
              <Verdict value={res.decision} className="text-sm px-3 py-1" />
              {res.policy_state && <Verdict value={res.policy_state} />}
              <span className="ml-auto text-xs text-mc-dim">risk <span className="text-mc-ink tabular">{Number(res.risk_score ?? 0).toFixed(2)}</span></span>
            </div>
            {(res.policy_hits || []).length > 0 ? (
              <div className="mt-4 space-y-2">
                {(res.policy_hits || []).map((h: string, i: number) => (
                  <div key={h + i} className="rounded-lg border border-mc-stop/30 bg-mc-stop/5 p-2.5">
                    <Mono className="text-mc-stop">{h}</Mono>
                    {res.reasons?.[i] && <div className="text-xs text-mc-mute mt-1">{res.reasons[i]}</div>}
                  </div>
                ))}
                {res.required_action && <Notice tone="warn">Required: {res.required_action}</Notice>}
              </div>
            ) : <div className="mt-4"><Notice tone="ok">All 11 policies passed. The move would execute.</Notice></div>}
          </div>
        )}
      </Panel>
    </div>
  );
}
