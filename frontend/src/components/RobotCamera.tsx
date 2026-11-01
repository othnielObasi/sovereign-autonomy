"use client";

import { useEffect, useRef, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "/api";

/**
 * The robot's camera: a heading-up, top-down view around the robot, refreshed
 * about once a second. This is the image the vision model reads.
 */
export function RobotCamera({ active = true, intervalMs = 1000 }: { active?: boolean; intervalMs?: number }) {
  const [src, setSrc] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const urlRef = useRef<string | null>(null);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    const load = async () => {
      try {
        const r = await fetch(`${API_BASE}/sim/frame?size=384&t=${Date.now()}`, { cache: "no-store" });
        if (!r.ok) throw new Error(r.status === 502 ? "Camera needs the warehouse simulator" : `HTTP ${r.status}`);
        const url = URL.createObjectURL(await r.blob());
        if (cancelled) return URL.revokeObjectURL(url);
        if (urlRef.current) URL.revokeObjectURL(urlRef.current);
        urlRef.current = url;
        setSrc(url);
        setError(null);
      } catch (e: any) {
        if (!cancelled) setError(e?.message || "Camera unavailable");
      }
    };
    load();
    const id = setInterval(load, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [active, intervalMs]);

  useEffect(() => () => { if (urlRef.current) URL.revokeObjectURL(urlRef.current); }, []);

  return (
    <div className="bg-slate-800/60 rounded-xl border border-slate-700 p-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-slate-200 uppercase tracking-wider">Robot camera</span>
        <span className="text-[10px] text-slate-400">heading up · 12 m view</span>
      </div>
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={src} alt="Top-down view around the robot, robot facing up" className="w-full aspect-square rounded-lg" />
      ) : (
        <div className="w-full aspect-square rounded-lg bg-slate-900 flex items-center justify-center text-xs text-slate-500 text-center px-4">
          {error || "Connecting…"}
        </div>
      )}
      <div className="flex flex-wrap gap-x-3 gap-y-1 mt-2 text-[10px] text-slate-400">
        <span><i className="inline-block w-2 h-2 rounded-full mr-1 align-middle" style={{ background: "#f0781e" }} />person</span>
        <span><i className="inline-block w-2 h-2 mr-1 align-middle" style={{ background: "#ebbe14" }} />forklift</span>
        <span><i className="inline-block w-2 h-2 rounded-full mr-1 align-middle" style={{ background: "#6ed2eb" }} />spill</span>
        <span><i className="inline-block w-2 h-2 mr-1 align-middle" style={{ background: "#965f2d" }} />pallet</span>
        <span><i className="inline-block w-2 h-2 mr-1 align-middle" style={{ background: "#4a3e34" }} />racking</span>
      </div>
    </div>
  );
}
