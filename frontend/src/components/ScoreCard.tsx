/**
 * ScoreCard — radar chart + chain-of-trust integrity badge for a run.
 *
 * Displays five normalised (0–1) scores as a filled SVG radar polygon
 * and fetches hash-chain integrity verification from the backend.
 */

"use client";

import React, { useEffect, useState } from "react";
import { getRunScores, checkRunIntegrity } from "@/lib/api";

const DIMS = ["safety", "compliance", "mission_success", "efficiency", "smoothness"] as const;
const DIM_LABELS: Record<string, string> = {
  safety: "Safety",
  compliance: "Compliance",
  mission_success: "Mission",
  efficiency: "Efficiency",
  smoothness: "Smoothness",
};
const DIM_COLORS: Record<string, string> = {
  safety: "#ef4444",
  compliance: "#3b82f6",
  mission_success: "#10b981",
  efficiency: "#f59e0b",
  smoothness: "#a855f7",
};

function RadarChart({ scores }: { scores: Record<string, number> }) {
  // Centre point, radius, and angular step for the regular polygon.
  const cx = 90, cy = 90, r = 70;
  const n = DIMS.length;
  const angleStep = (2 * Math.PI) / n;  // each dimension is equally spaced

  // Convert each score to polar coordinates for the data polygon
  // and compute label positions just outside the chart.
  const points = DIMS.map((dim, i) => {
    const angle = -Math.PI / 2 + i * angleStep;  // start at 12-o'clock
    const val = scores[dim] ?? 0;
    return {
      x: cx + r * val * Math.cos(angle),
      y: cy + r * val * Math.sin(angle),
      lx: cx + (r + 18) * Math.cos(angle),
      ly: cy + (r + 18) * Math.sin(angle),
    };
  });

  const polygon = points.map(p => `${p.x},${p.y}`).join(" ");

  // Grid rings
  const rings = [0.25, 0.5, 0.75, 1.0];

  return (
    <svg viewBox="0 0 180 180" className="w-full max-w-[200px] mx-auto">
      {/* Grid rings */}
      {rings.map(rv => (
        <polygon
          key={rv}
          points={DIMS.map((_, i) => {
            const a = -Math.PI / 2 + i * angleStep;
            return `${cx + r * rv * Math.cos(a)},${cy + r * rv * Math.sin(a)}`;
          }).join(" ")}
          fill="none"
          stroke="rgba(100,116,139,0.2)"
          strokeWidth="0.5"
        />
      ))}
      {/* Axis lines */}
      {DIMS.map((_, i) => {
        const a = -Math.PI / 2 + i * angleStep;
        return (
          <line key={i} x1={cx} y1={cy} x2={cx + r * Math.cos(a)} y2={cy + r * Math.sin(a)}
            stroke="rgba(100,116,139,0.15)" strokeWidth="0.5" />
        );
      })}
      {/* Data polygon */}
      <polygon points={polygon} fill="rgba(6,182,212,0.15)" stroke="#06b6d4" strokeWidth="1.5" />
      {/* Data points */}
      {points.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r="3" fill={DIM_COLORS[DIMS[i]]} />
      ))}
      {/* Labels */}
      {points.map((p, i) => (
        <text key={i} x={p.lx} y={p.ly} textAnchor="middle" dominantBaseline="central"
          className="fill-slate-400" style={{ fontSize: "6px" }}>
          {DIM_LABELS[DIMS[i]]}
        </text>
      ))}
    </svg>
  );
}

export function ScoreCard({ runId }: { runId: string }) {
  const [scores, setScores] = useState<any>(null);
  const [integrity, setIntegrity] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [sc, integ] = await Promise.all([
          getRunScores(runId),
          checkRunIntegrity(runId).catch(() => null),
        ]);
        if (!cancelled) {
          setScores(sc);
          setIntegrity(integ);
        }
      } catch (e: any) {
        if (!cancelled) setError(e.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [runId]);

  if (loading) return <div className="text-xs text-mc-dim text-center py-4">Loading scorecard…</div>;
  if (error) return <div className="text-xs text-red-400 text-center py-2">{error}</div>;
  if (!scores || scores.error) return <div className="text-xs text-mc-dim text-center py-2">No score data</div>;

  const s = scores.scores || {};
  const composite = s.composite ?? 0;

  return (
    <div className="space-y-3">
      {/* Composite score */}
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-mc-dim">Composite Score</div>
          <div className={`text-2xl font-bold ${composite > 0.7 ? "text-green-400" : composite > 0.4 ? "text-yellow-400" : "text-red-400"}`}>
            {(composite * 100).toFixed(0)}%
          </div>
        </div>
        {integrity && (
          <div className={`text-[10px] px-2 py-1 rounded-full border font-semibold ${
            integrity.verdict === "CLEAN" ? "bg-green-500/15 text-green-400 border-green-500/30" :
            integrity.verdict === "FLAGGED" ? "bg-yellow-500/15 text-yellow-400 border-yellow-500/30" :
            "bg-red-500/15 text-red-400 border-red-500/30"
          }`}>
            {integrity.verdict === "CLEAN" ? "✓ Clean" : integrity.verdict === "FLAGGED" ? "⚠ Flagged" : "✗ Suspicious"}
          </div>
        )}
      </div>

      {/* Radar chart */}
      <RadarChart scores={s} />

      {/* Score bars */}
      <div className="space-y-1.5">
        {DIMS.map(dim => {
          const val = s[dim] ?? 0;
          return (
            <div key={dim} className="flex items-center gap-2">
              <div className="w-16 text-[10px] text-mc-mute truncate">{DIM_LABELS[dim]}</div>
              <div className="flex-1 h-1.5 bg-mc-raise rounded-full overflow-hidden">
                <div className="h-full rounded-full transition-all duration-500" style={{
                  width: `${val * 100}%`,
                  backgroundColor: DIM_COLORS[dim],
                }} />
              </div>
              <div className="w-8 text-[10px] text-mc-ink/85 font-mono text-right">{(val * 100).toFixed(0)}</div>
            </div>
          );
        })}
      </div>

      {/* Integrity flags */}
      {integrity?.flags?.length > 0 && (
        <div className="space-y-1 mt-2">
          <div className="text-[10px] uppercase tracking-wider text-yellow-500 font-semibold">Integrity Flags</div>
          {integrity.flags.map((f: any, i: number) => (
            <div key={i} className={`text-[10px] px-2 py-1 rounded border ${
              f.severity === "high" ? "bg-red-500/10 border-red-500/20 text-red-300" :
              f.severity === "medium" ? "bg-yellow-500/10 border-yellow-500/20 text-yellow-300" :
              "bg-mc-raise/50 border-mc-line2 text-mc-mute"
            }`}>
              <span className="font-semibold">{f.type}</span>: {f.description}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
