"use client";
/**
 * Everything that moves or appears: the AMR, the forklift, people in hi-vis,
 * and the hazards (spills, dropped pallets, totes, handcarts, parked pallets).
 * Positions arrive a few times a second; each actor glides to its latest pose.
 */
import { useEffect, useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Html, RoundedBox } from "@react-three/drei";
import * as THREE from "three";
import { labelTexture, loadTexture, rng, vestTexture, woodTexture } from "./textures";

export const VERDICT_COLOURS: Record<string, string> = {
  APPROVED: "#22c55e",
  NEEDS_REVIEW: "#f59e0b",
  HOLDING: "#f59e0b",
  DENIED: "#ef4444",
  IDLE: "#38bdf8",
};

const tmp = new THREE.Vector3();

/** Glide a group toward (x, y) and heading; returns the measured speed (m/s). */
function useGlide(ref: React.RefObject<THREE.Group>, x: number, y: number, heading: number | null, rate = 6, pose?: React.MutableRefObject<{ x: number; y: number; theta: number }>) {
  const speed = useRef(0);
  const init = useRef(false);
  const lastHeading = useRef(heading ?? 0);
  useFrame((_, dt) => {
    const g = ref.current;
    if (!g) return;
    tmp.set(x, 0, -y);
    if (!init.current || g.position.distanceTo(tmp) > 6) {
      g.position.copy(tmp);
      g.rotation.y = heading ?? 0;
      speed.current = 0;
      lastHeading.current = heading ?? 0;
      if (pose) { pose.current.x = g.position.x; pose.current.y = -g.position.z; pose.current.theta = g.rotation.y; }
      init.current = true;
      return;
    }
    const beforeX = g.position.x, beforeZ = g.position.z;
    const k = 1 - Math.exp(-rate * Math.min(dt, 0.1));
    g.position.lerp(tmp, k);
    const moved = Math.hypot(g.position.x - beforeX, g.position.z - beforeZ);
    const speedEase = 1 - Math.exp(-10 * Math.min(dt, 0.1));
    speed.current += (moved / Math.max(dt, 1e-3) - speed.current) * speedEase;
    let target = heading;
    if (target === null) {
      const dx = tmp.x - g.position.x, dz = tmp.z - g.position.z;
      if (Math.hypot(dx, dz) > 0.05) lastHeading.current = Math.atan2(-dz, dx);
      target = lastHeading.current;
    }
    let d = target - g.rotation.y;
    d = Math.atan2(Math.sin(d), Math.cos(d));
    g.rotation.y += d * Math.min(1, k * 1.5);
    if (pose) { pose.current.x = g.position.x; pose.current.y = -g.position.z; pose.current.theta = g.rotation.y; }
  });
  return speed;
}

/* ────────────────────────────── robot ────────────────────────────── */

