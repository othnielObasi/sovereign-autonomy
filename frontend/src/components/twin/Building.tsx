"use client";
/**
 * The warehouse shell: floor, cladded walls, steel frame, roof trusses,
 * high-bay lights, dock doors (with trailers outside), fire exits and signage.
 *
 * Coordinates: simulator (x, y) metres map to three.js (x, height, -y).
 */
import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { claddingTexture, floorTextures, labelTexture, roofTexture, type WorldLayout } from "./textures";

export const WALL_H = 10;
const WALL_T = 0.25;
const DOOR_W = 3.0;
const DOOR_H = 3.6;

function Box({ p, s, m, rot, cast = true, receive = true }: { p: [number, number, number]; s: [number, number, number]; m: THREE.Material; rot?: [number, number, number]; cast?: boolean; receive?: boolean }) {
  return (
    <mesh position={p} rotation={rot} castShadow={cast} receiveShadow={receive} material={m}>
      <boxGeometry args={s} />
    </mesh>
  );
}

/** Children show only while the camera is on the inside of a wall (dollhouse view). */
function OnWall({ p, n, children }: { p: [number, number]; n: [number, number]; children: React.ReactNode }) {
  const ref = useRef<THREE.Group>(null!);
  useFrame(({ camera }) => {
    if (ref.current) ref.current.visible = (camera.position.x - p[0]) * n[0] + (camera.position.z - p[1]) * n[1] > -0.05;
  });
  return <group ref={ref}>{children}</group>;
}

/** Roof structure and hanging lights: hidden when looking down from above the roof. */
function UnderRoof({ children }: { children: React.ReactNode }) {
  const ref = useRef<THREE.Group>(null!);
  useFrame(({ camera }) => {
    if (ref.current) ref.current.visible = camera.position.y < WALL_H + 1.2;
  });
  return <group ref={ref}>{children}</group>;
}

/** One-sided wall panel facing into the building (normal = +z rotated by rotY). */
function Panel({ p, s, rotY, m, holes }: { p: [number, number, number]; s: [number, number]; rotY: number; m: THREE.Material; holes?: number[] }) {
  if (holes && holes.length) {
    // outer skin with dock openings: draw the pieces between openings
    const x0 = p[0] - s[0] / 2, x1 = p[0] + s[0] / 2;
    const xs = [...holes].sort((a, b) => a - b);
    const pieces: [number, number][] = [];
    let a = x0;
    for (const h of xs) { pieces.push([a, h - DOOR_W / 2]); a = h + DOOR_W / 2; }
    pieces.push([a, x1]);
    return (
      <group>
        {pieces.map(([u, v]) => (
          <mesh key={u} position={[(u + v) / 2, p[1], p[2]]} rotation={[0, rotY, 0]} material={m}>
            <planeGeometry args={[v - u, s[1]]} />
          </mesh>
        ))}
        {xs.map((h) => (
          <mesh key={h} position={[h, (WALL_H + DOOR_H) / 2, p[2]]} rotation={[0, rotY, 0]} material={m}>
            <planeGeometry args={[DOOR_W, WALL_H - DOOR_H]} />
          </mesh>
        ))}
      </group>
    );
  }
  return (
    <mesh position={p} rotation={[0, rotY, 0]} material={m} receiveShadow>
      <planeGeometry args={s} />
    </mesh>
  );
}

function Sign({ text, sub, p, rot = [0, 0, 0], size = [1.6, 0.4], bg = "#ffffff", fg = "#111111", border, emissive = 0 }: {
  text: string; sub?: string; p: [number, number, number]; rot?: [number, number, number]; size?: [number, number]; bg?: string; fg?: string; border?: string; emissive?: number;
}) {
  const mat = useMemo(() => {
    const t = labelTexture(text, { bg, fg, border, sub, w: 512, h: Math.round(512 * size[1] / size[0]) });
    return new THREE.MeshStandardMaterial({ map: t, roughness: 0.5, emissive: new THREE.Color("#ffffff"), emissiveMap: emissive ? t : null, emissiveIntensity: emissive });
  }, [text, sub, bg, fg, border, emissive, size]);
  return (
    <mesh position={p} rotation={rot} material={mat}>
      <planeGeometry args={size} />
    </mesh>
  );
}

