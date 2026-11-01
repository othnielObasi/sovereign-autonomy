"use client";
/**
 * Adjustable pallet racking built from the simulator's rack runs: upright frames
 * with bracing, orange step beams, wire decking, end guards, location labels and
 * loaded pallets at mixed heights. Everything is instanced (a few draw calls).
 */
import { useEffect, useMemo } from "react";
import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { labelTexture, loadTexture, meshTexture, rng, uprightTexture, woodTexture, type Rack } from "./textures";

const UPRIGHT_H = 6.4;
const LEVEL_Z = [0.0, 1.6, 3.15, 4.7];
const BEAM_H = 0.12;
const BAY_TARGET = 2.7;
const PALLET_W = 1.2;

type Inst = { p: [number, number, number]; s?: [number, number, number]; r?: [number, number, number] };

function instanced(geo: THREE.BufferGeometry, mat: THREE.Material, items: Inst[], cast = true) {
  const m = new THREE.InstancedMesh(geo, mat, Math.max(1, items.length));
  const o = new THREE.Object3D();
  items.forEach((it, i) => {
    o.position.set(...it.p);
    o.rotation.set(...(it.r ?? [0, 0, 0]));
    o.scale.set(...(it.s ?? [1, 1, 1]));
    o.updateMatrix();
    m.setMatrixAt(i, o.matrix);
  });
  m.count = items.length;
  m.castShadow = cast;
  m.receiveShadow = true;
  m.instanceMatrix.needsUpdate = true;
  m.computeBoundingSphere();
  return m;
}

function palletGeometry() {
  const parts: THREE.BufferGeometry[] = [];
  const add = (w: number, h: number, d: number, x: number, y: number, z: number) => {
    const g = new THREE.BoxGeometry(w, h, d);
    g.translate(x, y, z);
    parts.push(g);
  };
  // top deck boards (along x), stringer blocks, bottom boards
  for (let k = 0; k < 7; k++) add(PALLET_W, 0.022, 0.1, 0, 0.133, -0.45 + k * 0.15);
  for (const x of [-0.55, 0, 0.55]) for (const z of [-0.43, 0, 0.43]) add(0.1, 0.078, 0.14, x, 0.083, z);
  for (const z of [-0.43, 0, 0.43]) add(PALLET_W, 0.022, 0.14, 0, 0.033, z);
  for (const x of [-0.55, 0, 0.55]) add(0.1, 0.022, 1.0, x, 0.011, 0);
  const merged = mergeGeometries(parts)!;
  parts.forEach((part) => part.dispose());
  return merged;
}