export function Robot({ x, y, theta, verdict, ghost = false, idle = false, pose, label }: { label?: string; pose?: React.MutableRefObject<{ x: number; y: number; theta: number }>; x: number; y: number; theta: number; verdict: string; ghost?: boolean; idle?: boolean }) {
  const ref = useRef<THREE.Group>(null!);
  const speed = useGlide(ref, x, y, theta, ghost ? 30 : 7, pose);
  const wheels = useRef<THREE.Group[]>([]);
  const colour = VERDICT_COLOURS[verdict] ?? VERDICT_COLOURS.IDLE;
  const mats = useMemo(() => {
    const decal = labelTexture("SOVEREIGN AUTONOMY", { bg: "#e9edf1", fg: "#0f172a", w: 512, h: 96, font: "800 32px Arial" });
    const m = {
      body: new THREE.MeshPhysicalMaterial({ color: idle ? "#6b7280" : "#1f2329", roughness: 0.35, metalness: 0.4, clearcoat: 0.6 }),
      top: new THREE.MeshPhysicalMaterial({ color: "#e9edf1", roughness: 0.3, clearcoat: 0.8 }),
      decal: new THREE.MeshStandardMaterial({ map: decal, roughness: 0.4 }),
      strip: new THREE.MeshStandardMaterial({ color: colour, emissive: colour, emissiveIntensity: 3.5, toneMapped: false }),
      lidar: new THREE.MeshStandardMaterial({ color: "#0b0d10", roughness: 0.2, metalness: 0.8 }),
      lens: new THREE.MeshStandardMaterial({ color: "#0b0d10", roughness: 0.05, metalness: 1 }),
      tote: new THREE.MeshStandardMaterial({ color: "#2563eb", roughness: 0.6 }),
      field: new THREE.MeshBasicMaterial({ color: colour, transparent: true, opacity: 0.22, depthWrite: false, toneMapped: false }),
      fieldEdge: new THREE.MeshBasicMaterial({ color: colour, transparent: true, opacity: 0.85, depthWrite: false, toneMapped: false }),
    };
    if (ghost) {
      for (const v of Object.values(m)) {
        (v as THREE.Material).transparent = true;
        (v as THREE.Material).opacity = 0.28;
        (v as THREE.Material).depthWrite = false;
      }
    }
    return m;
  }, [colour, ghost, idle]);
  useEffect(() => () => Object.values(mats).forEach((m) => m.dispose()), [mats]);

  useFrame(({ clock }, dt) => {
    for (const wheel of wheels.current) if (wheel) wheel.rotation.z -= speed.current * Math.min(dt, 0.1) / 0.095;
    const pulse = 0.55 + 0.45 * Math.sin(clock.elapsedTime * (verdict === "DENIED" ? 9 : 3));
    mats.fieldEdge.opacity = (ghost ? 0.4 : 0.9) * pulse;
    mats.strip.emissiveIntensity = 2.5 + 1.5 * pulse;
  });

  return (
    <group ref={ref}>
      {label && <Html position={[0, 1.2, 0]} center distanceFactor={16}><div className="whitespace-nowrap rounded bg-slate-950/80 px-2 py-1 text-[10px] text-slate-300">{label} · IDLE</div></Html>}
      {/* Four recessed rubber wheels roll with measured rendered travel. */}
      {[[-0.28, -0.31], [-0.28, 0.31], [0.28, -0.31], [0.28, 0.31]].map(([wx, wz], i) => <group key={i} ref={(wheel) => { if (wheel) wheels.current[i] = wheel; }} position={[wx, 0.095, wz]}>
        <mesh rotation={[Math.PI / 2, 0, 0]} castShadow><cylinderGeometry args={[0.095, 0.095, 0.065, 16]} /><meshStandardMaterial color="#161b22" roughness={0.94} /></mesh>
        <mesh position={[0, 0, wz > 0 ? 0.036 : -0.036]} rotation={[Math.PI / 2, 0, 0]}><cylinderGeometry args={[0.047, 0.047, 0.006, 12]} /><meshStandardMaterial color="#9aa8b7" metalness={0.7} roughness={0.35} /></mesh>
        <mesh position={[0.025, 0, wz > 0 ? 0.041 : -0.041]}><boxGeometry args={[0.008, 0.065, 0.004]} /><meshStandardMaterial color="#364152" /></mesh>
      </group>)}
      {/* chassis: 0.9 m long, 0.62 m wide */}
      <RoundedBox args={[0.9, 0.24, 0.62]} radius={0.06} smoothness={4} position={[0, 0.17, 0]} castShadow material={mats.body} />
      <RoundedBox args={[0.84, 0.05, 0.58]} radius={0.03} smoothness={4} position={[0, 0.31, 0]} castShadow material={mats.top} />
      <mesh position={[0, 0.1, 0]} material={mats.strip}>
        <boxGeometry args={[0.92, 0.025, 0.64]} />
      </mesh>
      {[-1, 1].map((s) => (
        <mesh key={s} position={[0, 0.2, s * 0.312]} rotation={[0, s > 0 ? 0 : Math.PI, 0]} material={mats.decal}>
          <planeGeometry args={[0.5, 0.09]} />
        </mesh>
      ))}
      {/* lidar puck and camera mast at the front */}
      <mesh position={[0.36, 0.38, 0]} castShadow material={mats.lidar}>
        <cylinderGeometry args={[0.055, 0.06, 0.09, 24]} />
      </mesh>
      <mesh position={[0.3, 0.55, 0]} castShadow material={mats.lidar}>
        <boxGeometry args={[0.04, 0.4, 0.04]} />
      </mesh>
      <mesh position={[0.32, 0.76, 0]} castShadow material={mats.lidar}>
        <boxGeometry args={[0.08, 0.06, 0.16]} />
      </mesh>
      <mesh position={[0.365, 0.76, 0]} rotation={[0, 0, Math.PI / 2]} material={mats.lens}>
        <cylinderGeometry args={[0.02, 0.02, 0.01, 16]} />
      </mesh>
      {/* tote it is carrying */}
      {!idle && (
        <mesh position={[-0.12, 0.47, 0]} castShadow material={mats.tote}>
          <boxGeometry args={[0.6, 0.27, 0.4]} />
        </mesh>
      )}
      {/* projected safety field ahead of the robot */}
      {!idle && (
        <group position={[0, 0.012, 0]} rotation={[-Math.PI / 2, 0, 0]}>
          <mesh material={mats.field}>
            <ringGeometry args={[0.55, 1.6, 48, 1, -Math.PI / 3, (Math.PI * 2) / 3]} />
          </mesh>
          <mesh material={mats.fieldEdge}>
            <ringGeometry args={[1.56, 1.62, 48, 1, -Math.PI / 3, (Math.PI * 2) / 3]} />
          </mesh>
        </group>
      )}
    </group>
  );
}

/* ───────────────────────────── forklift ───────────────────────────── */

