"use client";
/**
 * Sovereign Autonomy live digital twin: a photoreal-styled 3D warehouse driven by the
 * simulator's world and telemetry, with the governance layer drawn into the
 * scene (planned route, people's safety zones, denied moves, the verdict).
 */
import { Component, Suspense, memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Environment, Html, Line, OrbitControls, PerspectiveCamera } from "@react-three/drei";
import { Bloom, EffectComposer, N8AO, SMAA, Vignette } from "@react-three/postprocessing";
import * as THREE from "three";
import { RiskHeatmap, RobotSafety, Trail, CameraFootprint, MiniMap } from "./MapLayers";
import { FrameBudget } from "./FrameBudget";
import { WarehouseToolbar } from "./WarehouseToolbar";
import { FacilityEnvironment } from "./FacilityEnvironment";
import { Forklift, Obstacle, FleetRobot, VERDICT_COLOURS, Worker, ZoneCones, ZoneMarking } from "./Actors";
import type { WorldLayout } from "./textures";
import { cameraObstacles, clearFollowCamera } from './cameraGeometry';


export type CameraMode = "overview" | "follow" | "robot";
type Pt = { x: number; y: number };
export type Detection = { label: string; conf: number; dist: number; box: [number, number, number, number]; kind: string };

export type TwinProps = {
  roofMode?: "auto" | "show" | "hide";
  pathPoints?: Pt[] | null;
  showHeatmap?: boolean;
  showTrail?: boolean;
  trailPoints?: Pt[];
  safetyState?: string;
  hoveredWaypointIdx?: number | null;
  riskCells?: Array<Pt & { risk: number }>;
  destinationBayId?: string | null;
  fullscreenTargetRef?: React.RefObject<HTMLElement | null>;
  world: any | null;
  telemetry: any | null;
  verdict?: string | null; // APPROVED | NEEDS_REVIEW | DENIED
  verdictText?: string | null;
  proposal?: { intent?: string; params?: any; rationale?: string } | null;
  planWaypoints?: Array<Pt & { max_speed?: number }> | null;
  executedPath?: Pt[];
  goal?: Pt | null;
  goalLabel?: string | null;
  mode?: CameraMode;
  onModeChange?: (m: CameraMode) => void;
  overlay?: boolean;
  className?: string;
  quality?: "high" | "low";
  pickingGoal?: boolean;
  onGoalPick?: (point: Pt) => void;
};

/* ───────────────────────── camera rigs ───────────────────────── */

function CameraRig({ mode, robot, center, reset, span, focus, eyeHeight, world }: { world: any; eyeHeight: number; span: number; focus: Pt | null; reset: number; mode: CameraMode; robot: React.MutableRefObject<{ x: number; y: number; theta: number }>; center: THREE.Vector3 }) {
  const { camera } = useThree();
  const look = useRef(new THREE.Vector3().copy(center));
  const pos = useRef(new THREE.Vector3());
  const lookTarget = useRef(new THREE.Vector3());
  const snap = useRef(true);
  const cameraBoxes = useMemo(() => cameraObstacles(world), [world]);
  useEffect(() => {
    const cam = camera as THREE.PerspectiveCamera;
    cam.fov = mode === "robot" ? 78 : mode === "follow" ? 55 : 42;
    cam.near = mode === "robot" ? 0.05 : 0.1;
    cam.far = Math.max(200, span * 5);
    cam.updateProjectionMatrix();
    snap.current = true;
    if (mode === "overview") {
      const target = focus ? lookTarget.current.set(focus.x, 0, -focus.y) : center;
      cam.position.set(target.x + span * 0.225, span * 0.78, target.z + span * 0.6);
      cam.lookAt(target);
    }
  }, [mode, camera, center, reset, span, focus]);
  useFrame((_, dt) => {
    if (mode === "overview") return;
    const r = robot.current;
    const fx = Math.cos(r.theta), fz = -Math.sin(r.theta);
    const k = 1 - Math.exp(-(mode === "robot" ? 14 : 3.5) * Math.min(dt, 0.1));
    if (mode === "follow") {
      pos.current.set(r.x - fx * 3.8, 2.15, -r.y - fz * 3.8);
      look.current.lerp(lookTarget.current.set(r.x + fx * .8, 0.7, -r.y + fz * .8), snap.current ? 1 : k);
    } else {
      pos.current.set(r.x + fx * 0.37, eyeHeight, -r.y + fz * 0.37);
      look.current.set(r.x + fx * 6, eyeHeight-.05, -r.y + fz * 6);
    }
    camera.position.lerp(pos.current, mode === "robot" || snap.current ? 1 : k);
    if (mode === 'follow') {
      const safe = clearFollowCamera({x:r.x,y:.85,z:-r.y}, camera.position, cameraBoxes, world.geofence);
      camera.position.set(safe.x,safe.y,safe.z);
    }
    snap.current = false;
    camera.lookAt(look.current);
  });
  return null;
}

