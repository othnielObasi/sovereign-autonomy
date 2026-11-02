"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import Link from "next/link";
import { SceneBoundary } from "@/components/SceneBoundary";
import { MissionControls, type Destination } from "@/components/twin/MissionControls";
import { getTelemetry, getWorld, triggerScenario, killSwitch } from "@/lib/api";

const Warehouse3D = dynamic(() => import("@/components/twin/Warehouse3D"), {
  ssr: false,
  loading: () => <div className="h-full flex items-center justify-center text-slate-400 text-sm">Loading the 3D warehouse…</div>,
});

const SCENARIOS = [
  { key: "human_approach", label: "Worker steps out" },
  { key: "forklift_crossing", label: "Forklift crossing" },
  { key: "spill", label: "Spill" },
  { key: "path_blocked", label: "Dropped pallet" },
  { key: "clear", label: "Clear" },
];

/** Full-screen live digital twin of the simulated warehouse. */
export default function TwinPage() {
  const [missionOpen, setMissionOpen] = useState(false);
  const [destination, setDestination] = useState<Destination | null>(null);
  const [picking, setPicking] = useState(false);
  const [pickError, setPickError] = useState<string | null>(null);
  const [world, setWorld] = useState<any>(null);
  const [telemetry, setTelemetry] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [stopMessage, setStopMessage] = useState<string | null>(null);
  const [quality, setQuality] = useState<"high" | "low" | undefined>(undefined);
  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("q");
    if (q === "low") setQuality("low");
  }, []);

  useEffect(() => {
    let live = true;
    let loadedWorld = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        if (document.hidden) return;
        if (!loadedWorld) {
          const w = await getWorld();
          if (live) setWorld(w);
          loadedWorld = true;
        }
        const t = await getTelemetry();
        if (live) { setTelemetry(t); setErr(null); }
      } catch (e: any) {
        if (live) setErr(String(e?.message ?? e));
      } finally {
        if (live) timer = setTimeout(poll, 200);
      }
    };
    void poll();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, []);

  return (
    <div className="fixed inset-0 z-[100] bg-slate-950 flex flex-col">
      <div className="flex flex-wrap items-center gap-2 px-4 py-2 border-b border-white/10 bg-slate-900/80">
        <Link href="/overview" className="text-xs text-slate-400 hover:text-white mr-1">← Overview</Link>
        <span className="text-sm font-bold text-white">Sovereign Autonomy · live warehouse</span>
        <span className="text-xs text-slate-400 mr-auto">Every robot move here passes the safety gate before it happens.</span>
        <button aria-expanded={missionOpen} onClick={() => { setMissionOpen(!missionOpen); setPicking(false); }} className="rounded-md bg-cyan-400 px-3 py-1 text-xs font-bold text-slate-950">Plan mission</button>
        <button className="rounded-md bg-red-700 px-3 py-1 text-xs font-bold text-white" onClick={() => {
          killSwitch("global", "*", "digital twin operator stop").then(r => setStopMessage(r.stop_verified ? "Stop confirmed" : "Stop not confirmed — check the robot")).catch(e => setStopMessage(String(e.message)));
        }}>Stop all robots</button>
        {stopMessage && <span role="status" className="text-xs text-white">{stopMessage}</span>}
        {SCENARIOS.map((s) => (
          <button key={s.key} onClick={() => triggerScenario(s.key).catch(() => {})} className="px-2.5 py-1 text-xs rounded-md border border-white/15 text-slate-200 hover:bg-white/10">
            {s.label}
          </button>
        ))}
      </div>
      <div className="flex-1 min-h-0 flex flex-col sm:flex-row">
        <div className="relative flex-1 min-h-0 min-w-0">
        {err && !world ? (
          <div className="h-full flex items-center justify-center text-red-300 text-sm">Simulator unavailable: {err}</div>
        ) : (
          <SceneBoundary>
          <Warehouse3D world={world} telemetry={telemetry} className="h-full" quality={quality} goal={destination} goalLabel={destination?.label} pickingGoal={picking} onGoalPick={(point) => {
            const g = world.geofence;
            const blocked = world.racks.some((r: any) => point.x >= r.x1 - 0.6 && point.x <= r.x2 + 0.6 && point.y >= r.y - 0.6 && point.y <= r.y + (r.depth ?? 1) + 0.6);
            if (blocked || point.x < g.min_x + 0.6 || point.x > g.max_x - 0.6 || point.y < g.min_y + 0.6 || point.y > g.max_y - 0.6) { setPickError("Choose open floor with clearance from racks and walls."); return; }
            setDestination({ x: point.x, y: point.y, label: "Floor destination" }); setPicking(false); setPickError(null);
          }} />
          </SceneBoundary>
        )}
        {pickError && picking && <p role="alert" className="absolute bottom-20 left-3 right-3 rounded bg-red-950/95 p-2 text-xs text-red-200">{pickError}</p>}
        </div>
        {missionOpen && <MissionControls world={world} destination={destination} onDestination={setDestination} picking={picking} onPicking={(value) => { setPicking(value); setPickError(null); }} onClose={() => { setMissionOpen(false); setPicking(false); }} />}
      </div>
    </div>
  );
}