export function Forklift({ x, y, heading }: { x: number; y: number; heading: number }) {
  const ref = useRef<THREE.Group>(null!);
  useGlide(ref, x, y, heading, 5);
  const beacon = useRef<THREE.MeshStandardMaterial>(null!);
  const mats = useMemo(() => ({
    paint: new THREE.MeshPhysicalMaterial({ color: "#f2b705", roughness: 0.38, metalness: 0.25, clearcoat: 0.5 }),
    dark: new THREE.MeshStandardMaterial({ color: "#202326", roughness: 0.55, metalness: 0.5 }),
    steel: new THREE.MeshStandardMaterial({ color: "#3b3f44", roughness: 0.35, metalness: 0.85 }),
    tyre: new THREE.MeshStandardMaterial({ color: "#111111", roughness: 0.9 }),
    seat: new THREE.MeshStandardMaterial({ color: "#1a1a1a", roughness: 0.8 }),
    spot: new THREE.MeshBasicMaterial({ color: "#2f7dff", transparent: true, opacity: 0.75, depthWrite: false, toneMapped: false }),
    lamp: new THREE.MeshStandardMaterial({ color: "#fff", emissive: "#fff8e1", emissiveIntensity: 6, toneMapped: false }),
    stripe: new THREE.MeshStandardMaterial({ map: labelTexture("", { bg: "#111111" }), color: "#111" }),
  }), []);
  useFrame(({ clock }) => {
    if (beacon.current) beacon.current.emissiveIntensity = Math.sin(clock.elapsedTime * 8) > 0.2 ? 10 : 0.6;
  });
  // model is ~2.3 m long; centre it on the simulator position (+x = forward)
  return (
    <group ref={ref}>
      <group position={[-0.25, 0, 0]}>
        <RoundedBox args={[1.5, 0.75, 1.05]} radius={0.08} smoothness={3} position={[0, 0.62, 0]} castShadow material={mats.paint} />
        <RoundedBox args={[0.55, 0.9, 1.08]} radius={0.12} smoothness={3} position={[-0.72, 0.72, 0]} castShadow material={mats.dark} />
        <mesh position={[-0.2, 1.12, 0]} castShadow material={mats.seat}>
          <boxGeometry args={[0.45, 0.25, 0.5]} />
        </mesh>
        <mesh position={[-0.42, 1.38, 0]} castShadow material={mats.seat}>
          <boxGeometry args={[0.1, 0.5, 0.48]} />
        </mesh>
        <mesh position={[0.25, 1.3, 0]} rotation={[0, 0, 0.9]} material={mats.dark}>
          <torusGeometry args={[0.16, 0.02, 8, 24]} />
        </mesh>
        {/* overhead guard */}
        {[[0.55, 0.48], [0.55, -0.48], [-0.6, 0.48], [-0.6, -0.48]].map(([gx, gz], i) => (
          <mesh key={i} position={[gx, 1.55, gz]} castShadow material={mats.dark}>
            <boxGeometry args={[0.06, 1.9, 0.06]} />
          </mesh>
        ))}
        <mesh position={[-0.02, 2.5, 0]} castShadow material={mats.dark}>
          <boxGeometry args={[1.25, 0.05, 1.02]} />
        </mesh>
        {Array.from({ length: 6 }).map((_, k) => (
          <mesh key={k} position={[-0.55 + k * 0.22, 2.48, 0]} material={mats.dark}>
            <boxGeometry args={[0.04, 0.05, 0.98]} />
          </mesh>
        ))}
        <mesh position={[-0.55, 2.62, 0.38]}>
          <cylinderGeometry args={[0.06, 0.07, 0.14, 16]} />
          <meshStandardMaterial ref={beacon} color="#ffb000" emissive="#ff9d00" emissiveIntensity={6} toneMapped={false} />
        </mesh>
        {/* mast, chains, carriage and forks */}
        {[0.36, -0.36].map((gz) => (
          <mesh key={gz} position={[0.86, 1.3, gz]} castShadow material={mats.steel}>
            <boxGeometry args={[0.1, 2.5, 0.09]} />
          </mesh>
        ))}
        {[0.4, 1.4, 2.45].map((h) => (
          <mesh key={h} position={[0.86, h, 0]} material={mats.steel}>
            <boxGeometry args={[0.08, 0.08, 0.8]} />
          </mesh>
        ))}
        <mesh position={[0.95, 0.45, 0]} castShadow material={mats.dark}>
          <boxGeometry args={[0.06, 0.55, 0.95]} />
        </mesh>
        {[0.28, -0.28].map((gz) => (
          <group key={gz}>
            <mesh position={[1.5, 0.08, gz]} castShadow material={mats.steel}>
              <boxGeometry args={[1.1, 0.045, 0.11]} />
            </mesh>
            <mesh position={[0.97, 0.38, gz]} material={mats.steel}>
              <boxGeometry args={[0.045, 0.6, 0.11]} />
            </mesh>
          </group>
        ))}
        {[0.2, -0.2].map((gz) => (
          <mesh key={gz} position={[0.84, 1.4, gz]} material={mats.lamp}>
            <boxGeometry args={[0.04, 0.08, 0.12]} />
          </mesh>
        ))}
        {/* wheels */}
        {[[0.5, 0.3, 0.5], [0.5, 0.3, -0.5], [-0.65, 0.24, 0.48], [-0.65, 0.24, -0.48]].map(([wx, r, wz], i) => (
          <mesh key={i} position={[wx, r, wz]} rotation={[Math.PI / 2, 0, 0]} castShadow material={mats.tyre}>
            <cylinderGeometry args={[r, r, 0.22, 24]} />
          </mesh>
        ))}
      </group>
      {/* blue warning spot projected 3 m ahead */}
      <mesh position={[3.2, 0.015, 0]} rotation={[-Math.PI / 2, 0, 0]} material={mats.spot}>
        <circleGeometry args={[0.32, 32]} />
      </mesh>
    </group>
  );
}

/* ────────────────────────────── people ────────────────────────────── */

const SKIN = ["#e0b899", "#c68d67", "#8d5a3b", "#5c3a26", "#f1cfb4", "#a8714e"];

