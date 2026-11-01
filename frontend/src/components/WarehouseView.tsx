"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef } from "react";
import { Map2D } from "./Map2D";
import type { TwinProps } from "./twin/Warehouse3D";

const Warehouse3D = dynamic(() => import("./twin/Warehouse3D"), { ssr: false,
  loading: () => <div className="p-8 text-slate-400">Loading the 3D warehouse…</div> });

export type WarehouseViewProps = Parameters<typeof Map2D>[0] & Pick<TwinProps, "verdict" | "verdictText" | "proposal" | "quality"> & {
  view: "2d" | "3d";
  trailKey?: string | number;
};

/** One map contract and one trail lifetime, independent of the chosen renderer. */
export function WarehouseView({ view, trailKey, ...props }: WarehouseViewProps) {
  const trail = useRef<{ x: number; y: number }[]>([]);
  useEffect(() => { trail.current = []; }, [trailKey]);
  useEffect(() => {
    const t = props.telemetry;
    if (!Number.isFinite(t?.x) || !Number.isFinite(t?.y)) return;
    const last = trail.current[trail.current.length - 1];
    if (!last || Math.hypot(t.x - last.x, t.y - last.y) > 0.05) {
      trail.current.push({ x: t.x, y: t.y });
      if (trail.current.length > 1200) trail.current.shift();
    }
  }, [props.telemetry]);
  const world = useMemo(() => props.world ? { ...props.world, racks: props.world.racks ?? [],
    features: props.world.features ?? [], bays: props.world.bays ?? [], zones: props.world.zones ?? [] } : null, [props.world]);
  if (view === "2d") return <Map2D {...props} world={world} trailPoints={trail.current} />;
  return <Warehouse3D {...props} world={world} trailPoints={trail.current}
    goal={props.missionGoal} goalLabel={props.destinationBayId} className="h-full" />;
}