/** True when the sight line crosses racking (racks are taller than everything we detect). */
function blockedByRack(ax: number, ay: number, bx: number, by: number, racks: { x1: number; x2: number; y: number; depth?: number }[]) {
  for (const r of racks) {
    const x0 = r.x1 + 0.05, x1 = r.x2 - 0.05, y0 = r.y + 0.05, y1 = r.y + (r.depth ?? 1) - 0.05;
    let t0 = 0, t1 = 1;
    const dx = bx - ax, dy = by - ay;
    const clip = (p: number, q: number) => {
      if (p === 0) return q >= 0;
      const t = q / p;
      if (p < 0) { if (t > t1) return false; if (t > t0) t0 = t; }
      else { if (t < t0) return false; if (t < t1) t1 = t; }
      return true;
    };
    if (clip(-dx, ax - x0) && clip(dx, x1 - ax) && clip(-dy, ay - y0) && clip(dy, y1 - ay) && t0 <= t1) return true;
  }
  return false;
}

/* ─────────────── robot-eye detections (projected to screen) ─────────────── */

function DetectionProbe({ active, items, onDetections, racks }: { racks: { x1: number; x2: number; y: number; depth?: number }[]; active: boolean; items: { kind: string; label: string; x: number; y: number; w: number; h: number; conf: number }[]; onDetections: (d: Detection[]) => void }) {
  const { camera, size } = useThree();
  const last = useRef(0);
  useFrame(({ clock }) => {
    if (!active || clock.elapsedTime - last.current < 0.15) return;
    last.current = clock.elapsedTime;
    const out: Detection[] = [];
    const camPos = camera.position;
    const fwd = new THREE.Vector3();
    camera.getWorldDirection(fwd);
    for (const it of items) {
      const c = new THREE.Vector3(it.x, it.h / 2, -it.y);
      const rel = c.clone().sub(camPos);
      const dist = rel.length();
      if (dist > 16 || rel.dot(fwd) < 0.3) continue;
      if (blockedByRack(camPos.x, -camPos.z, it.x, it.y, racks)) continue;
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      for (const dx of [-it.w / 2, it.w / 2])
        for (const dz of [-it.w / 2, it.w / 2])
          for (const yy of [0, it.h]) {
            const p = new THREE.Vector3(it.x + dx, yy, -it.y + dz).project(camera);
            const sx = ((p.x + 1) / 2) * size.width, sy = ((1 - p.y) / 2) * size.height;
            x0 = Math.min(x0, sx); x1 = Math.max(x1, sx); y0 = Math.min(y0, sy); y1 = Math.max(y1, sy);
          }
      if (x1 < 0 || y1 < 0 || x0 > size.width || y0 > size.height) continue;
      out.push({ kind: it.kind, label: it.label, conf: it.conf, dist, box: [Math.max(0, x0), Math.max(0, y0), Math.min(size.width, x1), Math.min(size.height, y1)] });
    }
    onDetections(out.sort((a, b) => a.dist - b.dist).slice(0, 6));
  });
  return null;
}

/* ───────────────────────── governance overlay ───────────────────────── */

function SafetyZones({ people, robot, stop, slow }: { people: Pt[]; robot: Pt; stop: number; slow: number }) {
  return (
    <group>
      {people.map((p, i) => {
        const d = Math.hypot(p.x - robot.x, p.y - robot.y);
        if (d > Math.max(9, slow + 1)) return null;
        return (
          <group key={i} position={[p.x, 0.018, -p.y]} rotation={[-Math.PI / 2, 0, 0]}>
            <mesh>
              <circleGeometry args={[stop, 48]} />
              <meshBasicMaterial color="#ef4444" transparent opacity={d < stop ? 0.32 : 0.16} depthWrite={false} toneMapped={false} />
            </mesh>
            <mesh>
              <ringGeometry args={[slow - 0.06, slow, 64]} />
              <meshBasicMaterial color="#f59e0b" transparent opacity={0.7} depthWrite={false} toneMapped={false} />
            </mesh>
            <mesh>
              <ringGeometry args={[stop - 0.03, stop + 0.03, 48]} />
              <meshBasicMaterial color="#ef4444" transparent opacity={0.9} depthWrite={false} toneMapped={false} />
            </mesh>
          </group>
        );
      })}
    </group>
  );
}

function GoalMarker({ goal, label }: { goal: Pt; label?: string | null }) {
  const ring = useRef<THREE.Mesh>(null!);
  useFrame(({ clock }) => {
    const s = 1 + 0.25 * ((clock.elapsedTime * 0.8) % 1);
    if (ring.current) {
      ring.current.scale.set(s, s, s);
      (ring.current.material as THREE.MeshBasicMaterial).opacity = 0.9 - 0.8 * ((clock.elapsedTime * 0.8) % 1);
    }
  });
  return (
    <group position={[goal.x, 0.02, -goal.y]}>
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[0.5, 0.58, 48]} />
        <meshBasicMaterial color="#10b981" transparent opacity={0.95} toneMapped={false} />
      </mesh>
      <mesh ref={ring} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[0.6, 0.66, 48]} />
        <meshBasicMaterial color="#10b981" transparent opacity={0.6} toneMapped={false} />
      </mesh>
      <Html position={[0, 1.2, 0]} center distanceFactor={14} zIndexRange={[10, 0]}>
        <div style={{ background: "rgba(6,78,59,.9)", color: "#d1fae5", font: "600 12px system-ui", padding: "3px 8px", borderRadius: 6, whiteSpace: "nowrap", border: "1px solid #10b981" }}>
          GOAL {label ?? ""}
        </div>
      </Html>
    </group>
  );
}

/* ───────────────────────────── scene ───────────────────────────── */

type Selection = { kind: "robot" | "person" | "obstacle"; index: number };