/** A warehouse operative: proportioned limbs with knee and elbow bend, hi-vis vest, hard hat. */
export function Worker({ x, y, id, highlight = false, label, heading }: { heading?: number; label?: string; x: number; y: number; id: string; highlight?: boolean }) {
  const ref = useRef<THREE.Group>(null!);
  const hipL = useRef<THREE.Group>(null!), hipR = useRef<THREE.Group>(null!);
  const kneeL = useRef<THREE.Group>(null!), kneeR = useRef<THREE.Group>(null!);
  const shL = useRef<THREE.Group>(null!), shR = useRef<THREE.Group>(null!);
  const elL = useRef<THREE.Group>(null!), elR = useRef<THREE.Group>(null!);
  const body = useRef<THREE.Group>(null!);
  const head = useRef<THREE.Group>(null!);
  const gait = useRef(0);
  const faceDetails = useRef<THREE.Group>(null!);
  const speed = useGlide(ref, x, y, heading ?? null, 4);
  const phase = useRef(Array.from(id).reduce((sum, ch) => sum + ch.charCodeAt(0), 0) % 6);
  const look = useMemo(() => {
    let h = 0;
    for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    const r = rng(h + 1);
    return {
      skin: SKIN[Math.floor(r() * SKIN.length)],
      vest: vestTexture(r() < 0.3),
      hat: ["#f4f4f2", "#f2c200", "#2563eb", "#f4f4f2"][Math.floor(r() * 4)],
      trousers: ["#1f2a3a", "#2b2b2b", "#3a3f2e"][Math.floor(r() * 3)],
      shirt: ["#2d3748", "#374151", "#1e293b"][Math.floor(r() * 3)],
      scale: 0.95 + r() * 0.09,
      scanner: r() < 0.55,
      bald: r() < 0.3,
      build: 0.94 + r() * 0.12,
      hair: ["#211811", "#3b2b1d", "#72675d", "#161616"][Math.floor(r() * 4)],
      beard: r() < 0.35,
    };
  }, [id]);
  const mats = useMemo(() => ({
    skin: new THREE.MeshStandardMaterial({ color: look.skin, roughness: 0.65 }),
    vest: new THREE.MeshStandardMaterial({ map: look.vest, roughness: 0.7, emissive: "#d8ff3a", emissiveIntensity: 0.05 }),
    shirt: new THREE.MeshStandardMaterial({ color: look.shirt, roughness: 0.9 }),
    trousers: new THREE.MeshStandardMaterial({ color: look.trousers, roughness: 0.9 }),
    boots: new THREE.MeshStandardMaterial({ color: "#17110d", roughness: 0.55 }),
    sole: new THREE.MeshStandardMaterial({ color: "#3a332c", roughness: 0.9 }),
    hat: new THREE.MeshPhysicalMaterial({ color: look.hat, roughness: 0.42, clearcoat: 0.35 }),
    dark: new THREE.MeshStandardMaterial({ color: "#111", roughness: 0.35, metalness: 0.3 }),
    screen: new THREE.MeshStandardMaterial({ color: "#000", emissive: "#4ade80", emissiveIntensity: 1.2 }),
    hair: new THREE.MeshStandardMaterial({ color: look.hair, roughness: 0.95 }),
    eye: new THREE.MeshStandardMaterial({ color: "#bcb8ad", roughness: 0.5 }),
    iris: new THREE.MeshStandardMaterial({ color: "#29261e", roughness: 0.35 }),
    lip: new THREE.MeshStandardMaterial({ color: new THREE.Color(look.skin).multiplyScalar(0.62), roughness: 0.85 }),
    trim: new THREE.MeshStandardMaterial({ color: "#c7cdd0", metalness: 0.65, roughness: 0.32 }),
  }), [look]);

  useEffect(() => () => {
    Object.values(mats).forEach(material => material.dispose());
    look.vest.dispose();
  }, [mats, look]);

  useFrame(({ clock, camera }, dt) => {
    if (faceDetails.current && ref.current) faceDetails.current.visible = camera.position.distanceToSquared(ref.current.position) < 144;
    const v = Math.min(speed.current, 1.8);
    const walking = v > 0.1;
    phase.current += Math.min(dt, 0.1) * (walking ? 3.0 + v * 3.4 : 0);
    gait.current += ((walking ? Math.min(0.5, 0.2 + v * 0.28) : 0) - gait.current) * (1 - Math.exp(-8 * Math.min(dt, 0.1)));
    const amp = gait.current;
    const s = Math.sin(phase.current), c = Math.cos(phase.current);
    const k = Math.min(1, dt * 12);
    const ease = (r: React.RefObject<THREE.Group>, target: number) => {
      if (r.current) r.current.rotation.z += (target - r.current.rotation.z) * k;
    };
    // hips swing; knees bend on the trailing leg
    ease(hipL, s * amp);
    ease(hipR, -s * amp);
    ease(kneeL, -Math.max(0, s) * amp * 1.5);
    ease(kneeR, -Math.max(0, -s) * amp * 1.5);
    ease(shL, -s * amp * 0.7);
    ease(shR, look.scanner ? 0.2 : s * amp * 0.7);
    ease(elL, 0.25 + amp * 0.3);
    ease(elR, look.scanner ? 1.25 : 0.25 + amp * 0.3);
    if (body.current) {
      body.current.position.y = Math.abs(c) * amp * 0.035 + Math.sin(clock.elapsedTime * 1.8) * 0.003;
      body.current.rotation.x = Math.sin(phase.current) * amp * 0.035;
      body.current.rotation.y = Math.sin(phase.current) * amp * 0.055;
    }
    if (head.current) {
      head.current.rotation.y = Math.sin(clock.elapsedTime * 0.5 + phase.current * 0.1) * 0.045;
      head.current.rotation.z = Math.sin(clock.elapsedTime * 0.7) * 0.012;
    }
  });

  const leg = (hip: React.RefObject<THREE.Group>, knee: React.RefObject<THREE.Group>, z: number) => (
    <group ref={hip} position={[0, 0.93, z]}>
      <mesh position={[0, -0.22, 0]} castShadow material={mats.trousers}>
        <cylinderGeometry args={[0.085, 0.068, 0.46, 12]} />
      </mesh>
      <group ref={knee} position={[0, -0.45, 0]}>
        <mesh position={[0, -0.21, 0]} castShadow material={mats.trousers}>
          <cylinderGeometry args={[0.066, 0.055, 0.43, 12]} />
        </mesh>
        <group position={[0.05, -0.44, 0]}>
          <RoundedBox args={[0.28, 0.1, 0.12]} radius={0.035} smoothness={2} castShadow material={mats.boots} />
          <mesh position={[0, -0.045, 0]} material={mats.sole}>
            <boxGeometry args={[0.285, 0.02, 0.125]} />
          </mesh>
        </group>
      </group>
    </group>
  );
  const arm = (sh: React.RefObject<THREE.Group>, el: React.RefObject<THREE.Group>, z: number, scanner: boolean) => (
    <group ref={sh} position={[0, 1.44, z]}>
      <mesh castShadow material={mats.shirt}>
        <sphereGeometry args={[0.065, 12, 10]} />
      </mesh>
      <mesh position={[0, -0.15, 0]} castShadow material={mats.shirt}>
        <capsuleGeometry args={[0.054, 0.19, 4, 10]} />
      </mesh>
      <group ref={el} position={[0, -0.3, 0]}>
        <mesh position={[0, -0.13, 0]} castShadow material={mats.shirt}>
          <capsuleGeometry args={[0.043, 0.18, 4, 10]} />
        </mesh>
        <mesh position={[0.008, -0.3, 0]} scale={[0.65, 1.15, 0.8]} castShadow material={mats.skin}>
          <sphereGeometry args={[0.048, 10, 8]} />
        </mesh>
        <mesh position={[0.03, -0.285, z > 0 ? -0.027 : 0.027]} rotation={[0, 0, 0.35]} material={mats.skin}>
          <capsuleGeometry args={[0.012, 0.025, 3, 6]} />
        </mesh>
        {scanner && (
          <group position={[0.04, -0.33, 0]}>
            <mesh material={mats.dark}>
              <boxGeometry args={[0.15, 0.035, 0.07]} />
            </mesh>
            <mesh position={[0, 0.019, 0]} rotation={[-Math.PI / 2, 0, 0]} material={mats.screen}>
              <planeGeometry args={[0.08, 0.05]} />
            </mesh>
          </group>
        )}
      </group>
    </group>
  );

  return (
    <group ref={ref}>
      {label && <Html position={[0, 2.05, 0]} center distanceFactor={16}><div className="whitespace-nowrap rounded bg-slate-950/80 px-2 py-0.5 text-[10px] text-amber-200">{label}</div></Html>}
      <group ref={body} scale={[look.scale, look.scale, look.scale * look.build]}>
        {leg(hipL, kneeL, 0.095)}
        {leg(hipR, kneeR, -0.095)}
        {/* pelvis, torso in a fitted vest, shoulders */}
        <mesh position={[0, 0.98, 0]} scale={[0.75, 1, 1]} castShadow material={mats.trousers}>
          <cylinderGeometry args={[0.17, 0.17, 0.16, 16]} />
        </mesh>
        <mesh position={[0, 1.24, 0]} scale={[0.68, 1, 1]} castShadow material={mats.vest}>
          <cylinderGeometry args={[0.205, 0.172, 0.42, 20, 1, false]} />
        </mesh>
        <mesh position={[0, 1.45, 0]} scale={[0.68, 0.45, 1]} castShadow material={mats.vest}>
          <sphereGeometry args={[0.205, 20, 10, 0, Math.PI * 2, 0, Math.PI / 2]} />
        </mesh>
        {arm(shL, elL, 0.235, false)}
        {arm(shR, elR, -0.235, look.scanner)}
        {/* Reflective bands follow the front and back of the fitted vest. */}
        {[-1, 1].map(side => <group key={`trim-${side}`}>
          <mesh position={[side * 0.142, 1.14, 0]} material={mats.trim}><boxGeometry args={[0.008, 0.035, 0.3]} /></mesh>
          {[-0.105, 0.105].map(z => <mesh key={z} position={[side * 0.14, 1.33, z]} material={mats.trim}><boxGeometry args={[0.008, 0.21, 0.027]} /></mesh>)}
        </group>)}
        <mesh position={[0.145, 1.29, 0]} material={mats.dark}><boxGeometry args={[0.008, 0.32, 0.009]} /></mesh>
        <mesh position={[0.151, 1.35, -0.058]} material={mats.shirt}><boxGeometry args={[0.012, 0.075, 0.065]} /></mesh>
        {/* Neck, articulated head and close-range facial detail. */}
        <mesh position={[0, 1.53, 0]} material={mats.skin}>
          <cylinderGeometry args={[0.048, 0.055, 0.09, 10]} />
        </mesh>
        <group ref={head} position={[0, 1.55, 0]}><group position={[0, -1.55, 0]}>
        <mesh position={[0.01, 1.645, 0]} scale={[1, 1.12, 0.92]} castShadow material={mats.skin}>
          <sphereGeometry args={[0.098, 18, 14]} />
        </mesh>
        <group ref={faceDetails}>
        <mesh position={[0.028, 1.585, 0]} scale={[1, 0.78, 0.92]} material={mats.skin}><sphereGeometry args={[0.07, 14, 10]} /></mesh>
        <mesh position={[0.105, 1.636, 0]} scale={[1.15, 1.35, 0.75]} material={mats.skin}><sphereGeometry args={[0.017, 10, 8]} /></mesh>
        {[-1, 1].map(side => <group key={`face-${side}`}>
          <mesh position={[-0.004, 1.648, side * 0.091]} scale={[0.7, 1.35, 0.5]} material={mats.skin}><sphereGeometry args={[0.021, 10, 8]} /></mesh>
          <mesh position={[0.096, 1.664, side * 0.037]} scale={[0.35, 0.55, 1]} material={mats.eye}><sphereGeometry args={[0.013, 10, 8]} /></mesh>
          <mesh position={[0.101, 1.664, side * 0.037]} scale={[0.3, 0.95, 0.8]} material={mats.iris}><sphereGeometry args={[0.006, 8, 6]} /></mesh>
          <mesh position={[0.094, 1.682, side * 0.037]} rotation={[side * 0.08, 0, 0]} material={mats.hair}><boxGeometry args={[0.006, 0.005, 0.025]} /></mesh>
        </group>)}
        <mesh position={[0.105, 1.608, 0]} material={mats.lip}><boxGeometry args={[0.006, 0.004, 0.035]} /></mesh>
        {look.beard && <mesh position={[0.057, 1.58, 0]} scale={[0.65, 0.42, 0.85]} material={mats.hair}><sphereGeometry args={[0.066, 12, 8]} /></mesh>}
        </group>
        {!look.bald && (
          <mesh position={[-0.012, 1.655, 0]} scale={[1, 1.1, 0.95]} material={mats.hair}>
            <sphereGeometry args={[0.1, 16, 12, Math.PI * 0.55, Math.PI * 0.9]} />
          </mesh>
        )}
        <group position={[0, 1.7, 0]}>
          <mesh scale={[1.08, 0.82, 0.98]} castShadow material={mats.hat}>
            <sphereGeometry args={[0.118, 20, 10, 0, Math.PI * 2, 0, Math.PI / 2]} />
          </mesh>
          <mesh position={[0.03, 0.002, 0]} scale={[1.2, 1, 1]} material={mats.hat}>
            <cylinderGeometry args={[0.135, 0.138, 0.012, 24]} />
          </mesh>
          <mesh position={[0, 0.035, 0]} scale={[1.05, 0.5, 0.18]} material={mats.hat}>
            <sphereGeometry args={[0.11, 12, 6, 0, Math.PI * 2, 0, Math.PI / 2]} />
          </mesh>
        </group>
        </group>
        </group>
      </group>
      {highlight && (
        <mesh position={[0, 0.02, 0]} rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[0.35, 0.42, 32]} />
          <meshBasicMaterial color="#ef4444" transparent opacity={0.9} toneMapped={false} />
        </mesh>
      )}
    </group>
  );
}

