"use client";
/**
 * Factory equipment from the site layout: machine tools, the fenced welding cell with
 * its robot arm, and the assembly line. Same footprints the gate and router treat as solid.
 */
import React from "react";

type Item = { id: string; kind?: string; label?: string; x1: number; x2: number; y: number; depth?: number };

export function Equipment({ items }: { items: Item[] }) {
  return (
    <group>
      {items.filter((it) => it.kind && it.kind !== "rack").map((it) => {
        const depth = it.depth ?? 1;
        const w = it.x2 - it.x1;
        const cx = (it.x1 + it.x2) / 2;
        const cz = -(it.y + depth / 2);
        if (it.kind === "machine")
          return (
            <group key={it.id} position={[cx, 0, cz]}>
              <mesh position={[0, 1.0, 0]} castShadow receiveShadow>
                <boxGeometry args={[w, 2.0, depth]} />
                <meshStandardMaterial color="#64748b" metalness={0.5} roughness={0.45} />
              </mesh>
              <mesh position={[0, 2.05, 0]} castShadow>
                <boxGeometry args={[w * 0.92, 0.1, depth * 0.92]} />
                <meshStandardMaterial color="#e2e8f0" roughness={0.6} />
              </mesh>
              <mesh position={[0, 1.2, depth / 2 + 0.01]}>
                <planeGeometry args={[w * 0.5, 0.8]} />
                <meshStandardMaterial color="#0b1220" emissive="#0ea5e9" emissiveIntensity={0.35} />
              </mesh>
              <mesh position={[w / 2 - 0.25, 2.35, depth / 2 - 0.25]}>
                <cylinderGeometry args={[0.06, 0.06, 0.5, 12]} />
                <meshStandardMaterial color="#000" emissive="#22c55e" emissiveIntensity={2} toneMapped={false} />
              </mesh>
            </group>
          );
        if (it.kind === "cell")
          return (
            <group key={it.id} position={[cx, 0, cz]}>
              {/* safety fence: posts and translucent mesh panels */}
              {[[-w / 2, 0, depth], [w / 2, 0, depth], [0, -depth / 2, w], [0, depth / 2, w]].map(([x, z, len], i) => (
                <mesh key={i} position={[x, 1.1, z]} rotation={[0, i < 2 ? Math.PI / 2 : 0, 0]}>
                  <planeGeometry args={[len as number, 2.2]} />
                  <meshStandardMaterial color="#fca5a5" transparent opacity={0.22} side={2} />
                </mesh>
              ))}
              {[[-w / 2, -depth / 2], [w / 2, -depth / 2], [-w / 2, depth / 2], [w / 2, depth / 2]].map(([x, z], i) => (
                <mesh key={`p${i}`} position={[x, 1.1, z]} castShadow>
                  <boxGeometry args={[0.08, 2.2, 0.08]} />
                  <meshStandardMaterial color="#facc15" />
                </mesh>
              ))}
              {/* robot arm on a pedestal */}
              <mesh position={[0, 0.4, 0]} castShadow>
                <cylinderGeometry args={[0.35, 0.45, 0.8, 20]} />
                <meshStandardMaterial color="#f97316" roughness={0.4} />
              </mesh>
              <mesh position={[0.35, 1.25, 0]} rotation={[0, 0, -0.6]} castShadow>
                <boxGeometry args={[0.22, 1.3, 0.22]} />
                <meshStandardMaterial color="#f97316" roughness={0.4} />
              </mesh>
              <mesh position={[0.9, 1.55, 0]} rotation={[0, 0, 1.0]} castShadow>
                <boxGeometry args={[0.16, 0.9, 0.16]} />
                <meshStandardMaterial color="#f97316" roughness={0.4} />
              </mesh>
              <mesh position={[1.25, 1.3, 0]}>
                <sphereGeometry args={[0.09, 12, 12]} />
                <meshStandardMaterial color="#000" emissive="#60a5fa" emissiveIntensity={3} toneMapped={false} />
              </mesh>
            </group>
          );
        if (it.kind === "conveyor")
          return (
            <group key={it.id} position={[cx, 0, cz]}>
              <mesh position={[0, 0.85, 0]} castShadow receiveShadow>
                <boxGeometry args={[w, 0.12, depth]} />
                <meshStandardMaterial color="#1e3a8a" roughness={0.6} />
              </mesh>
              {Array.from({ length: Math.max(2, Math.round(w / 2)) + 1 }, (_, i) => -w / 2 + (i * w) / Math.max(2, Math.round(w / 2))).map((x, i) => (
                <mesh key={i} position={[x, 0.4, 0]} castShadow>
                  <boxGeometry args={[0.08, 0.8, depth * 0.9]} />
                  <meshStandardMaterial color="#6b7280" metalness={0.6} roughness={0.35} />
                </mesh>
              ))}
              {Array.from({ length: 5 }, (_, i) => -w / 2 + ((i + 0.5) * w) / 5).map((x, i) => (
                <mesh key={`b${i}`} position={[x, 1.03, 0]} castShadow>
                  <boxGeometry args={[0.5, 0.25, 0.45]} />
                  <meshStandardMaterial color="#b88752" roughness={0.8} />
                </mesh>
              ))}
            </group>
          );
        return null;
      })}
    </group>
  );
}