export function Building({ world }: { world: WorldLayout }) {
  const g = world.geofence;
  const W = g.max_x - g.min_x, D = g.max_y - g.min_y;
  const cx = (g.min_x + g.max_x) / 2, cz = -(g.min_y + g.max_y) / 2;

  const mats = useMemo(() => {
    const { map, roughnessMap } = floorTextures(world);
    const clad = claddingTexture();
    const roof = roofTexture();
    return {
      floor: new THREE.MeshStandardMaterial({ map, roughnessMap, roughness: 0.88, metalness: 0.03, envMapIntensity: 0.9 }),
      apron: new THREE.MeshStandardMaterial({ color: "#5d5e5f", roughness: 0.95 }),
      wall: new THREE.MeshStandardMaterial({ map: clad, color: "#f2f4f5", roughness: 0.55, metalness: 0.35 }),
      wallOut: new THREE.MeshStandardMaterial({ map: clad, color: "#9aa7b4", roughness: 0.5, metalness: 0.4 }),
      ground: new THREE.MeshStandardMaterial({ color: "#6f7174", roughness: 0.95 }),
      plinth: new THREE.MeshStandardMaterial({ color: "#8d8e8c", roughness: 0.9 }),
      kerb: new THREE.MeshStandardMaterial({ color: "#e0aa00", roughness: 0.6 }),
      steel: new THREE.MeshStandardMaterial({ color: "#3d4f63", roughness: 0.5, metalness: 0.6 }),
      truss: new THREE.MeshStandardMaterial({ color: "#c9ccd0", roughness: 0.6, metalness: 0.5 }),
      roof: new THREE.MeshStandardMaterial({ map: roof, color: "#e3e6ea", roughness: 0.7, metalness: 0.3 }),
      skylight: new THREE.MeshStandardMaterial({ color: "#eef4fb", emissive: "#eaf2ff", emissiveIntensity: 1.6, roughness: 0.3 }),
      lampHousing: new THREE.MeshStandardMaterial({ color: "#2b2f35", roughness: 0.4, metalness: 0.7 }),
      lamp: new THREE.MeshStandardMaterial({ color: "#fffaf0", emissive: "#fff3df", emissiveIntensity: 9 }),
      door: new THREE.MeshStandardMaterial({ map: clad, color: "#b9c0c8", roughness: 0.5, metalness: 0.5 }),
      doorFrame: new THREE.MeshStandardMaterial({ color: "#f2c200", roughness: 0.5 }),
      rubber: new THREE.MeshStandardMaterial({ color: "#151515", roughness: 0.9 }),
      leveller: new THREE.MeshStandardMaterial({ color: "#6c7178", roughness: 0.45, metalness: 0.8 }),
      trailer: new THREE.MeshStandardMaterial({ color: "#eceeef", roughness: 0.5, metalness: 0.2 }),
      trailerIn: new THREE.MeshStandardMaterial({ color: "#2c2a28", roughness: 0.9 }),
      outside: new THREE.MeshBasicMaterial({ color: "#e9eef3" }),
      exitDoor: new THREE.MeshStandardMaterial({ color: "#2d7d46", roughness: 0.5, metalness: 0.3 }),
      bollard: new THREE.MeshStandardMaterial({ color: "#f0b400", roughness: 0.45, metalness: 0.2 }),
      black: new THREE.MeshStandardMaterial({ color: "#151515", roughness: 0.6 }),
    };
  }, [world]);

  const docks = world.bays.filter((b) => b.type === "dock");
  const exits = world.features.filter((f) => f.type === "fire_exit");

  /* north wall broken around the dock openings */
  const northSegs = useMemo(() => {
    const xs = docks.map((d) => d.x).sort((a, b) => a - b);
    const segs: [number, number][] = [];
    let start = g.min_x;
    for (const x of xs) {
      segs.push([start, x - DOOR_W / 2]);
      start = x + DOOR_W / 2;
    }
    segs.push([start, g.max_x]);
    return segs.filter(([a, b]) => b - a > 0.01);
  }, [docks, g]);

  const columnsX = useMemo(() => {
    const out: number[] = [];
    for (let x = g.min_x; x <= g.max_x + 0.01; x += 5) out.push(x);
    return out;
  }, [g]);

  const lamps = useMemo(() => {
    const out: [number, number][] = [];
    for (let x = g.min_x + 2.5; x < g.max_x; x += 5) for (let y = g.min_y + 2.5; y < g.max_y; y += 5) out.push([x, y]);
    return out;
  }, [g]);

  return (
    <group>
      {/* floor */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[cx, 0, cz]} receiveShadow material={mats.floor}>
        <planeGeometry args={[W, D]} />
      </mesh>
      {/* site ground */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[cx, -0.04, cz]} material={mats.ground}>
        <planeGeometry args={[220, 220]} />
      </mesh>
      {/* yard outside the docks */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[cx, -0.02, -g.max_y - 12]} material={mats.apron}>
        <planeGeometry args={[W + 30, 24]} />
      </mesh>
      <mesh position={[cx, 3, -g.max_y - 16]} material={mats.outside}>
        <planeGeometry args={[W + 10, 6]} />
      </mesh>

      {/* walls are inward-facing panels: from outside, the near walls vanish (dollhouse view) */}
      <Panel p={[cx, WALL_H / 2, -g.min_y]} s={[W, WALL_H]} rotY={Math.PI} m={mats.wall} />
      <Panel p={[g.min_x, WALL_H / 2, cz]} s={[D, WALL_H]} rotY={Math.PI / 2} m={mats.wall} />
      <Panel p={[g.max_x, WALL_H / 2, cz]} s={[D, WALL_H]} rotY={-Math.PI / 2} m={mats.wall} />
      {northSegs.map(([a, b]) => (
        <Panel key={a} p={[(a + b) / 2, WALL_H / 2, -g.max_y]} s={[b - a, WALL_H]} rotY={0} m={mats.wall} />
      ))}
      {docks.map((d) => (
        <Panel key={d.id} p={[d.x, (WALL_H + DOOR_H) / 2, -g.max_y]} s={[DOOR_W, WALL_H - DOOR_H]} rotY={0} m={mats.wall} />
      ))}
      {/* exterior skin of the far walls so the building reads solid from the yard */}
      <Panel p={[cx, WALL_H / 2, -g.max_y - 0.3]} s={[W + 0.6, WALL_H]} rotY={Math.PI} m={mats.wallOut} holes={docks.map((d) => d.x)} />

      {/* concrete plinth and painted kerb along the inside of the walls */}
      <Panel p={[cx, 0.6, -g.min_y - 0.01]} s={[W, 1.2]} rotY={Math.PI} m={mats.plinth} />
      <Panel p={[g.min_x + 0.01, 0.6, cz]} s={[D, 1.2]} rotY={Math.PI / 2} m={mats.plinth} />
      <Panel p={[g.max_x - 0.01, 0.6, cz]} s={[D, 1.2]} rotY={-Math.PI / 2} m={mats.plinth} />

      {/* steel columns along the long walls */}
      {([[g.min_y + 0.2, [cx, -g.min_y], [0, -1]], [g.max_y - 0.2, [cx, -g.max_y], [0, 1]]] as [number, [number, number], [number, number]][]).map(([y, wp, wn]) => (
        <OnWall key={y} p={wp} n={wn}>
          {columnsX.map((x) => (
            <group key={x} position={[Math.min(Math.max(x, g.min_x + 0.2), g.max_x - 0.2), 0, -y]}>
              <Box p={[0, WALL_H / 2, 0]} s={[0.35, WALL_H, 0.05]} m={mats.steel} />
              <Box p={[0, WALL_H / 2, -0.15]} s={[0.35, WALL_H, 0.04]} m={mats.steel} />
              <Box p={[0, WALL_H / 2, 0.15]} s={[0.35, WALL_H, 0.04]} m={mats.steel} />
            </group>
          ))}
        </OnWall>
      ))}

      <UnderRoof>
        {/* trusses across the span, purlins along it, roof sheet and skylights */}
        {columnsX.map((x) => (
          <group key={x} position={[Math.min(Math.max(x, g.min_x + 0.2), g.max_x - 0.2), 0, cz]}>
            <Box p={[0, WALL_H + 1.1, 0]} s={[0.2, 0.2, D]} m={mats.truss} cast={false} />
            <Box p={[0, WALL_H - 0.3, 0]} s={[0.15, 0.15, D]} m={mats.truss} cast={false} />
            {Array.from({ length: Math.floor(D / 2.5) }).map((_, k) => (
              <Box key={k} p={[0, WALL_H + 0.4, -D / 2 + 1.25 + k * 2.5]} s={[0.07, 1.6, 0.07]} rot={[k % 2 ? 0.6 : -0.6, 0, 0]} m={mats.truss} cast={false} />
            ))}
          </group>
        ))}
        {Array.from({ length: Math.floor(D / 2.5) + 1 }).map((_, k) => (
          <Box key={k} p={[cx, WALL_H + 1.3, -g.min_y - k * 2.5]} s={[W, 0.12, 0.08]} m={mats.truss} cast={false} />
        ))}
        <mesh position={[cx, WALL_H + 1.45, cz]} rotation={[Math.PI / 2, 0, 0]} material={mats.roof}>
          <planeGeometry args={[W + 0.6, D + 0.6]} />
        </mesh>
        {[4, 12.5, 21].map((y) => (
          <mesh key={y} position={[cx, WALL_H + 1.42, -y]} rotation={[Math.PI / 2, 0, 0]} material={mats.skylight}>
            <planeGeometry args={[W - 4, 1.4]} />
          </mesh>
        ))}
        {/* high-bay LED lights */}
        {lamps.map(([x, y]) => (
          <group key={`${x}-${y}`} position={[x, WALL_H - 1.2, -y]}>
            <mesh material={mats.lampHousing}>
              <cylinderGeometry args={[0.28, 0.34, 0.16, 20]} />
            </mesh>
            <mesh position={[0, -0.085, 0]} rotation={[Math.PI / 2, 0, 0]} material={mats.lamp}>
              <circleGeometry args={[0.3, 24]} />
            </mesh>
            <mesh position={[0, 1.0, 0]} material={mats.black}>
              <cylinderGeometry args={[0.008, 0.008, 2, 4]} />
            </mesh>
          </group>
        ))}
      </UnderRoof>

      {/* dock doors: half-open roller shutters, levellers, bumpers, trailers */}
      {docks.map((d, i) => {
        const z = -g.max_y;
        const open = i % 3 !== 2;
        const shutterH = open ? 1.4 : DOOR_H;
        return (
          <group key={d.id}>
            <Box p={[d.x, DOOR_H - shutterH / 2, z - 0.05]} s={[DOOR_W, shutterH, 0.08]} m={mats.door} />
            <Box p={[d.x - DOOR_W / 2 - 0.08, DOOR_H / 2, z + 0.02]} s={[0.16, DOOR_H, 0.16]} m={mats.doorFrame} />
            <Box p={[d.x + DOOR_W / 2 + 0.08, DOOR_H / 2, z + 0.02]} s={[0.16, DOOR_H, 0.16]} m={mats.doorFrame} />
            <Box p={[d.x, DOOR_H + 0.1, z + 0.02]} s={[DOOR_W + 0.32, 0.2, 0.16]} m={mats.doorFrame} />
            <Box p={[d.x, 0.012, z + 1.0]} s={[2.2, 0.025, 2.0]} m={mats.leveller} cast={false} />
            <Box p={[d.x, 0.02, z + 2.02]} s={[2.2, 0.03, 0.06]} m={mats.doorFrame} cast={false} />
            {[-1.35, 1.35].map((dx) => (
              <Box key={dx} p={[d.x + dx, 0.95, z + 0.12]} s={[0.25, 0.45, 0.12]} m={mats.rubber} />
            ))}
            {[-1.75, 1.75].map((dx) => (
              <mesh key={dx} position={[d.x + dx, 0.6, z + 0.35]} castShadow material={mats.bollard}>
                <cylinderGeometry args={[0.08, 0.08, 1.2, 14]} />
              </mesh>
            ))}
            <mesh position={[d.x + 1.6, DOOR_H + 0.55, z + 0.15]}>
              <boxGeometry args={[0.2, 0.12, 0.1]} />
              <meshStandardMaterial color="#111" emissive={open ? "#22c55e" : "#ef4444"} emissiveIntensity={4} />
            </mesh>
            <Sign text={d.id.replace("B-", "DOOR ")} p={[d.x, DOOR_H + 0.75, z + 0.11]} size={[1.3, 0.38]} bg="#1d3d6b" fg="#ffffff" />
            {open && (
              <group position={[d.x, 0, z - 7.5]}>
                <Box p={[0, 2.55, 0]} s={[2.5, 2.9, 13.6]} m={mats.trailer} />
                <Box p={[0, 2.5, 6.79]} s={[2.3, 2.6, 0.04]} m={mats.trailerIn} />
                <Box p={[0, 1.05, 6.75]} s={[2.5, 0.1, 0.15]} m={mats.black} />
                {[-0.9, 0.9].map((dx) => (
                  <mesh key={dx} position={[dx, 0.5, 3]} rotation={[0, 0, Math.PI / 2]} material={mats.rubber}>
                    <cylinderGeometry args={[0.5, 0.5, 0.35, 20]} />
                  </mesh>
                ))}
              </group>
            )}
          </group>
        );
      })}

      {/* fire exits */}
      {exits.map((f) => {
        const west = f.x <= g.min_x + 0.5;
        const x = west ? g.min_x + 0.03 : g.max_x - 0.03;
        const rot: [number, number, number] = [0, west ? Math.PI / 2 : -Math.PI / 2, 0];
        return (
          <OnWall key={f.label} p={[x, -f.y]} n={[west ? 1 : -1, 0]}>
          <group position={[x, 0, -f.y]} rotation={rot}>
            <Box p={[0, 1.1, 0]} s={[1.2, 2.2, 0.06]} m={mats.exitDoor} />
            <Box p={[0, 1.05, 0.06]} s={[1.0, 0.06, 0.06]} m={mats.truss} />
            <Sign text="FIRE EXIT" sub="KEEP CLEAR" p={[0, 2.65, 0.05]} size={[1.2, 0.4]} bg="#1d8f3f" fg="#ffffff" emissive={1.2} />
            {[-1.0, 1.0].map((dz) => (
              <Box key={dz} p={[dz, 0.06, 1.0]} s={[0.05, 0.02, 2.0]} m={mats.kerb} cast={false} />
            ))}
          </group>
          </OnWall>
        );
      })}

      {/* wall signage */}
      <OnWall p={[cx, -g.min_y]} n={[0, -1]}>
        <Sign text="SOVEREIGN AUTONOMY" sub="EVERY MOVE GOVERNED · EVERY DECISION SIGNED" p={[cx, 6.2, -g.min_y - 0.14]} size={[9, 1.5]} bg="#0d1b2e" fg="#ffffff" />
        <Sign text="SPEED LIMIT 5 KM/H" p={[8, 2.6, -g.min_y - 0.14]} size={[1.8, 0.6]} bg="#ffffff" fg="#c1121f" border="#c1121f" />
        <Sign text="HI-VIS REQUIRED" p={[g.max_x - 8, 2.6, -g.min_y - 0.14]} size={[1.8, 0.6]} bg="#1d4ed8" fg="#ffffff" />
      </OnWall>
      <OnWall p={[g.min_x, cz]} n={[1, 0]}>
        <Sign text="FORKLIFT ROUTE" sub="PEDESTRIANS USE CROSSINGS" p={[g.min_x + 0.14, 3.0, -13.5 + 3]} rot={[0, Math.PI / 2, 0]} size={[2.2, 0.7]} bg="#f2c200" fg="#111111" />
        <Sign text="STAGING" p={[g.min_x + 0.14, 4.0, -17]} rot={[0, Math.PI / 2, 0]} size={[2.4, 0.7]} bg="#1d3d6b" fg="#ffffff" />
      </OnWall>
      <OnWall p={[g.max_x, cz]} n={[-1, 0]}>
        <Sign text="LOADING BAY" p={[g.max_x - 0.14, 4.0, -21]} rot={[0, -Math.PI / 2, 0]} size={[3, 0.8]} bg="#1d3d6b" fg="#ffffff" />
      </OnWall>
    </group>
  );
}