/* ───────────────────────────── hazards ───────────────────────────── */

export function Spill({ x, y, r }: { x: number; y: number; r: number }) {
  const geo = useMemo(() => {
    const rr = rng(Math.round(x * 100 + y * 7));
    const shape = new THREE.Shape();
    const n = 40;
    for (let i = 0; i <= n; i++) {
      const a = (i / n) * Math.PI * 2;
      const k = r * 1.3 * (0.75 + 0.18 * Math.sin(a * 3 + rr() * 6) + 0.1 * Math.sin(a * 7 + rr() * 6) + rr() * 0.06);
      const px = Math.cos(a) * k * 1.25, py = Math.sin(a) * k;
      if (i === 0) shape.moveTo(px, py);
      else shape.lineTo(px, py);
    }
    return new THREE.ShapeGeometry(shape, 8);
  }, [x, y, r]);
  const sign = useMemo(() => labelTexture("CAUTION", { bg: "#f6c400", fg: "#111", w: 256, h: 320, sub: "WET FLOOR", font: "900 64px Arial" }), []);
  return (
    <group position={[x, 0, -y]}>
      <mesh geometry={geo} rotation={[-Math.PI / 2, 0, 0.4]} position={[0, 0.006, 0]} receiveShadow>
        <meshPhysicalMaterial color="#3a4148" transparent opacity={0.55} roughness={0.03} metalness={0.1} clearcoat={1} clearcoatRoughness={0} envMapIntensity={2.5} depthWrite={false} />
      </mesh>
      {/* wet-floor A-frame beside the spill */}
      <group position={[r * 1.6 + 0.3, 0, r * 0.4]} rotation={[0, 0.5, 0]}>
        {[1, -1].map((s) => (
          <mesh key={s} position={[0, 0.31, s * 0.08]} rotation={[s * 0.25, 0, 0]} castShadow>
            <boxGeometry args={[0.3, 0.62, 0.012]} />
            <meshStandardMaterial map={sign} roughness={0.5} />
          </mesh>
        ))}
      </group>
    </group>
  );
}