function Scene(props: TwinProps & { focus: Pt | null; onCameraFootprint: (points: Pt[]) => void; reset: number; stop: number | null; slow: number | null; onSelect: (s: Selection) => void; mode: CameraMode; onDetections: (d: Detection[]) => void; robotPose: React.MutableRefObject<{ x: number; y: number; theta: number }> }) {
  const { world, telemetry, verdict, verdictText, proposal, planWaypoints, executedPath, goal, goalLabel, mode, overlay = true, quality = "high" } = props;
  const [waypoint, setWaypoint] = useState<number | null>(null);
  const layout: WorldLayout = world;
  const g = layout.geofence;
  const span = Math.max(g.max_x - g.min_x, g.max_y - g.min_y);
  const center = useMemo(() => new THREE.Vector3((g.min_x + g.max_x) / 2, 0, -(g.min_y + g.max_y) / 2), [g]);

  const rx = telemetry?.x ?? 3, ry = telemetry?.y ?? 3.5, rth = telemetry?.theta ?? 0;
  const obstacles: any[] = telemetry?.obstacles ?? world?.obstacles ?? [];
  const peopleRaw: any[] = telemetry?.walking_humans ?? world?.walking_humans ?? [];
  const people = useMemo(() => {
    const out = [...peopleRaw];
    const h = telemetry?.human ?? world?.human;
    if (h && !out.some((p) => Math.hypot(p.x - h.x, p.y - h.y) < 0.2)) out.push({ ...h, name: h.name ?? "Worker" });
    return out;
  }, [peopleRaw, telemetry?.human, world?.human]);
  const idle: any[] = telemetry?.idle_robots ?? world?.idle_robots ?? [];
  const forklifts = obstacles.filter((o) => o.type === "forklift");
  const zones: any[] = telemetry?.site_constraints ?? [];
  const statics = obstacles.filter((o) => o.type !== "forklift");
  // An approved WAIT is the robot holding on purpose (e.g. for a hazard), not a normal approval
  const holding = verdict === "APPROVED" && proposal?.intent === "WAIT";
  const v = holding ? "HOLDING" : verdict ?? "IDLE";

  const ghostTarget = proposal?.intent === "MOVE_TO" && v !== "APPROVED" && proposal?.params && typeof proposal.params.x === "number" ? { x: proposal.params.x, y: proposal.params.y } : null;
  const destination = layout.bays.find(b => b.id === props.destinationBayId);
  const nearestPerson = people.reduce((m: number, p: any) => Math.min(m, Math.hypot(p.x - rx, p.y - ry)), 999);

  const detItems = useMemo(() => [
    ...people.map((p: any) => ({ kind: "person", label: "person", x: p.x, y: p.y, w: 0.6, h: 1.8, conf: p.conf ?? 0.9 })),
    ...forklifts.map((f: any) => ({ kind: "forklift", label: "forklift", x: f.x, y: f.y, w: 2.2, h: 2.6, conf: 0.93 })),
    ...statics.filter((o: any) => ["spill", "dropped_pallet", "pallet", "tote_stack", "handcart"].includes(o.type)).map((o: any) => ({
      kind: o.type, label: o.type.replace("_", " "), x: o.x, y: o.y, w: Math.max(0.6, o.r * 2.4), h: o.type === "spill" ? 0.05 : o.type === "pallet" ? 1.25 : 0.9, conf: 0.88,
    })),
  ], [people, forklifts, statics]);

  return (
    <>
      <color attach="background" args={["#b9c6d3"]} />
      <fog attach="fog" args={["#becbd6", span * 0.95, span * 2.5]} />
      <hemisphereLight args={["#ffffff", "#8b8a86", mode === "robot" ? 0.8 : 0.55]} />
      <directionalLight position={[center.x - 15, 18, center.z - 12]} intensity={0.35} color="#d9eaff" />
      <directionalLight
        position={[center.x + 6, 30, center.z + 8]}
        intensity={1.5}
        color="#fff6e8"
        castShadow={quality === "high"}
        shadow-mapSize={[quality === "high" ? 2048 : 1024, quality === "high" ? 2048 : 1024]}
        shadow-camera-left={-26}
        shadow-camera-right={26}
        shadow-camera-top={18}
        shadow-camera-bottom={-18}
        shadow-camera-near={1}
        shadow-camera-far={60}
        shadow-bias={-0.0004}
        shadow-normalBias={0.03}
        target-position={[center.x, 0, center.z]}
      />
      <Suspense fallback={null}>
        <WarehouseEnvironment />
      </Suspense>

      <FacilityEnvironment world={layout} roofMode={props.roofMode} />
      {props.pickingGoal && mode === "overview" && <mesh position={[center.x, 0.045, center.z]} rotation={[-Math.PI / 2, 0, 0]} onClick={(e) => {
        if (e.delta > 5) return;
        e.stopPropagation();
        props.onGoalPick?.({ x: Math.round(e.point.x * 100) / 100, y: Math.round(-e.point.z * 100) / 100 });
      }}><planeGeometry args={[g.max_x - g.min_x, g.max_y - g.min_y]} /><meshBasicMaterial color="#38bdf8" transparent opacity={0.07} depthWrite={false} /></mesh>}

      {statics.map((o, i) => (
        <group key={`${o.type}-${i}`} onClick={(e) => { e.stopPropagation(); props.onSelect({ kind: "obstacle", index: obstacles.indexOf(o) }); }}><Obstacle o={o} /></group>
      ))}
      {zones.filter((z: any) => z.radius > 0).map((z: any) => (
        <ZoneCones key={`cones-${z.id}-${z.radius}`} zone={z} racks={layout.racks} bounds={g} />
      ))}
      {forklifts.map((f, i) => (
        <group key={`fl-${i}`} onClick={(e) => { e.stopPropagation(); props.onSelect({ kind: "obstacle", index: obstacles.indexOf(f) }); }}><Forklift x={f.x} y={f.y} heading={f.heading ?? 0} /></group>
      ))}
      {people.map((p: any, i: number) => (
        <group key={p.name ?? i} onClick={(e) => { e.stopPropagation(); props.onSelect({ kind: "person", index: i }); }}><Worker heading={p.heading} label={mode !== "robot" ? p.name ?? p.label ?? `Worker ${i + 1}` : undefined} id={p.name ?? String(i)} x={p.x} y={p.y} highlight={overlay && props.slow !== null && Math.hypot(p.x - rx, p.y - ry) < props.slow} /></group>
      ))}
      {idle.map((r: any, i: number) => (
        <FleetRobot robot_kind={r.robot_kind} key={`idle-${i}`} x={r.x} y={r.y} theta={r.theta ?? 0} verdict={r.speed>.01?"APPROVED":"IDLE"} idle={!(r.speed>.01)} label={mode !== "robot" ? r.label ?? r.robot_id ?? `Robot ${i + 2}` : undefined} />
      ))}
      <group onClick={(e) => { e.stopPropagation(); props.onSelect({ kind: "robot", index: 0 }); }}><FleetRobot robot_kind={telemetry?.robot_kind} x={rx} y={ry} theta={rth} verdict={v} pose={props.robotPose} /></group>

      {overlay && (
        <group>
          {props.showHeatmap && <RiskHeatmap bounds={g} human={telemetry?.human ?? world?.human ?? null} obstacles={obstacles} riskCells={props.riskCells ?? []} />}
          {props.showTrail && <Trail points={props.trailPoints ?? []} />}
          <RobotSafety robot={{ x: rx, y: ry }} state={props.safetyState ?? "OK"} />
          {props.pathPoints && props.pathPoints.length > 1 && <Line points={props.pathPoints.map(p => [p.x, 0.028, -p.y])} color="#3b82f6" lineWidth={2.5} dashed dashSize={0.4} gapSize={0.2} />}
          <Line points={[[g.min_x, 0.015, -g.min_y], [g.max_x, 0.015, -g.min_y], [g.max_x, 0.015, -g.max_y], [g.min_x, 0.015, -g.max_y], [g.min_x, 0.015, -g.min_y]]} color="#64748b" lineWidth={2} />
          {planWaypoints && planWaypoints.length > 0 && (
            <Line points={[[rx, 0.03, -ry], ...planWaypoints.map((w) => [w.x, 0.03, -w.y] as [number, number, number])]} color="#a855f7" lineWidth={3.5} dashed dashSize={0.5} gapSize={0.3} transparent opacity={0.95} />
          )}
          {planWaypoints?.map((w, i) => <group key={i} position={[w.x, 0.12, -w.y]}>
            <mesh onClick={(e) => { e.stopPropagation(); setWaypoint(waypoint === i ? null : i); }}>
              <sphereGeometry args={[waypoint === i || props.hoveredWaypointIdx === i ? 0.22 : 0.13, 10, 8]} />
              <meshBasicMaterial color={waypoint === i || props.hoveredWaypointIdx === i ? "#ffffff" : "#a855f7"} toneMapped={false} />
            </mesh>
            {(waypoint === i || props.hoveredWaypointIdx === i) && <Html position={[0, 0.65, 0]} center zIndexRange={[20, 0]}><div className="whitespace-nowrap rounded bg-slate-950/95 border border-cyan-600 p-2 text-xs text-white">Waypoint {i + 1} · {w.x.toFixed(1)}, {w.y.toFixed(1)} m<br />Speed cap: {w.max_speed?.toFixed(2) ?? "unspecified"} m/s</div></Html>}
          </group>)}
          {executedPath && executedPath.length > 1 && (
            <Line points={executedPath.map((p) => [p.x, 0.025, -p.y] as [number, number, number])} color="#22c55e" lineWidth={2.5} transparent opacity={0.6} />
          )}
          {goal && <GoalMarker goal={goal} label={goalLabel} />}
          {destination && (!goal || Math.hypot(goal.x - destination.x, goal.y - destination.y) > 0.01) && <GoalMarker goal={destination} label={`DEST ${destination.id}`} />}
          {props.stop !== null && props.slow !== null && <SafetyZones people={people} robot={{ x: rx, y: ry }} stop={props.stop} slow={props.slow} />}
          {zones.map((z: any) => (
            <group key={`zm-${z.id}`}>
              <ZoneMarking zone={z} />
              <Html position={[z.x, 1.3, -z.y]} center distanceFactor={14} zIndexRange={[15, 0]}>
                {z.radius > 0.1 ? (
                  <div style={{ background: "rgba(127,29,29,.92)", color: "#fee2e2", font: "700 11px system-ui", padding: "3px 8px", borderRadius: 6, whiteSpace: "nowrap", border: "1px solid #ef4444", pointerEvents: "none" }}>
                    NO ENTRY · {z.label ?? "hazard"} · {Number(z.radius).toFixed(1)} m
                  </div>
                ) : (
                  <div style={{ background: "rgba(120,53,15,.92)", color: "#fef3c7", font: "700 11px system-ui", padding: "3px 8px", borderRadius: 6, whiteSpace: "nowrap", border: "1px solid #f59e0b", pointerEvents: "none" }}>
                    SLOW · {z.label ?? "vision sighting"} · ≤{Number(z.max_speed).toFixed(1)} m/s
                  </div>
                )}
              </Html>
            </group>
          ))}
          {ghostTarget && (
            <>
              <FleetRobot robot_kind={telemetry?.robot_kind} x={ghostTarget.x} y={ghostTarget.y} theta={Math.atan2(ghostTarget.y - ry, ghostTarget.x - rx)} verdict={v} ghost />
              <Line points={[[rx, 0.05, -ry], [ghostTarget.x, 0.05, -ghostTarget.y]]} color={VERDICT_COLOURS[v]} lineWidth={2} dashed dashSize={0.2} gapSize={0.15} />
            </>
          )}
          {mode !== "robot" && (
            <Html position={[rx, 1.55, -ry]} center zIndexRange={[20, 0]}>
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2, pointerEvents: "none" }}>
                <div style={{ background: VERDICT_COLOURS[v] ?? "#38bdf8", color: "#0b0b0b", font: "800 12px system-ui", padding: "3px 9px", borderRadius: 6, whiteSpace: "nowrap", boxShadow: "0 2px 10px rgba(0,0,0,.35)" }}>
                  {props.safetyState ?? (v === "IDLE" ? "STANDBY" : v.replace("_", " "))} · {Number(telemetry?.speed ?? 0).toFixed(2)} m/s
                  {nearestPerson < 6 ? ` · person ${nearestPerson.toFixed(1)} m` : ""}
                </div>
                {verdictText && v !== "APPROVED" && v !== "IDLE" && (
                  <div style={{ background: "rgba(15,23,42,.88)", color: "#e2e8f0", font: "500 11px system-ui", padding: "2px 8px", borderRadius: 5, maxWidth: 260, textAlign: "center" }}>{holding ? proposal?.rationale : verdictText}</div>
                )}
              </div>
            </Html>
          )}
        </group>
      )}

      <CameraRig world={layout} eyeHeight={telemetry?.robot_kind === "humanoid" ? 1.61 : .76} mode={mode} robot={props.robotPose} center={center} reset={props.reset} span={span} focus={props.focus} />
      <CameraFootprint onChange={props.onCameraFootprint} />
      <DetectionProbe active={mode === "robot"} items={detItems} onDetections={props.onDetections} racks={layout.racks} />
      {mode === "overview" && <OrbitControls key={props.reset} target={props.focus ? [props.focus.x, 0, -props.focus.y] : center} maxPolarAngle={Math.PI / 2.15} minDistance={4} maxDistance={span * 2} enableDamping />}

      {quality === "high" ? (
        <EffectComposer multisampling={0} enableNormalPass={false}>
          <N8AO aoRadius={1.2} intensity={2.2} distanceFalloff={0.6} quality="medium" halfRes />
          <Bloom mipmapBlur luminanceThreshold={1.0} intensity={0.55} radius={0.6} />
            <SMAA />
          <Vignette offset={0.25} darkness={mode === "robot" ? 0.2 : 0.4} />
        </EffectComposer>
      ) : null}
    </>
  );
}

