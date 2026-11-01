"use client";

import { useEffect, useState } from "react";
import { getPerceptionStatus, runPerceptionCheck } from "@/lib/api";

type Obj = { type: string; ahead_m: number; right_m: number; error_m?: number };
type Check = {
  id: string; ts: number; run_id: string | null; model: string; latency_ms: number | null; ok: boolean;
  verdict: "agree" | "missed_hazard" | "unconfirmed_sighting" | "no_answer";
  seen: Obj[]; truth: Obj[]; matched: Obj[]; missed: Obj[]; unconfirmed: Obj[]; note?: string;
};

const VERDICT: Record<Check["verdict"], { text: string; cls: string }> = {
  agree: { text: "Agrees with sensors", cls: "text-emerald-300 border-emerald-500/40 bg-emerald-500/10" },
  missed_hazard: { text: "Missed a hazard", cls: "text-red-300 border-red-500/40 bg-red-500/10" },
  unconfirmed_sighting: { text: "Unconfirmed sighting", cls: "text-amber-300 border-amber-500/40 bg-amber-500/10" },
  no_answer: { text: "No answer", cls: "text-mc-ink/85 border-mc-line2/40 bg-slate-500/10" },
};

const COLOUR: Record<string, string> = { person: "#f0781e", forklift: "#ebbe14", spill: "#6ed2eb", pallet: "#965f2d" };

/** Robot-relative plot: hollow = what the sensors know, filled = what the model saw. */
function Plot({ check }: { check: Check }) {
  const S = 132, view = 12, scale = S / view, ox = S / 2, oy = S * 0.72;
  const px = (o: Obj) => ({ x: ox + o.right_m * scale, y: oy - o.ahead_m * scale });
  return (
    <svg viewBox={`0 0 ${S} ${S}`} className="w-[132px] h-[132px] shrink-0 rounded-md bg-mc-bg/80 border border-mc-line" role="img"
      aria-label="Vision check: sensor objects as rings, model sightings as dots, robot at the bottom facing up">
      <polygon points={`${ox},${oy - 6} ${ox - 5},${oy + 4} ${ox + 5},${oy + 4}`} fill="#3b82f6" />
      {check.truth.map((o, i) => { const p = px(o); return <circle key={`t${i}`} cx={p.x} cy={p.y} r={5} fill="none" stroke={COLOUR[o.type] || "#94a3b8"} strokeWidth={1.5} />; })}
      {check.seen.map((o, i) => { const p = px(o); return <circle key={`s${i}`} cx={p.x} cy={p.y} r={2.6} fill={COLOUR[o.type] || "#cbd5e1"} />; })}
      {check.missed.map((o, i) => { const p = px(o); return <circle key={`m${i}`} cx={p.x} cy={p.y} r={8} fill="none" stroke="#ef4444" strokeWidth={1.5} strokeDasharray="2 2" />; })}
    </svg>
  );
}

const list = (items: Obj[]) => items.map((o) => `${o.type} ${o.ahead_m.toFixed(1)} m ahead`).join(", ");

/**
 * Vision check: an NVIDIA vision-language model on Nebius Token Factory reads the
 * robot camera; Sovereign Autonomy compares what it saw with the sensors. The gate never
 * relies on it — a sighting the sensors can't confirm can only slow the robot.
 */
export function VisionPanel({ runId }: { runId?: string }) {
  const [status, setStatus] = useState<any>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    const load = async () => {
      try {
        const s = await getPerceptionStatus();
        if (live) setStatus(s);
      } catch (_) {}
    };
    load();
    const id = setInterval(load, 2500);
    return () => { live = false; clearInterval(id); };
  }, []);

  if (!status) return null;
  const recent: Check[] = status.recent || [];
  const mine = runId ? recent.filter((c) => c.run_id === runId || c.run_id === null) : recent;
  const last = mine[mine.length - 1];
  const zones: any[] = status.caution_zones || [];
  const shortModel = String(status.model || "").replace(/^nvidia\//, "");

  async function checkNow() {
    setChecking(true);
    setError(null);
    try {
      await runPerceptionCheck();
      setStatus(await getPerceptionStatus());
    } catch (e: any) {
      setError(e?.message || "Vision check failed");
    }
    setChecking(false);
  }

  return (
    <div className="bg-mc-panel/60 rounded-xl border border-mc-line p-4">
      <div className="flex items-center justify-between mb-2 gap-2">
        <h3 className="text-sm font-bold text-mc-ink tracking-wide uppercase">Vision check</h3>
        <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${status.enabled ? "text-emerald-300 border-emerald-500/40 bg-emerald-500/10" : "text-mc-ink/85 border-mc-line2/40"}`}>
          {status.enabled ? shortModel : "Off (needs Nebius key)"}
        </span>
      </div>
      <p className="text-[11px] text-mc-mute mb-3 leading-relaxed">
        An NVIDIA vision model reads the robot camera every {status.interval_s ?? 5}s during a run. Its answer is checked against the sensors and never trusted on its own: anything it sees that the sensors don&apos;t can only slow the robot.
      </p>

      {!last ? (
        <div className="text-xs text-mc-dim mb-2">No vision checks yet. They run while a mission is active.</div>
      ) : (
        <div className="flex gap-3 mb-2">
          <Plot check={last} />
          <div className="min-w-0 text-[11px] space-y-1.5">
            <span className={`inline-block text-[10px] font-semibold px-2 py-0.5 rounded-full border ${VERDICT[last.verdict]?.cls}`}>
              {VERDICT[last.verdict]?.text ?? last.verdict}
            </span>
            <div className="text-mc-mute font-mono text-[10px]">
              {last.latency_ms != null ? `${last.latency_ms} ms` : "—"} · {new Date(last.ts * 1000).toLocaleTimeString()}
            </div>
            <div className="text-mc-ink/85">Matched: {last.matched.length ? list(last.matched) : "nothing in view"}</div>
            {last.missed.length > 0 && <div className="text-red-300">Missed: {list(last.missed)} (gate kept using sensors)</div>}
            {last.unconfirmed.length > 0 && <div className="text-amber-300">Unconfirmed: {list(last.unconfirmed)} (slowed nearby)</div>}
          </div>
        </div>
      )}

      {zones.length > 0 && (
        <div className="text-[11px] text-amber-200 mb-2">{zones.length} vision slow zone{zones.length > 1 ? "s" : ""} in force (expire in {status.caution_ttl_s ?? 8}s)</div>
      )}

      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] text-mc-dim">rings = sensors · dots = model · red dashes = missed</span>
        {status.enabled && (
          <button onClick={checkNow} disabled={checking}
            className="text-[11px] px-2.5 py-1 rounded-md border border-cyan-500/40 text-cyan-300 hover:bg-cyan-500/10 disabled:opacity-50">
            {checking ? "Checking…" : "Check now"}
          </button>
        )}
      </div>
      {error && <div className="text-[11px] text-red-300 mt-1">{error}</div>}
    </div>
  );
}