function PalletWithLoad({ variant = 0, h = 1.0 }: { variant?: number; h?: number }) {
  const wood = useMemo(() => woodTexture(), []);
  const load = useMemo(() => loadTexture(variant), [variant]);
  return (
    <group>
      <mesh position={[0, 0.072, 0]} castShadow receiveShadow>
        <boxGeometry args={[1.2, 0.144, 1.0]} />
        <meshStandardMaterial map={wood} roughness={0.85} />
      </mesh>
      {h > 0 && (
        <mesh position={[0, 0.144 + h / 2, 0]} castShadow receiveShadow>
          <boxGeometry args={[1.14, h, 0.96]} />
          <meshPhysicalMaterial map={load} roughness={0.75} clearcoat={0.7} clearcoatRoughness={0.25} />
        </mesh>
      )}
    </group>
  );
}

export function Obstacle({ o }: { o: { x: number; y: number; r: number; type: string } }) {
  const pos: [number, number, number] = [o.x, 0, -o.y];
  const rot = useMemo(() => (Math.round(o.x * 13 + o.y * 7) % 7) * 0.12, [o.x, o.y]);
  if (o.type === "spill") return <Spill x={o.x} y={o.y} r={o.r} />;
  if (o.type === "pallet")
    return (
      <group position={pos} rotation={[0, rot, 0]}>
        <PalletWithLoad variant={1} h={1.1} />
      </group>
    );
  if (o.type === "dropped_pallet")
    return (
      <group position={pos} rotation={[0, rot + 0.6, 0]}>
        <group rotation={[0, 0, 0.12]} position={[0, 0.06, 0]}>
          <PalletWithLoad variant={0} h={0} />
        </group>
        {[[0.2, 0.3, 0.2], [-0.5, 0.15, -0.3], [0.7, -0.4, 0.9], [-0.1, 0.55, 1.4]].map(([dx, dz, ry], i) => (
          <mesh key={i} position={[dx, 0.2, dz]} rotation={[i === 3 ? 1.2 : 0, ry, 0]} castShadow>
            <boxGeometry args={[0.5, 0.4, 0.4]} />
            <meshStandardMaterial color={i % 2 ? "#b88752" : "#a97a47"} roughness={0.8} />
          </mesh>
        ))}
      </group>
    );
  if (o.type === "tote_stack")
    return (
      <group position={pos} rotation={[0, rot, 0]}>
        {[0, 1, 2].map((k) => (
          <mesh key={k} position={[0, 0.16 + k * 0.31, 0]} castShadow receiveShadow>
            <boxGeometry args={[0.6, 0.3, 0.4]} />
            <meshStandardMaterial color={k === 1 ? "#64748b" : "#1d4ed8"} roughness={0.55} />
          </mesh>
        ))}
      </group>
    );
  if (o.type === "handcart")
    return (
      <group position={pos} rotation={[0, rot, 0]}>
        <mesh position={[0, 0.2, 0]} castShadow receiveShadow>
          <boxGeometry args={[0.9, 0.04, 0.6]} />
          <meshStandardMaterial color="#1e3a8a" roughness={0.5} metalness={0.4} />
        </mesh>
        <mesh position={[-0.45, 0.6, 0]} castShadow>
          <boxGeometry args={[0.03, 0.8, 0.55]} />
          <meshStandardMaterial color="#9ca3af" metalness={0.8} roughness={0.3} />
        </mesh>
        {[[-0.35, 0.25], [-0.35, -0.25], [0.35, 0.25], [0.35, -0.25]].map(([wx, wz], i) => (
          <mesh key={i} position={[wx, 0.08, wz]} rotation={[Math.PI / 2, 0, 0]} castShadow>
            <cylinderGeometry args={[0.08, 0.08, 0.04, 14]} />
            <meshStandardMaterial color="#111" />
          </mesh>
        ))}
        <mesh position={[0.1, 0.42, 0]} castShadow>
          <boxGeometry args={[0.5, 0.4, 0.45]} />
          <meshStandardMaterial color="#b88752" roughness={0.8} />
        </mesh>
      </group>
    );
  return (
    <group position={pos}>
      <PalletWithLoad variant={2} h={0.8} />
    </group>
  );
}