function WarehouseEnvironment() {
  const [file, setFile] = useState<string | null>(null);
  useEffect(() => {
    let ok = true;
    // Optional IBL must not make the locally bundled scene depend on a CDN.
    // Remote presets retain the existing local hemisphere/directional lights.
    import("@pmndrs/assets/hdri/warehouse.exr").then((m) => {
      const url = new URL(m.default, window.location.href);
      if (ok && url.origin === window.location.origin) setFile(url.href);
    }).catch(() => {});
    return () => {
      ok = false;
    };
  }, []);
  if (!file) return null;
  return <Environment files={file} environmentIntensity={0.55} />;
}

/* ───────────────────────────── shell ───────────────────────────── */

const MODES: { key: CameraMode; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "follow", label: "Follow" },
  { key: "robot", label: "Robot eye" },
];

class RenderBoundary extends Component<{ children: React.ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    return this.state.failed ? <div role="alert" className="p-8 text-slate-200">3D rendering is unavailable. Try reloading or use the dashboard’s 2D map. <button className="underline" onClick={() => window.location.reload()}>Reload</button></div> : this.props.children;
  }
}

function ContextMonitor({ onLost }: { onLost: (lost: boolean) => void }) {
  const { gl } = useThree();
  useEffect(() => {
    const lost = (e: Event) => { e.preventDefault(); onLost(true); };
    const restored = () => onLost(false);
    gl.domElement.addEventListener("webglcontextlost", lost);
    gl.domElement.addEventListener("webglcontextrestored", restored);
    return () => {
      gl.domElement.removeEventListener("webglcontextlost", lost);
      gl.domElement.removeEventListener("webglcontextrestored", restored);
    };
  }, [gl, onLost]);
  return null;
}