export function Racking({ racks }: { racks: Rack[] }) {
  const objects = useMemo(() => {
    const r = rng(42);
    const uprights: Inst[] = [], braces: Inst[] = [], beams: Inst[] = [], decks: Inst[] = [], guards: Inst[] = [], pallets: Inst[] = [], baseplates: Inst[] = [];
    const labelGroups: { id: string; items: Inst[] }[] = [];
    const loads: Inst[][] = [[], [], [], []];

    for (const rk of racks) {
      const labels: Inst[] = [];
      const depth = rk.depth ?? 1;
      const L = rk.x2 - rk.x1;
      const nb = Math.max(1, Math.round(L / BAY_TARGET));
      const bw = L / nb;
      const zf = -rk.y, zb = -(rk.y + depth); // two faces
      const zc = (zf + zb) / 2;
      const levels = Math.min(rk.levels ?? 4, LEVEL_Z.length);

      for (let i = 0; i <= nb; i++) {
        const x = rk.x1 + i * bw;
        for (const z of [zf - 0.04, zb + 0.04]) {
          uprights.push({ p: [x, UPRIGHT_H / 2, z] });
          baseplates.push({ p: [x, 0.006, z], s: [0.18, 0.012, 0.18] });
        }
        // frame bracing: horizontals + diagonals in the y-z plane of the frame
        for (let h = 0.3; h + 1.2 <= UPRIGHT_H - 0.3; h += 1.2) {
          braces.push({ p: [x, h, zc], s: [0.03, 0.03, depth - 0.08] });
          const len = Math.hypot(depth - 0.08, 1.2);
          braces.push({ p: [x, h + 0.6, zc], s: [0.025, len, 0.025], r: [Math.atan2(depth - 0.08, 1.2) * (Math.round(h / 1.2) % 2 ? 1 : -1), 0, 0] });
        }
      }
      for (let i = 0; i < nb; i++) {
        const bx = rk.x1 + (i + 0.5) * bw;
        for (let l = 1; l < levels; l++) {
          const y = LEVEL_Z[l] - BEAM_H / 2;
          beams.push({ p: [bx, y, zf - 0.04], s: [bw - 0.08, BEAM_H, 0.05] });
          beams.push({ p: [bx, y, zb + 0.04], s: [bw - 0.08, BEAM_H, 0.05] });
          decks.push({ p: [bx, LEVEL_Z[l] + 0.005, zc], s: [bw - 0.1, 1, depth] });
        }
        // top beams to finish the frame
        beams.push({ p: [bx, UPRIGHT_H - 0.3, zf - 0.04], s: [bw - 0.08, BEAM_H, 0.05] });
        beams.push({ p: [bx, UPRIGHT_H - 0.3, zb + 0.04], s: [bw - 0.08, BEAM_H, 0.05] });

        // pallet positions: two per bay per level, most occupied
        const slots = Math.max(1, Math.floor((bw - 0.1) / (PALLET_W + 0.1)));
        for (let l = 0; l < levels; l++) {
          for (let s = 0; s < slots; s++) {
            const px = rk.x1 + i * bw + (bw / slots) * (s + 0.5);
            if (l > 0) {
              labels.push({ p: [px, LEVEL_Z[l] - BEAM_H / 2, zf - 0.008], s: [0.22, 0.08, 1] });
              labels.push({ p: [px, LEVEL_Z[l] - BEAM_H / 2, zb + 0.008], s: [0.22, 0.08, 1], r: [0, Math.PI, 0] });
            }
            if (r() < (l === 0 ? 0.55 : 0.82)) {
              const base = LEVEL_Z[l] + (l === 0 ? 0 : 0.01);
              pallets.push({ p: [px, base, zc], s: [1, 1, Math.min(1, depth / 1.0)] });
              const h = 0.75 + r() * 0.65;
              const v = Math.floor(r() * 4);
              loads[v].push({ p: [px + (r() - 0.5) * 0.04, base + 0.144 + h / 2, zc + (r() - 0.5) * 0.04], s: [1.12, h, depth - 0.06], r: [0, (r() - 0.5) * 0.03, 0] });
            }
          }
        }
      }
      labelGroups.push({ id: rk.id, items: labels });
      // end-of-run guards
      for (const x of [rk.x1 - 0.12, rk.x2 + 0.12]) guards.push({ p: [x, 0.2, zc], s: [0.1, 0.4, depth + 0.3] });
    }

    const box = new THREE.BoxGeometry(1, 1, 1);
    const upTex = uprightTexture();
    const meshTex = meshTexture();

    const out: THREE.Object3D[] = [
      instanced(new THREE.BoxGeometry(0.08, UPRIGHT_H, 0.08), new THREE.MeshStandardMaterial({ map: upTex, color: "#ffffff", roughness: 0.45, metalness: 0.5 }), uprights),
      instanced(box, new THREE.MeshStandardMaterial({ color: "#2457b0", roughness: 0.5, metalness: 0.5 }), braces, false),
      instanced(box, new THREE.MeshStandardMaterial({ color: "#e8661c", roughness: 0.42, metalness: 0.35 }), beams),
      instanced(new THREE.BoxGeometry(1, 0.02, 1), new THREE.MeshStandardMaterial({ map: meshTex, color: "#b9bec4", alphaTest: 0.4, transparent: false, metalness: 0.6, roughness: 0.4, side: THREE.DoubleSide }), decks, false),
      instanced(box, new THREE.MeshStandardMaterial({ color: "#f2b600", roughness: 0.5, metalness: 0.3 }), guards),
      instanced(box, new THREE.MeshStandardMaterial({ color: "#5a5f66", roughness: 0.6, metalness: 0.5 }), baseplates, false),
      ...labelGroups.map(({ id, items }) => instanced(new THREE.PlaneGeometry(1, 1), new THREE.MeshStandardMaterial({ map: labelTexture(id, { bg: "#ffffff", fg: "#111", w: 256, h: 96, font: "700 44px Arial" }), roughness: 0.6 }), items, false)),
      instanced(palletGeometry(), new THREE.MeshStandardMaterial({ map: woodTexture(), roughness: 0.85 }), pallets),
    ];
    loads.forEach((items, v) => {
      if (!items.length) return;
      const tex = loadTexture(v);
      // shrink-wrapped cartons: printed faces with a glossy film on top
      const mat = new THREE.MeshPhysicalMaterial({ map: tex, roughness: 0.75, clearcoat: 0.7, clearcoatRoughness: 0.25, sheen: 0.4, sheenColor: new THREE.Color("#ffffff") });
      out.push(instanced(box, mat, items));
    });
    return out;
  }, [racks]);

  useEffect(() => () => {
    const geometries = new Set<THREE.BufferGeometry>();
    const materials = new Set<THREE.Material>();
    const textures = new Set<THREE.Texture>();
    for (const object of objects) {
      const mesh = object as THREE.InstancedMesh;
      geometries.add(mesh.geometry);
      for (const material of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
        materials.add(material);
        for (const value of Object.values(material)) if (value instanceof THREE.Texture) textures.add(value);
      }
      mesh.dispose();
    }
    textures.forEach((texture) => texture.dispose());
    materials.forEach((material) => material.dispose());
    geometries.forEach((geometry) => geometry.dispose());
  }, [objects]);

  return (
    <group>
      {objects.map((o, i) => (
        <primitive key={i} object={o} />
      ))}
    </group>
  );
}
