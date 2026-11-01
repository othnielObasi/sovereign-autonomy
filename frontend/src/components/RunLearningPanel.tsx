"use client";

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { getLessons } from "@/lib/api";
import { Mono, Pill, Verdict, cx } from "@/components/ui";

type Ev = { id?: number | string; type: string; ts?: string; payload?: any; payload_json?: any };

const payloadOf = (e: Ev) => e.payload ?? e.payload_json ?? {};
const short = (m?: string) => String(m || "").replace(/^nvidia\//, "");
const time = (ts?: string) => (ts ? new Date(ts).toLocaleTimeString() : "");

/**
 * How this run stayed on task and what it learned:
 * - task checks on every plan and replan (ends at the mission destination, no wandering);
 * - lessons from earlier runs that the planner was given, and which it says it used;
 * - each replan: what the gate blocked and what came back;
 * - the lessons this run produced for future runs.
 */
export function RunLearningPanel({ runId, events, ended }: { runId: string; events: Ev[]; ended: boolean }) {
  const [produced, setProduced] = useState<any[]>([]);

  useEffect(() => {
    if (!ended) return;
    getLessons().then((d: any) => setProduced((d.lessons || []).filter((l: any) => (l.runs || []).includes(runId)))).catch(() => {});
  }, [ended, runId]);

  const plans = useMemo(() => events.filter((e) => e.type === "PLAN").map((e) => ({ e, p: payloadOf(e) }))
    .filter(({ p }) => p.source !== "fallback" || p.task_check || p.note?.startsWith("Replan")), [events]);
  const checks = useMemo(() => events.filter((e) => e.type === "TASK_CHECK").map((e) => ({ e, p: payloadOf(e) })), [events]);
  const replans = useMemo(() => events.filter((e) => e.type === "REPLAN").map((e) => ({ e, p: payloadOf(e) })), [events]);
  const offered = useMemo(() => {
    const m = new Map<string, string>();
    plans.forEach(({ p }) => (p.lessons_offered || []).forEach((l: any) => m.set(String(l.id), l.text)));
    return [...m.entries()];
  }, [plans]);
  const applied = useMemo(() => new Set(plans.flatMap(({ p }) => (p.lessons_applied || []).map((l: any) => String(l.id)))), [plans]);
  const drifts = checks.filter(({ p }) => p.verdict === "DRIFT").length;

  return (
    <div className="space-y-3">
      {/* Task focus */}
      <section className="rounded-xl border border-mc-line bg-mc-panel p-4">
        <div className="flex items-center justify-between gap-2 mb-2">
          <h3 className="text-[13px] font-semibold uppercase tracking-[0.08em]">Task focus</h3>
          {checks.length > 0 && <Pill tone={drifts ? "warn" : "ok"} dot>{drifts ? `${drifts} drift caught` : "On task"}</Pill>}
        </div>
        <p className="text-xs text-mc-mute mb-3">Each plan must end at the mission&apos;s destination without wandering, or the aisle route is used.</p>
        {checks.length === 0 ? <div className="text-xs text-mc-dim">No plan checked yet.</div> : (
          <ul className="space-y-2">
            {checks.map(({ e, p }, i) => (
              <li key={String(e.id ?? i)} className="rounded-lg bg-mc-raise border border-mc-line p-2.5 text-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <Verdict value={p.verdict === "ON_TASK" ? "PASS" : "DRIFT"} />
                  <span className="text-mc-ink">{p.stage === "replan" ? "Replan" : "Mission plan"}</span>
                  <span className="text-mc-dim tabular ml-auto">{time(e.ts)}</span>
                </div>
                <div className="mt-1.5 text-mc-mute tabular">
                  ends {p.metrics?.end_distance_to_goal_m ?? "?"} m from destination
                  {p.metrics?.plan_length_m != null && <> · {p.metrics.plan_length_m} m long</>}
                  {p.metrics?.reference_length_m != null && <> (aisle route {p.metrics.reference_length_m} m)</>}
                </div>
                {(p.reasons || []).map((r: string, j: number) => <div key={j} className="mt-1 text-mc-warn">{r}</div>)}
                {p.action === "replaced_with_aisle_route" && <div className="mt-1 text-mc-ok">Replaced with the aisle route to the same destination.</div>}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Lessons given to the planner */}
      <section className="rounded-xl border border-mc-line bg-mc-panel p-4">
        <div className="flex items-center justify-between gap-2 mb-2">
          <h3 className="text-[13px] font-semibold uppercase tracking-[0.08em]">Lessons the planner was given</h3>
          <Pill>{offered.length}</Pill>
        </div>
        {offered.length === 0 ? (
          <div className="text-xs text-mc-dim">No lessons near this route yet. They come from earlier runs where the gate denied moves nearby.</div>
        ) : (
          <ul className="space-y-1.5">
            {offered.map(([id, text]) => (
              <li key={id} className="text-xs leading-relaxed">
                <Mono>L{id}</Mono>{" "}
                {applied.has(id) && <Pill tone="nv" className="mr-1">used by Nemotron</Pill>}
                <span className="text-mc-mute">{text}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Replans */}
      <section className="rounded-xl border border-mc-line bg-mc-panel p-4">
        <div className="flex items-center justify-between gap-2 mb-2">
          <h3 className="text-[13px] font-semibold uppercase tracking-[0.08em]">Replans after a denial</h3>
          <Pill>{replans.length}</Pill>
        </div>
        {replans.length === 0 ? <div className="text-xs text-mc-dim">No replans: the gate hasn&apos;t blocked the same waypoint three times.</div> : (
          <ol className="space-y-2">
            {replans.map(({ e, p }, i) => {
              const next = plans.find(({ e: pe }) => pe.ts && e.ts && pe.ts >= e.ts && payloadOf(pe).note?.startsWith("Replan"));
              const np = next ? payloadOf(next.e) : null;
              return (
                <li key={String(e.id ?? i)} className="rounded-lg bg-mc-raise border border-mc-line p-2.5 text-xs">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-mc-dim">#{i + 1}</span>
                    {(p.policy_hits || []).map((h: string) => <Pill key={h} tone="stop">{h}</Pill>)}
                    <span className="text-mc-dim tabular ml-auto">{time(e.ts)}</span>
                  </div>
                  <div className="mt-1.5 text-mc-mute">
                    Blocked {p.denial_count ?? 3}× at ({Number(p.blocked_waypoint?.x).toFixed(1)}, {Number(p.blocked_waypoint?.y).toFixed(1)})
                    {np && <> → new plan from <span className={cx(np.source === "fallback" ? "text-mc-mute" : "text-mc-nv")}>{np.source === "fallback" ? "the aisle router" : short(np.plan?.model_used)}</span>, {np.plan?.waypoints?.length ?? "?"} waypoints</>}
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </section>

      {/* Lessons produced */}
      <section className="rounded-xl border border-mc-line bg-mc-panel p-4">
        <div className="flex items-center justify-between gap-2 mb-2">
          <h3 className="text-[13px] font-semibold uppercase tracking-[0.08em]">What this run taught the planner</h3>
          {ended && <Pill tone={produced.length ? "accent" : "neutral"}>{produced.length}</Pill>}
        </div>
        {!ended ? (
          <div className="text-xs text-mc-dim">Lessons are distilled from the gate&apos;s decisions when the run ends.</div>
        ) : produced.length === 0 ? (
          <div className="text-xs text-mc-dim">No new lessons: the gate had nothing to teach from this run.</div>
        ) : (
          <ul className="space-y-1.5">
            {produced.map((l) => (
              <li key={l.id} className="text-xs leading-relaxed"><Mono>L{l.id}</Mono> <span className="text-mc-mute">{l.text}</span></li>
            ))}
          </ul>
        )}
        <div className="mt-2 text-[11px] text-mc-dim">
          Lessons only change what the planner proposes; the gate still judges every move. <Link href="/policies" className="text-mc-accent hover:underline">All lessons →</Link>
        </div>
      </section>
    </div>
  );
}