/** Packing benches and charger towers at the simulator's feature points. */
export function Features({ features }: { features: { type: string; x: number; y: number; label?: string }[] }) {
  return (
    <group>
      {features.map((f) => {
        if (f.type === "charging_station")
          return (
            <group key={f.label} position={[f.x, 0, -f.y - 0.75]}>
              <mesh position={[0, 0.45, 0]} castShadow>
                <boxGeometry args={[0.5, 0.9, 0.18]} />
                <meshStandardMaterial color="#e5e7eb" roughness={0.4} />
              </mesh>
              <mesh position={[0, 0.7, 0.095]}>
                <planeGeometry args={[0.3, 0.12]} />
                <meshStandardMaterial color="#000" emissive="#22c55e" emissiveIntensity={2.5} toneMapped={false} />
              </mesh>
            </group>
          );
        if (f.type === "packing_station" || f.type === "work_station" || f.type === "qc_station")
          return (
            <group key={f.label} position={[f.x, 0, -f.y - 0.55]}>
              <mesh position={[0, 0.9, 0]} castShadow receiveShadow>
                <boxGeometry args={[1.8, 0.05, 0.6]} />
                <meshStandardMaterial color="#c7a77a" roughness={0.7} />
              </mesh>
              {[[-0.85, -0.25], [-0.85, 0.25], [0.85, -0.25], [0.85, 0.25]].map(([lx, lz], i) => (
                <mesh key={i} position={[lx, 0.45, lz]} castShadow>
                  <boxGeometry args={[0.04, 0.9, 0.04]} />
                  <meshStandardMaterial color="#6b7280" metalness={0.7} roughness={0.3} />
                </mesh>
              ))}
              <mesh position={[0.4, 1.05, 0]} castShadow>
                <boxGeometry args={[0.4, 0.25, 0.3]} />
                <meshStandardMaterial color="#b88752" roughness={0.8} />
              </mesh>
              <mesh position={[-0.45, 1.15, -0.2]} rotation={[-0.3, 0, 0]}>
                <boxGeometry args={[0.45, 0.3, 0.02]} />
                <meshStandardMaterial color="#111" emissive="#1e3a8a" emissiveIntensity={0.8} />
              </mesh>
            </group>
          );
        return null;
      })}
    </group>
  );
}

