"use client";

import React, { useEffect, useState } from "react";
import { checkPlanForDrift, getWorld } from "@/lib/api";
import { Button, Empty, Notice, Panel, Verdict, cx } from "@/components/ui";

type P = { x: number; y: number };

// Mission: from the robot's parking spot near A-01 to dock B-03.
const START: P = { x: 3, y: 3.5 };
const GOAL: P = { x: 16, y: 23 };

const CASES: Array<{ id: string; label: string; note: string; wps: P[] }> = [
  { id: "ok", label: "On task", note: "Along the aisle, up the cross-aisle, to dock B-03.",
    wps: [{ x: 12.5, y: 3.5 }, { x: 12.5, y: 13.5 }, { x: 16, y: 13.5 }, { x: 16, y: 23 }] },
  { id: "wrong", label: "Wrong destination", note: "A planted plan that ends at dock B-05, not B-03.",
    wps: [{ x: 12.5, y: 3.5 }, { x: 12.5, y: 13.5 }, { x: 28, y: 13.5 }, { x: 28, y: 23 }] },
  { id: "wander", label: "Wandering detour", note: "Reaches B-03, but tours the whole warehouse first.",
    wps: [{ x: 12.5, y: 3.5 }, { x: 38, y: 5.5 }, { x: 38, y: 13.5 }, { x: 2, y: 13.5 }, { x: 2, y: 20 }, { x: 38, y: 20 }, { x: 16, y: 20 }, { x: 16, y: 23 }] },
  { id: "outside", label: "Leaves the site", note: "Cuts outside the site boundary on the way.",
    wps: [{ x: 12.5, y: 3.5 }, { x: 12.5, y: 13.5 }, { x: 44, y: 13.5 }, { x: 16, y: 23 }] },
];

const W = 40, H = 25;

function SitePlot({ world, submitted, used, replaced }: { world: any; submitted: P[]; used: P[] | null; replaced: boolean }) {
  const sx = (x: number) => x * 10, sy = (y: number) => (H - y) * 10;
  const line = (pts: P[]) => [START, ...pts].map((p) => `${sx(p.x)},${sy(p.y)}`).join(" ");
  return (
    <svg viewBox={`-20 -20 ${W * 10 + 40} ${H * 10 + 40}`} className="w-full rounded-lg bg-mc-bg border border-mc-line"
      role="img" aria-label="Site plan: submitted plan in red or cyan, the plan the robot would follow in green">
      <rect x={0} y={0} width={W * 10} height={H * 10} fill="none" stroke="#253246" strokeWidth={2} />
      <rect x={0} y={sy(15)} width={W * 10} height={30} fill="#111b29" />
      {(world?.racks || []).map((r: any) => (
        <rect key={r.id} x={sx(r.x1)} y={sy(r.y + (r.depth ?? 1))} width={(r.x2 - r.x1) * 10} height={(r.depth ?? 1) * 10} fill="#4a3e34" />
      ))}
      {(world?.bays || []).map((b: any) => (
        <g key={b.id}>
          <rect x={sx(b.x) - 4} y={sy(b.y) - 4} width={8} height={8} fill="none" stroke={b.id === "B-03" ? "#22c55e" : "#334155"} strokeWidth={b.id === "B-03" ? 2 : 1} />
          {b.id.startsWith("B") && <text x={sx(b.x)} y={sy(b.y) - 8} fontSize={9} textAnchor="middle" fill={b.id === "B-03" ? "#22c55e" : "#64748b"}>{b.id}</text>}
        </g>
      ))}
      <polyline points={line(submitted)} fill="none" stroke={replaced ? "#ef4444" : "#22d3ee"} strokeWidth={3} strokeDasharray={replaced ? "6 5" : undefined} strokeLinejoin="round" />
      {used && replaced && <polyline points={line(used)} fill="none" stroke="#22c55e" strokeWidth={3} strokeLinejoin="round" />}
      <circle cx={sx(START.x)} cy={sy(START.y)} r={6} fill="#3b82f6" />
      <text x={sx(START.x) + 9} y={sy(START.y) + 4} fontSize={10} fill="#94a3b8">robot</text>
      <circle cx={sx(GOAL.x)} cy={sy(GOAL.y)} r={7} fill="none" stroke="#22c55e" strokeWidth={2} />
    </svg>
  );
}

/**
 * Task-drift guard, demonstrated on planted plans. Nothing moves and nothing is
 * recorded: the same check every real plan and replan goes through.
 */
export function DriftDemo() {
  const [world, setWorld] = useState<any>(null);
  const [caseId, setCaseId] = useState("wrong");
  const [res, setRes] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const c = CASES.find((x) => x.id === caseId)!;

  useEffect(() => { getWorld().then(setWorld).catch(() => {}); }, []);

  async function run() {
    setBusy(true); setErr(null);
    try { setRes(await checkPlanForDrift({ start: START, goal: GOAL, waypoints: c.wps })); }
    catch (e: any) { setErr(e.message); }
    setBusy(false);
  }

  return (
    <Panel title="Test a plan for task drift"
      subtitle="Mission: take the robot to dock B-03. Pick a plan, as if Nemotron had proposed it, and see what the task guard does. Nothing moves; nothing is recorded.">
      <div className="grid lg:grid-cols-5 gap-4">
        <div className="lg:col-span-2 space-y-3">
          <div className="grid grid-cols-2 gap-2">
            {CASES.map((x) => (
              <button key={x.id} onClick={() => { setCaseId(x.id); setRes(null); }}
                className={cx("rounded-lg border px-3 py-2 text-left text-xs", caseId === x.id ? "border-mc-accent bg-mc-accent/10 text-mc-ink" : "border-mc-line2 text-mc-mute hover:text-mc-ink")}>
                <div className="font-semibold">{x.label}</div>
              </button>
            ))}
          </div>
          <p className="text-xs text-mc-mute">{c.note}</p>
          <Button variant="primary" className="w-full" onClick={run} disabled={busy}>{busy ? "Checking…" : "Run the task guard"}</Button>
          {err && <Notice tone="stop">{err}</Notice>}
          {res && (
            <div className="rounded-lg border border-mc-line bg-mc-raise p-3 space-y-1.5 text-xs">
              <div className="flex items-center gap-2"><Verdict value={res.check.verdict === "ON_TASK" ? "PASS" : "DRIFT"} />
                <span className="text-mc-ink">{res.replaced ? "Plan rejected; aisle route to B-03 used instead" : "Plan accepted"}</span></div>
              <div className="text-mc-mute tabular">ends {res.check.metrics.end_distance_to_goal_m} m from B-03 · {res.check.metrics.plan_length_m} m long · limit {res.check.metrics.length_limit_m ?? "—"} m</div>
              {res.check.reasons.map((r: string, i: number) => <div key={i} className="text-mc-warn">{r}</div>)}
            </div>
          )}
        </div>
        <div className="lg:col-span-3">
          {world ? <SitePlot world={world} submitted={c.wps} used={res?.used || null} replaced={!!res?.replaced} /> : <Empty title="Loading the site…" />}
          <div className="mt-2 flex flex-wrap gap-4 text-[11px] text-mc-dim">
            <span><i className="inline-block w-4 h-0.5 bg-mc-accent align-middle mr-1" />submitted plan</span>
            <span><i className="inline-block w-4 h-0.5 bg-mc-stop align-middle mr-1" />rejected for drift</span>
            <span><i className="inline-block w-4 h-0.5 bg-mc-ok align-middle mr-1" />route the robot would follow</span>
          </div>
        </div>
      </div>
    </Panel>
  );
}