/** Lighting is fixed: reuse the shadow map between actor updates instead of
 * rendering the entire warehouse a second time on every display frame. */
function ShadowBudget({ enabled }: { enabled: boolean }) {
  const { gl } = useThree();
  const elapsed = useRef(0);
  useEffect(() => {
    gl.shadowMap.autoUpdate = false;
    gl.shadowMap.needsUpdate = enabled;
    elapsed.current = 1;
    return () => { gl.shadowMap.autoUpdate = true; };
  }, [gl, enabled]);
  useFrame((_, dt) => {
    if (!enabled || document.hidden) return;
    elapsed.current += dt;
    if (elapsed.current >= 1 / 15) {
      gl.shadowMap.needsUpdate = true;
      elapsed.current = 0;
    }
  });
  return null;
}

const DET_COLOURS: Record<string, string> = { person: "#f97316", forklift: "#facc15", spill: "#38bdf8", dropped_pallet: "#f43f5e" };

export default function Warehouse3D(props: TwinProps) {
  const [modeLocal, setModeLocal] = useState<CameraMode>(() => {
    const q = typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("cam") : null;
    return props.mode ?? (q === "follow" || q === "robot" ? q : "overview");
  });
  const normalizedWorld = useMemo(() => props.world ? { ...props.world, racks: props.world.racks ?? [], features: props.world.features ?? [], bays: props.world.bays ?? [], zones: props.world.zones ?? [] } : null, [props.world]);
  const mode = props.pickingGoal ? "overview" : props.mode ?? modeLocal;
  const setMode = (m: CameraMode) => (props.onModeChange ? props.onModeChange(m) : setModeLocal(m));
  const [overlay, setOverlay] = useState(props.overlay ?? true);
  const [dets, setDets] = useState<Detection[]>([]);
  const containerRef = useRef<HTMLDivElement>(null);
  const [fullscreen, setFullscreen] = useState(() => typeof document !== "undefined" && !!document.fullscreenElement);
  const [fullscreenError, setFullscreenError] = useState<string | null>(null);
  const [showMap, setShowMap] = useState(true);
  const [cameraFootprint, setCameraFootprint] = useState<Pt[]>([]);
  const [focus, setFocus] = useState<Pt | null>(null);
  const [heatmapLocal, setHeatmapLocal] = useState(true);
  const [trailLocal, setTrailLocal] = useState(true);
  const heatmap = props.showHeatmap ?? heatmapLocal;
  const trail = props.showTrail ?? trailLocal;
  const liveTrail = useRef<Pt[]>([]);
  useEffect(() => {
    const t = props.telemetry;
    if (!Number.isFinite(t?.x) || !Number.isFinite(t?.y)) return;
    const last = liveTrail.current[liveTrail.current.length - 1];
    if (!last || Math.hypot(t.x - last.x, t.y - last.y) > 0.05) {
      liveTrail.current.push({ x: t.x, y: t.y });
      if (liveTrail.current.length > 1200) liveTrail.current.shift();
    }
  }, [props.telemetry]);
  useEffect(() => {
    const update = () => {
      const target = props.fullscreenTargetRef?.current ?? containerRef.current;
      setFullscreen(!!target && document.fullscreenElement === target);
    };
    document.addEventListener("fullscreenchange", update);
    return () => document.removeEventListener("fullscreenchange", update);
  }, [props.fullscreenTargetRef]);
  const toggleFullscreen = async () => {
    try {
      setFullscreenError(null);
      if (document.fullscreenElement) await document.exitFullscreen();
      else await (props.fullscreenTargetRef?.current ?? containerRef.current)?.requestFullscreen();
    } catch { setFullscreenError("Fullscreen is unavailable in this browser."); }
  };
  const resolvedGoal = props.goal ?? props.planWaypoints?.[props.planWaypoints.length - 1] ?? props.telemetry?.target ?? null;
  const robotPose = useRef({ x: 3, y: 3.5, theta: 0 });
  const v = props.verdict === "APPROVED" && props.proposal?.intent === "WAIT" ? "HOLDING" : props.verdict ?? "IDLE";
  const [qualityChoice, setQualityChoice] = useState<"auto" | "high" | "low">(() => props.quality ?? (typeof window !== "undefined" && new URLSearchParams(window.location.search).get("q") === "low" ? "low" : "auto"));
  // Start with the inexpensive profile so first load is responsive on integrated GPUs.
  // High remains an explicit choice; Auto never enables costly effects before measuring.
  const [autoLow, setAutoLow] = useState(true);
  const [fps, setFps] = useState<number | null>(null);
  const [showRoutes, setShowRoutes] = useState(true);
  const [roofMode,setRoofMode] = useState<"auto" | "show" | "hide">("auto");
  const quality = qualityChoice === "auto" ? (autoLow ? "low" : "high") : qualityChoice;
  const onFrameSample = useCallback((value: number) => { setFps(value); if (value < 35) setAutoLow(true); }, []);
  useEffect(() => { if (props.pickingGoal) setMode("overview"); }, [props.pickingGoal]);
  const [reset, setReset] = useState(0);
  const [contextLost, setContextLost] = useState(false);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [lastUpdate, setLastUpdate] = useState<number | null>(null);
  const [now, setNow] = useState(Date.now());
  const [policy, setPolicy] = useState<{ stop: number; slow: number } | null>(null);
  useEffect(() => {
    if (props.telemetry) {
      const timestamp = Number(props.telemetry.timestamp)*1000;
      setLastUpdate(Number.isFinite(timestamp)?Math.min(timestamp,Date.now()):Date.now());
    }
  }, [props.telemetry]);
  useEffect(() => { if (props.quality) setQualityChoice(props.quality); }, [props.quality]);
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  useEffect(() => {
    let live = true;
    const controller = new AbortController();
    const refresh = async () => {
      try {
        const res = await fetch(`${process.env.NEXT_PUBLIC_API_BASE || "/api"}/policies/active`, { cache: "no-store", signal: controller.signal });
        if (!res.ok) throw new Error("Policy unavailable");
        const { parameters: p } = await res.json();
        const stop = p.HUMAN_STOP_RADIUS_M, slow = p.HUMAN_SLOW_RADIUS_M;
        if (!Number.isFinite(stop) || !Number.isFinite(slow) || stop <= 0 || slow <= stop) throw new Error("Invalid policy");
        if (live) setPolicy({ stop, slow });
      } catch { if (live) setPolicy(null); }
    };
    void refresh();
    const id = window.setInterval(refresh, 5000);
    return () => { live = false; controller.abort(); window.clearInterval(id); };
  }, []);
  const age = lastUpdate === null ? null : Math.max(0, Math.floor((now - lastUpdate) / 1000));
  const people = [...(props.telemetry?.walking_humans ?? props.world?.walking_humans ?? [])];
  const human = props.telemetry?.human ?? props.world?.human;
  if (human && !people.some((p: Pt) => Math.hypot(p.x - human.x, p.y - human.y) < 0.2)) people.push(human);
  const obstacles = props.telemetry?.obstacles ?? props.world?.obstacles ?? [];
  const selected = selection?.kind === "robot" ? props.telemetry : selection?.kind === "person" ? people[selection.index] : selection ? obstacles[selection.index] : null;
  const distance = selected && props.telemetry ? Math.hypot(selected.x - props.telemetry.x, selected.y - props.telemetry.y) : null;
  const nearestClearance = props.telemetry ? Math.min(...people.map((p: Pt) => Math.hypot(p.x - props.telemetry.x, p.y - props.telemetry.y)), ...obstacles.map((o: any) => Math.max(0, Math.hypot(o.x - props.telemetry.x, o.y - props.telemetry.y) - (o.r ?? 0)))) : Infinity;

  if (!props.world?.geofence) {
    return (
      <div className={`flex items-center justify-center bg-slate-900 text-slate-400 text-sm ${props.className ?? ""}`} style={{ minHeight: 360 }}>
        Waiting for the warehouse simulator…
      </div>
    );
  }

  return (
    <div ref={containerRef} className={`warehouse-view ${props.className ?? ""}`} style={{ minHeight: 240, ...(fullscreen ? { height: "100vh" } : {}) }}>
      <WarehouseToolbar mode={mode} setMode={setMode} age={age} fullscreen={fullscreen} toggleFullscreen={toggleFullscreen}
        reset={()=>{setFocus(null);setReset(n=>n+1);}} inspect={()=>setSelection({kind:"robot",index:0})}
        showMap={showMap} toggleMap={()=>setShowMap(!showMap)} heatmap={heatmap} trail={trail}
        toggleHeatmap={props.showHeatmap===undefined?()=>setHeatmapLocal(!heatmap):undefined}
        toggleTrail={props.showTrail===undefined?()=>setTrailLocal(!trail):undefined}
        overlay={overlay} toggleOverlay={()=>setOverlay(!overlay)} waypoints={props.planWaypoints?.length||0}
        showRoutes={showRoutes} toggleRoutes={()=>setShowRoutes(!showRoutes)} qualityChoice={qualityChoice}
        setQuality={(q:"auto"|"high"|"low")=>{setQualityChoice(q);setAutoLow(true);}} quality={quality} fps={fps}
        cleanroom={props.world.racks?.some((r:any)=>r.kind==='partition')} roofMode={roofMode} setRoofMode={setRoofMode}/>
      <div className="warehouse-scene">
      <RenderBoundary><Canvas fallback={<div className="p-8 text-slate-200">WebGL is unavailable. Use the dashboard’s 2D map.</div>} shadows={quality === "high"} dpr={quality === "low" ? 1 : [1, 1.5]} gl={{ antialias: true, powerPreference: "high-performance" }} onCreated={({ gl }) => {
        gl.toneMapping = THREE.ACESFilmicToneMapping;
        gl.toneMappingExposure = 1.05;
        gl.shadowMap.type = THREE.PCFSoftShadowMap;
      }}>
        <PerspectiveCamera makeDefault position={[29, 31, 11.5]} fov={42} near={0.1} far={200} />
        <ContextMonitor onLost={setContextLost} />
        <ShadowBudget enabled={quality === "high"} />
        <FrameBudget onSample={onFrameSample} />
        <Scene {...props} roofMode={roofMode} world={normalizedWorld} goal={resolvedGoal} goalLabel={props.destinationBayId ?? props.goalLabel} showHeatmap={heatmap} showTrail={trail} trailPoints={props.trailPoints ?? liveTrail.current} focus={focus} onCameraFootprint={setCameraFootprint} pathPoints={showRoutes ? props.pathPoints : null} planWaypoints={showRoutes ? props.planWaypoints : null} executedPath={showRoutes ? props.executedPath : undefined} quality={quality} reset={reset} stop={policy?.stop ?? null} slow={policy?.slow ?? null} onSelect={setSelection} mode={mode} overlay={overlay} onDetections={setDets} robotPose={robotPose} />
      </Canvas></RenderBoundary>
      {contextLost && <div role="alert" className="absolute inset-0 z-30 grid place-items-center bg-slate-950/95 text-white">Graphics connection lost. <button className="underline" onClick={() => window.location.reload()}>Reload 3D view</button></div>}

      {fullscreenError && <p role="alert" className="absolute bottom-36 left-3 rounded bg-red-950/90 p-2 text-xs text-red-200">{fullscreenError}</p>}
      {showMap && <MiniMap world={{ ...props.world, racks: props.world.racks ?? [] }} telemetry={props.telemetry} points={cameraFootprint} onNavigate={(point) => { setMode("overview"); setFocus(point); setReset(n => n + 1); }} />}
      <output aria-label="Warehouse map status" className="sr-only">Execution {props.safetyState ?? "OK"}. Heatmap {heatmap ? "on" : "off"}. Trail {trail ? "on" : "off"}. Proposed path {props.pathPoints?.length ?? 0} points. Recorded plan {props.planWaypoints?.length ?? 0} waypoints. Executed path {props.executedPath?.length ?? 0} points. Risk cells {props.riskCells?.length ?? 0}. Trail samples {(props.trailPoints ?? liveTrail.current).length}.</output>
      {selection && <div className="absolute right-3 top-3 z-20 max-w-[240px] rounded-lg border border-white/20 bg-slate-950/95 p-3 text-xs text-slate-200" aria-live="polite">
        <button aria-label="Close inspection" className="float-right ml-4" onClick={() => setSelection(null)}>×</button>
        <strong>{selection.kind === "robot" ? "Active robot" : selected?.name ?? selected?.type?.replaceAll("_", " ") ?? "Worker"}</strong>
        {selected ? <><p className="mt-2">Position: {Number(selected.x).toFixed(2)}, {Number(selected.y).toFixed(2)} m</p><p>Speed: {Number.isFinite(selected.speed) ? `${selected.speed.toFixed(2)} m/s` : "Unavailable"}</p>{selection.kind === "robot" ? <><p>Nearest person / obstacle edge: {Number.isFinite(nearestClearance) ? `${nearestClearance.toFixed(2)} m` : "None reported"}</p><p>Gate: {v}</p><p>{props.verdictText ?? props.proposal?.rationale ?? "No decision reported"}</p></> : <><p>Distance to robot: {distance?.toFixed(2) ?? "—"} m</p>{selected.activity && <p>Activity: {selected.activity.replaceAll("_", " ")}</p>}{selected.destination && <p>Destination: {selected.destination}</p>}</>}{age !== null && age >= 3 && <p className="text-amber-300">Stale telemetry</p>}</> : <p className="mt-2">Object no longer reported.</p>}
      </div>}
      {mode !== "robot" && <div className="absolute bottom-3 left-3 right-3 rounded bg-slate-950/85 p-2 text-[11px] text-slate-200 pointer-events-none">{overlay ? <><span className="text-red-300">Stop {policy ? `${policy.stop} m` : "unavailable"}</span> · <span className="text-amber-300">Slow {policy ? `${policy.slow} m` : "unavailable"}</span> · <span className="text-blue-300">Proposed path</span> · <span className="text-purple-300">Recorded plan</span> · <span className="text-green-300">Executed route / goal</span></> : "Governance layer hidden"}<span className="block text-slate-400">{props.world.geofence.max_x - props.world.geofence.min_x}×{props.world.geofence.max_y - props.world.geofence.min_y} m · {props.pickingGoal ? "Click open floor to choose a destination" : mode === "overview" ? "Drag to orbit · scroll to zoom · click actors or route points to inspect" : "Click an actor to inspect · Overview enables orbit controls"}</span></div>}
      {/* robot-eye heads-up display */}
      {mode === "robot" && (
        <div className="pointer-events-none absolute inset-0">
          {dets.map((d, i) => (
            <div key={i} className="absolute" style={{ left: d.box[0], top: d.box[1], width: d.box[2] - d.box[0], height: Math.max(8, d.box[3] - d.box[1]), border: `2px solid ${DET_COLOURS[d.kind] ?? "#a3e635"}`, borderRadius: 3 }}>
              <span className="absolute -top-5 left-0 text-[10px] font-bold px-1.5 py-0.5 rounded-sm text-slate-950 whitespace-nowrap" style={{ background: DET_COLOURS[d.kind] ?? "#a3e635" }}>
                {d.label} · {d.dist.toFixed(1)} m
              </span>
            </div>
          ))}
          <div className="absolute bottom-3 left-3 right-3 flex items-center justify-between">
            <div className="text-[10px] font-mono text-white/80 bg-black/50 px-2 py-1 rounded">CAM-FRONT · 78° · {props.telemetry?.speed?.toFixed?.(2) ?? "0.00"} m/s</div>
            <div className="text-xs font-extrabold px-3 py-1 rounded" style={{ background: VERDICT_COLOURS[v] ?? "#38bdf8", color: "#0b0b0b" }}>
              GATE: {v === "IDLE" ? "STANDBY" : v.replace("_", " ")} · {props.safetyState ?? "OK"}
            </div>
          </div>
          <div className="absolute bottom-12 left-3 text-[10px] font-mono text-cyan-200 bg-slate-950/80 rounded px-2 py-1 flex items-center gap-1">
            Simulated detections · projected from world state
          </div>
        </div>
      )}
      </div>
    </div>
  );
}