/* ─────────────────────────── hazard zones ─────────────────────────── */

type Zone = { id: string; x: number; y: number; radius: number; slow_radius: number; max_speed: number; label?: string };
type RackRect = { x1: number; x2: number; y: number; depth?: number };

/** Traffic cones round an exclusion zone, the way a site cones off a spill. */
export function ZoneCones({ zone, racks, bounds }: { zone: Zone; racks: RackRect[]; bounds: { min_x: number; max_x: number; min_y: number; max_y: number } }) {
  const spots = useMemo(() => {
    const n = Math.max(6, Math.ceil((2 * Math.PI * zone.radius) / 1.3));
    const out: [number, number][] = [];
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2;
      const x = zone.x + Math.cos(a) * zone.radius, y = zone.y + Math.sin(a) * zone.radius;
      if (x < bounds.min_x + 0.3 || x > bounds.max_x - 0.3 || y < bounds.min_y + 0.3 || y > bounds.max_y - 0.3) continue;
      if (racks.some((r) => x > r.x1 - 0.35 && x < r.x2 + 0.35 && y > r.y - 0.35 && y < r.y + (r.depth ?? 1) + 0.35)) continue;
      out.push([x, y]);
    }
    return out;
  }, [zone.x, zone.y, zone.radius, racks, bounds]);
  const mats = useMemo(() => ({
    cone: new THREE.MeshStandardMaterial({ color: "#ff5a1f", roughness: 0.55 }),
    band: new THREE.MeshStandardMaterial({ color: "#f1f5f9", roughness: 0.3, metalness: 0.2 }),
    base: new THREE.MeshStandardMaterial({ color: "#151515", roughness: 0.8 }),
  }), []);
  return (
    <group>
      {spots.map(([x, y], i) => (
        <group key={i} position={[x, 0, -y]}>
          <mesh position={[0, 0.02, 0]} castShadow material={mats.base}>
            <boxGeometry args={[0.32, 0.04, 0.32]} />
          </mesh>
          <mesh position={[0, 0.27, 0]} castShadow material={mats.cone}>
            <cylinderGeometry args={[0.025, 0.13, 0.46, 18]} />
          </mesh>
          <mesh position={[0, 0.3, 0]} material={mats.band}>
            <cylinderGeometry args={[0.068, 0.084, 0.08, 18]} />
          </mesh>
        </group>
      ))}
    </group>
  );
}

/** Floor marking for the governance layer: no-entry disc and the slow ring. */
export function ZoneMarking({ zone }: { zone: Zone }) {
  const edge = useRef<THREE.MeshBasicMaterial>(null!);
  useFrame(({ clock }) => {
    if (edge.current) edge.current.opacity = 0.6 + 0.35 * Math.sin(clock.elapsedTime * 4);
  });
  // Vision caution zones have no no-entry radius: only the slow ring is drawn
  const noEntry = zone.radius > 0.1;
  return (
    <group position={[zone.x, 0.016, -zone.y]} rotation={[-Math.PI / 2, 0, 0]}>
      {noEntry && (
        <mesh>
          <circleGeometry args={[zone.radius, 64]} />
          <meshBasicMaterial color="#ef4444" transparent opacity={0.14} depthWrite={false} toneMapped={false} />
        </mesh>
      )}
      {noEntry && (
        <mesh>
          <ringGeometry args={[zone.radius - 0.07, zone.radius, 96]} />
          <meshBasicMaterial ref={edge} color="#ef4444" transparent opacity={0.9} depthWrite={false} toneMapped={false} />
        </mesh>
      )}
      <mesh>
        <ringGeometry args={[zone.slow_radius - 0.04, zone.slow_radius, 96]} />
        <meshBasicMaterial color="#f59e0b" transparent opacity={0.55} depthWrite={false} toneMapped={false} />
      </mesh>
    </group>
  );
}
