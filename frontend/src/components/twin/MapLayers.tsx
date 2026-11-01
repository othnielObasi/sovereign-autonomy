"use client";

import { useLayoutEffect, useMemo, useRef } from "react";
import { Line } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";

export type Point = { x: number; y: number };
export type Bounds = { min_x: number; max_x: number; min_y: number; max_y: number };
export type RiskCell = Point & { risk: number };
const clamp = (n: number) => Math.max(0, Math.min(1, n));

function Cells({ cells, size, height, proximity = false }: { cells: RiskCell[]; size: number; height: number; proximity?: boolean }) {
  const mesh = useRef<THREE.InstancedMesh>(null!);
  useLayoutEffect(() => {
    const object = new THREE.Object3D();
    const color = new THREE.Color();
    cells.forEach((cell, i) => {
      object.position.set(cell.x + size / 2, height, -cell.y - size / 2);
      object.rotation.x = -Math.PI / 2; object.updateMatrix();
      mesh.current.setMatrixAt(i, object.matrix);
      color.set(proximity || cell.risk > 0.7 ? "#ef4444" : cell.risk > 0.4 ? "#f59e0b" : "#3b82f6");
      mesh.current.setColorAt(i, color.multiplyScalar(0.5 + clamp(cell.risk) * 0.5));
    });
    mesh.current.instanceMatrix.needsUpdate = true;
    if (mesh.current.instanceColor) mesh.current.instanceColor.needsUpdate = true;
    mesh.current.computeBoundingSphere();
  }, [cells, size, height, proximity]);
  return <instancedMesh ref={mesh} args={[undefined, undefined, cells.length]} frustumCulled={false}>
    <planeGeometry args={[size, size]} /><meshBasicMaterial transparent opacity={0.3} depthWrite={false} toneMapped={false} />
  </instancedMesh>;
}

/** Match the floor-plan proximity calculation, plus its 2 m governance cells. */
export function RiskHeatmap({ bounds, human, obstacles, riskCells }: { bounds: Bounds; human: Point | null; obstacles: any[]; riskCells: RiskCell[] }) {
  const { cells, step } = useMemo(() => {
    const step = Math.max(0.75, Math.max(bounds.max_x - bounds.min_x, bounds.max_y - bounds.min_y) / 60);
    const cells: RiskCell[] = [];
    const bump = (d: number, r: number, w: number) => clamp((r - d) / w);
    for (let x = bounds.min_x; x + step <= bounds.max_x; x += step) for (let y = bounds.min_y; y + step <= bounds.max_y; y += step) {
      const cx = x + step / 2, cy = y + step / 2;
      let risk = human ? 1.2 * bump(Math.hypot(cx - human.x, cy - human.y), 2.5, 1.2) : 0;
      for (const ob of obstacles) risk += 0.6 * bump(Math.hypot(cx - ob.x, cy - ob.y) - (ob.r ?? ob.radius ?? 0.4), 1.1, 0.9);
      risk += 0.35 * bump(Math.min(cx - bounds.min_x, bounds.max_x - cx, cy - bounds.min_y, bounds.max_y - cy), 0.6, 0.6);
      if (risk >= 0.05) cells.push({ x, y, risk: clamp(risk) });
    }
    return { cells, step };
  }, [bounds, human, obstacles]);
  return <group>{cells.length > 0 && <Cells cells={cells} size={step} height={0.011} proximity />}
    {riskCells.length > 0 && <Cells cells={riskCells} size={2} height={0.013} />}</group>;
}

export function RobotSafety({ robot, state }: { robot: Point; state: string }) {
  const color = state === "STOP" ? "#ef4444" : state === "SLOW" ? "#f59e0b" : state === "REPLAN" ? "#818cf8" : "#22c55e";
  return <mesh position={[robot.x, 0.019, -robot.y]} rotation={[-Math.PI / 2, 0, 0]}>
    <ringGeometry args={[0.75, 0.82, 48]} /><meshBasicMaterial color={color} transparent opacity={0.8} depthWrite={false} toneMapped={false} />
  </mesh>;
}

export function Trail({ points }: { points: Point[] }) {
  return points.length > 1 ? <Line points={points.map(p => [p.x, 0.021, -p.y])} color="#22d3ee" lineWidth={2} transparent opacity={0.4} /> : null;
}

export function CameraFootprint({ onChange }: { onChange: (p: Point[]) => void }) {
  const { camera } = useThree();
  const last = useRef(0);
  const ray = useMemo(() => new THREE.Raycaster(), []);
  const ground = useMemo(() => new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), []);
  useFrame(({ clock }) => {
    if (clock.elapsedTime - last.current < 0.5) return;
    last.current = clock.elapsedTime;
    const points: Point[] = [];
    for (const [x, y] of [[-1, 1], [1, 1], [1, -1], [-1, -1]]) {
      ray.setFromCamera(new THREE.Vector2(x, y), camera);
      const hit = ray.ray.intersectPlane(ground, new THREE.Vector3());
      if (hit) points.push({ x: hit.x, y: -hit.z });
    }
    onChange(points);
  });
  return null;
}

export function MiniMap({ world, telemetry, points, onNavigate }: { world: any; telemetry: any; points: Point[]; onNavigate: (p: Point) => void }) {
  const g: Bounds = world.geofence;
  const w = g.max_x - g.min_x, h = g.max_y - g.min_y;
  return <svg role="img" aria-label="Warehouse minimap; click to recenter Overview" viewBox={`${g.min_x} ${-g.max_y} ${w} ${h}`}
    className="absolute bottom-20 right-3 w-28 sm:w-36 h-20 sm:h-24 rounded border border-slate-500 bg-slate-950/90 cursor-crosshair"
    preserveAspectRatio="none" onClick={e => {
      const rect = e.currentTarget.getBoundingClientRect();
      onNavigate({ x: g.min_x + (e.clientX - rect.left) / rect.width * w, y: g.max_y - (e.clientY - rect.top) / rect.height * h });
    }}>
    {world.racks.map((r: any, i: number) => <rect key={i} x={r.x1} y={-r.y - (r.depth ?? 1)} width={r.x2 - r.x1} height={r.depth ?? 1} fill="#64748b" />)}
    {(telemetry?.obstacles ?? world.obstacles ?? []).map((o: any, i: number) => <circle key={`o${i}`} cx={o.x} cy={-o.y} r={o.r ?? 0.4} fill="#f87171" />)}
    {(telemetry?.walking_humans ?? world.walking_humans ?? []).map((p: Point, i: number) => <circle key={`p${i}`} cx={p.x} cy={-p.y} r={0.35} fill="#fbbf24" />)}
    {(telemetry?.human ?? world.human) && <circle cx={(telemetry?.human ?? world.human).x} cy={-(telemetry?.human ?? world.human).y} r={0.4} fill="#fbbf24" />}
    {points.length === 4 && <polygon points={points.map(p => `${p.x},${-p.y}`).join(" ")} fill="#38bdf8" fillOpacity={0.08} stroke="#38bdf8" strokeWidth={0.25} />}
    {telemetry && <circle cx={telemetry.x} cy={-telemetry.y} r={0.55} fill="#22d3ee" />}
  </svg>;
}
