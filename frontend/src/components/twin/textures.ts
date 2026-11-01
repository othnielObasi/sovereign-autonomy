/**
 * Procedural textures for the warehouse twin. Everything is painted on canvases
 * at load time, so the scene needs no downloaded image assets.
 */
import * as THREE from "three";

export type Rack = { id: string; x1: number; x2: number; y: number; depth?: number; levels?: number };
export type Bay = { id: string; x: number; y: number; side: string; type: string };
export type Feature = { type: string; x: number; y: number; label?: string };
export type Zone = { name: string; rect: { min_x: number; max_x: number; min_y: number; max_y: number } };
export type WorldLayout = {
  geofence: { min_x: number; max_x: number; min_y: number; max_y: number };
  zones: Zone[];
  racks: Rack[];
  bays: Bay[];
  features: Feature[];
  hotspots?: { x: number; y: number }[];
};

/* Deterministic random so the floor looks the same on every load. */
export function rng(seed: number) {
  let s = seed >>> 0 || 1;
  return () => {
    s ^= s << 13;
    s ^= s >>> 17;
    s ^= s << 5;
    return ((s >>> 0) % 100000) / 100000;
  };
}

function canvas(w: number, h: number) {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  return [c, c.getContext("2d")!] as const;
}

function toTexture(c: HTMLCanvasElement, srgb = true, repeat?: [number, number]) {
  const t = new THREE.CanvasTexture(c);
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  if (repeat) {
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(repeat[0], repeat[1]);
  }
  t.needsUpdate = true;
  return t;
}

/** Speckle + blotch noise, the base of concrete, cardboard and wood. */
function noise(ctx: CanvasRenderingContext2D, w: number, h: number, r: () => number, n: number, size: [number, number], alpha: [number, number], light: number) {
  for (let i = 0; i < n; i++) {
    const x = r() * w, y = r() * h;
    const s = size[0] + r() * (size[1] - size[0]);
    const a = alpha[0] + r() * (alpha[1] - alpha[0]);
    const g = ctx.createRadialGradient(x, y, 0, x, y, s);
    const c = r() < light ? "255,255,255" : "0,0,0";
    g.addColorStop(0, `rgba(${c},${a})`);
    g.addColorStop(1, `rgba(${c},0)`);
    ctx.fillStyle = g;
    ctx.fillRect(x - s, y - s, s * 2, s * 2);
  }
}

function speckle(ctx: CanvasRenderingContext2D, w: number, h: number, r: () => number, n: number, alpha: number) {
  for (let i = 0; i < n; i++) {
    const v = r() < 0.5 ? 0 : 255;
    ctx.fillStyle = `rgba(${v},${v},${v},${alpha * r()})`;
    ctx.fillRect(r() * w, r() * h, 1 + r() * 1.5, 1 + r() * 1.5);
  }
}

/* ────────────────────────────────────────────────────────────────── */
/* Floor: polished concrete, joints, wear, and every painted marking   */
/* ────────────────────────────────────────────────────────────────── */

export const FLOOR_PX_PER_M = 64;

export function floorTextures(world: WorldLayout) {
  const g = world.geofence;
  const W = g.max_x - g.min_x, H = g.max_y - g.min_y;
  const S = FLOOR_PX_PER_M;
  const [c, ctx] = canvas(Math.round(W * S), Math.round(H * S));
  const [rc, rctx] = canvas(Math.round(W * 16), Math.round(H * 16)); // roughness, lower res
  const r = rng(7);
  // world (x, y) → canvas px; canvas y runs downward = world y decreasing
  const px = (x: number) => (x - g.min_x) * S;
  const py = (y: number) => (g.max_y - y) * S;

  /* concrete base */
  ctx.fillStyle = "#a3a29c";
  ctx.fillRect(0, 0, c.width, c.height);
  noise(ctx, c.width, c.height, r, 900, [60, 260], [0.025, 0.07], 0.45);
  noise(ctx, c.width, c.height, r, 2500, [6, 30], [0.03, 0.08], 0.5);
  speckle(ctx, c.width, c.height, r, 60000, 0.18);

  /* power-trowel swirls */
  ctx.lineWidth = 1;
  for (let i = 0; i < 260; i++) {
    const x = r() * c.width, y = r() * c.height, rad = 30 + r() * 90;
    ctx.strokeStyle = `rgba(255,255,255,${0.02 + r() * 0.03})`;
    ctx.beginPath();
    ctx.arc(x, y, rad, r() * 6, r() * 6 + 1.5 + r() * 2);
    ctx.stroke();
  }

  /* tyre marks along the aisles and the corridor */
  const lanes = [3.5, 7.5, 11, 13.5, 17, 21];
  for (const ly of lanes) {
    for (let k = 0; k < 6; k++) {
      ctx.strokeStyle = `rgba(30,28,26,${0.03 + r() * 0.05})`;
      ctx.lineWidth = 6 + r() * 10;
      ctx.beginPath();
      const off = (r() - 0.5) * 1.4;
      let x = r() * 4;
      ctx.moveTo(px(x), py(ly + off));
      while (x < W) {
        x += 3 + r() * 5;
        ctx.quadraticCurveTo(px(x - 2), py(ly + off + (r() - 0.5) * 0.6), px(x), py(ly + off + (r() - 0.5) * 0.3));
      }
      ctx.stroke();
    }
  }

  /* stains and oil drips (mostly in the loading bay and corridor) */
  for (let i = 0; i < 70; i++) {
    const x = r() * W, y = 12 + r() * 13;
    const s = (0.2 + r() * 0.9) * S;
    const gr = ctx.createRadialGradient(px(x), py(y), 0, px(x), py(y), s);
    gr.addColorStop(0, `rgba(40,35,30,${0.08 + r() * 0.12})`);
    gr.addColorStop(1, "rgba(40,35,30,0)");
    ctx.fillStyle = gr;
    ctx.beginPath();
    ctx.ellipse(px(x), py(y), s, s * (0.5 + r() * 0.5), r() * 3, 0, Math.PI * 2);
    ctx.fill();
  }

  /* pools of light under the high-bay lamps (they sit on a 5 m grid) */
  for (let x = 2.5; x < W; x += 5)
    for (let y = 2.5; y < H; y += 5) {
      const gr = ctx.createRadialGradient(px(x), py(y), 0, px(x), py(y), 3.2 * S);
      gr.addColorStop(0, "rgba(255,250,238,0.16)");
      gr.addColorStop(1, "rgba(255,250,238,0)");
      ctx.fillStyle = gr;
      ctx.fillRect(px(x) - 3.2 * S, py(y) - 3.2 * S, 6.4 * S, 6.4 * S);
    }

  /* saw-cut joints every 5 m */
  ctx.strokeStyle = "rgba(45,44,42,0.55)";
  ctx.lineWidth = 2;
  for (let x = 5; x < W; x += 5) { ctx.beginPath(); ctx.moveTo(px(x), 0); ctx.lineTo(px(x), c.height); ctx.stroke(); }
  for (let y = 5; y < H; y += 5) { ctx.beginPath(); ctx.moveTo(0, py(y)); ctx.lineTo(c.width, py(y)); ctx.stroke(); }
  ctx.strokeStyle = "rgba(255,255,255,0.12)";
  ctx.lineWidth = 1;
  for (let x = 5; x < W; x += 5) { ctx.beginPath(); ctx.moveTo(px(x) + 2, 0); ctx.lineTo(px(x) + 2, c.height); ctx.stroke(); }

  const paint = document.createElement("canvas");
  paint.width = c.width;
  paint.height = c.height;
  const p = paint.getContext("2d")!;
  const YELLOW = "#e9b400", WHITE = "#eeeeea", GREEN = "#2f8f4e", BLUE = "#2b62b8";
  const band = (x1: number, y1: number, x2: number, y2: number, col: string, wM = 0.1) => {
    p.strokeStyle = col;
    p.lineWidth = wM * S;
    p.lineCap = "butt";
    p.beginPath();
    p.moveTo(px(x1), py(y1));
    p.lineTo(px(x2), py(y2));
    p.stroke();
  };
  const rectLine = (x1: number, y1: number, x2: number, y2: number, col: string, wM = 0.1) => {
    band(x1, y1, x2, y1, col, wM); band(x2, y1, x2, y2, col, wM);
    band(x2, y2, x1, y2, col, wM); band(x1, y2, x1, y1, col, wM);
  };
  const hatch = (x1: number, y1: number, x2: number, y2: number, col: string, step = 0.5, wM = 0.12) => {
    p.save();
    p.beginPath();
    p.rect(px(x1), py(y2), (x2 - x1) * S, (y2 - y1) * S);
    p.clip();
    p.strokeStyle = col;
    p.lineWidth = wM * S;
    for (let d = -(y2 - y1); d < x2 - x1; d += step) {
      p.beginPath();
      p.moveTo(px(x1 + d), py(y1));
      p.lineTo(px(x1 + d + (y2 - y1)), py(y2));
      p.stroke();
    }
    p.restore();
  };
  const stencil = (text: string, x: number, y: number, sizeM: number, col: string, rot = 0, alpha = 0.85) => {
    p.save();
    p.translate(px(x), py(y));
    p.rotate(rot);
    p.globalAlpha = alpha;
    p.fillStyle = col;
    p.font = `800 ${sizeM * S}px "Arial Narrow", Arial, sans-serif`;
    p.textAlign = "center";
    p.textBaseline = "middle";
    p.fillText(text, 0, 0);
    p.restore();
  };
  const arrow = (x: number, y: number, dir: number, col: string, len = 1.6) => {
    p.save();
    p.translate(px(x), py(y));
    p.rotate(-dir);
    p.fillStyle = col;
    p.globalAlpha = 0.85;
    const L = len * S, Wd = 0.22 * S;
    p.beginPath();
    p.moveTo(-L / 2, -Wd / 2); p.lineTo(L / 4, -Wd / 2); p.lineTo(L / 4, -Wd * 1.6);
    p.lineTo(L / 2, 0); p.lineTo(L / 4, Wd * 1.6); p.lineTo(L / 4, Wd / 2); p.lineTo(-L / 2, Wd / 2);
    p.closePath();
    p.fill();
    p.restore();
  };

  /* yellow guard lines around every rack run */
  for (const rk of world.racks) {
    const d = rk.depth ?? 1;
    rectLine(rk.x1 - 0.25, rk.y - 0.25, rk.x2 + 0.25, rk.y + d + 0.25, YELLOW, 0.1);
  }
  /* aisle names */
  const aisleRows = Array.from(new Set(world.racks.map((k) => k.y))).sort((a, b) => a - b);
  for (let i = 0; i + 1 < aisleRows.length; i++) {
    const mid = (aisleRows[i] + 1 + aisleRows[i + 1]) / 2;
    for (const x of [6, 19, 32.5]) stencil(`AISLE 0${i + 1}`, x, mid, 0.55, WHITE, 0, 0.55);
  }
  /* pick-face locations */
  for (const b of world.bays.filter((b) => b.type === "pick")) {
    rectLine(b.x - 0.45, b.y - 0.45, b.x + 0.45, b.y + 0.45, WHITE, 0.05);
    stencil(b.id, b.x, b.y, 0.26, WHITE, 0, 0.75);
  }

  /* corridor: forklift lane with edge lines, centre dashes, arrows */
  const cor = world.zones.find((z) => z.name === "corridor")?.rect;
  if (cor) {
    band(g.min_x, cor.min_y, g.max_x, cor.min_y, YELLOW, 0.12);
    band(g.min_x, cor.max_y, g.max_x, cor.max_y, YELLOW, 0.12);
    const cy = (cor.min_y + cor.max_y) / 2;
    p.setLineDash([1.0 * S, 1.0 * S]);
    band(g.min_x + 1, cy, g.max_x - 1, cy, WHITE, 0.08);
    p.setLineDash([]);
    for (const x of [6, 18, 30]) arrow(x, cy + 0.75, 0, WHITE);
    for (const x of [10, 22, 34]) arrow(x, cy - 0.75, Math.PI, WHITE);
    /* zebra crossings where people cross */
    const xs = Array.from(new Set((world.hotspots ?? []).map((h) => h.x))).filter((x) => x > 1 && x < W - 1);
    for (const x of xs.length ? xs : [12.5, 25.5]) {
      for (let k = 0; k < 6; k++) {
        p.fillStyle = WHITE;
        p.globalAlpha = 0.9;
        p.fillRect(px(x - 1.0), py(cor.min_y + 0.25 + k * 0.45 + 0.25), 2.0 * S, 0.25 * S);
      }
      p.globalAlpha = 1;
    }
  }

  /* staging lanes */
  const stg = world.zones.find((z) => z.name === "staging")?.rect;
  if (stg) {
    for (let x = 2; x + 2.6 < W - 4; x += 3.2) {
      rectLine(x, stg.min_y + 0.5, x + 2.6, stg.max_y - 0.5, WHITE, 0.07);
      stencil(`L${String(Math.round(x / 3.2) + 1).padStart(2, "0")}`, x + 1.3, stg.min_y + 0.95, 0.35, WHITE, 0, 0.6);
    }
  }

  /* loading bay: keep-clear boxes in front of every dock door */
  for (const b of world.bays.filter((b) => b.type === "dock")) {
    hatch(b.x - 1.5, g.max_y - 2.4, b.x + 1.5, g.max_y - 0.05, YELLOW, 0.55, 0.13);
    rectLine(b.x - 1.5, g.max_y - 2.4, b.x + 1.5, g.max_y - 0.05, YELLOW, 0.12);
    stencil(b.id.replace("B-", "DOOR "), b.x, g.max_y - 3.0, 0.45, WHITE, 0, 0.8);
  }
  /* pedestrian walkway along the loading-bay edge */
  const lb = world.zones.find((z) => z.name === "loading_bay")?.rect;
  if (lb) {
    p.fillStyle = GREEN;
    p.globalAlpha = 0.85;
    p.fillRect(px(g.min_x), py(lb.min_y + 0.9), W * S, 0.9 * S);
    p.globalAlpha = 1;
    band(g.min_x, lb.min_y, g.max_x, lb.min_y, WHITE, 0.08);
    band(g.min_x, lb.min_y + 0.9, g.max_x, lb.min_y + 0.9, WHITE, 0.08);
    for (const x of [5, 20, 35]) stencil("PEDESTRIANS", x, lb.min_y + 0.45, 0.42, WHITE, 0, 0.9);
  }

  /* charging pads and packing stations */
  for (const f of world.features) {
    if (f.type === "charging_station") {
      p.fillStyle = BLUE;
      p.globalAlpha = 0.8;
      p.fillRect(px(f.x - 0.8), py(f.y + 0.9), 1.6 * S, 1.8 * S);
      p.globalAlpha = 1;
      rectLine(f.x - 0.8, f.y - 0.9, f.x + 0.8, f.y + 0.9, WHITE, 0.06);
      stencil("⚡", f.x, f.y - 0.1, 0.8, WHITE, 0, 0.9);
      stencil(f.label ?? "CHG", f.x, f.y - 0.7, 0.24, WHITE, 0, 0.9);
    }
    if (f.type === "packing_station") rectLine(f.x - 1.1, f.y - 0.8, f.x + 1.1, f.y + 0.8, YELLOW, 0.08);
  }
  /* robot home */
  rectLine(1.8, 2.6, 4.2, 4.4, "#13a3b8", 0.08);
  stencil("AMR HOME", 3, 2.85, 0.22, "#13a3b8", 0, 0.9);

  /* fade, scuff and lay the paint onto the concrete */
  const pctx = p;
  pctx.save();
  pctx.globalCompositeOperation = "destination-out";
  for (let i = 0; i < 90000; i++) {
    pctx.fillStyle = `rgba(0,0,0,${0.1 + r() * 0.5})`;
    pctx.fillRect(r() * paint.width, r() * paint.height, 1 + r() * 3, 1 + r() * 2);
  }
  pctx.restore();
  ctx.globalAlpha = 0.92;
  ctx.drawImage(paint, 0, 0);
  ctx.globalAlpha = 1;

  /* roughness: mostly satin with polished patches that catch the lights */
  rctx.fillStyle = "rgb(150,150,150)";
  rctx.fillRect(0, 0, rc.width, rc.height);
  noise(rctx, rc.width, rc.height, r, 500, [20, 90], [0.1, 0.3], 0.35);
  rctx.globalAlpha = 0.6;
  rctx.drawImage(paint, 0, 0, rc.width, rc.height); // paint is a bit smoother
  rctx.globalAlpha = 1;

  const map = toTexture(c);
  const roughnessMap = toTexture(rc, false);
  return { map, roughnessMap };
}

/* ────────────────────────────────────────────────────────────────── */
/* Small material textures                                            */
/* ────────────────────────────────────────────────────────────────── */

/** A pallet load face: cartons stacked in rows, with tape and labels. */
export function loadTexture(variant: number) {
  const [c, ctx] = canvas(512, 512);
  const r = rng(100 + variant);
  const palettes = [
    ["#b88752", "#a97a47", "#c29461"],
    ["#b88752", "#e9e6dd", "#a97a47"],
    ["#b88752", "#2f5d9e", "#b07f4b"],
    ["#9c7448", "#b18556", "#c49a6a"],
  ][variant % 4];
  const rows = 3 + (variant % 2), cols = 2 + ((variant + 1) % 2);
  const cw = 512 / cols, ch = 512 / rows;
  for (let i = 0; i < cols; i++)
    for (let j = 0; j < rows; j++) {
      const off = j % 2 ? cw / 2 : 0;
      for (const dx of [0, -cw]) {
        const x = i * cw + off + dx, y = j * ch;
        ctx.fillStyle = palettes[Math.floor(r() * palettes.length)];
        ctx.fillRect(x, y, cw, ch);
        ctx.fillStyle = "rgba(0,0,0,0.05)";
        ctx.fillRect(x, y + ch * 0.45, cw, ch * 0.1); // tape band shadow
        ctx.fillStyle = "rgba(255,240,210,0.22)";
        ctx.fillRect(x, y + ch * 0.46, cw, ch * 0.08); // tape
        if (r() < 0.7) {
          ctx.fillStyle = "#f7f7f2";
          const lw = cw * 0.32, lh = ch * 0.26;
          const lx = x + cw * 0.08 + r() * cw * 0.1, ly = y + ch * 0.1;
          ctx.fillRect(lx, ly, lw, lh);
          ctx.fillStyle = "#222";
          for (let b = 0; b < 18; b++) if (r() < 0.6) ctx.fillRect(lx + 4 + b * (lw - 8) / 18, ly + lh * 0.45, (lw - 8) / 36, lh * 0.45);
          ctx.fillRect(lx + 4, ly + 4, lw * 0.5, 3);
          ctx.fillRect(lx + 4, ly + 10, lw * 0.35, 2);
        }
        ctx.strokeStyle = "rgba(60,40,20,0.55)";
        ctx.lineWidth = 2;
        ctx.strokeRect(x + 1, y + 1, cw - 2, ch - 2);
      }
    }
  speckle(ctx, 512, 512, r, 9000, 0.12);
  /* shrink wrap: soft vertical streaks */
  for (let i = 0; i < 40; i++) {
    ctx.fillStyle = `rgba(255,255,255,${0.02 + r() * 0.05})`;
    ctx.fillRect(r() * 512, 0, 2 + r() * 14, 512);
  }
  return toTexture(c);
}

export function woodTexture() {
  const [c, ctx] = canvas(256, 256);
  const r = rng(3);
  ctx.fillStyle = "#b08a5a";
  ctx.fillRect(0, 0, 256, 256);
  for (let y = 0; y < 256; y += 1) {
    ctx.fillStyle = `rgba(${r() < 0.5 ? "60,40,20" : "230,200,160"},${0.04 + r() * 0.06})`;
    ctx.fillRect(0, y, 256, 1);
  }
  for (let i = 0; i < 6; i++) {
    ctx.fillStyle = "rgba(70,45,20,0.35)";
    ctx.beginPath();
    ctx.ellipse(r() * 256, r() * 256, 3 + r() * 5, 2 + r() * 2, 0, 0, Math.PI * 2);
    ctx.fill();
  }
  speckle(ctx, 256, 256, r, 3000, 0.15);
  return toTexture(c);
}

/** Pallet-rack upright: blue steel with teardrop slots. */
export function uprightTexture() {
  const [c, ctx] = canvas(32, 256);
  ctx.fillStyle = "#1f4fa3";
  ctx.fillRect(0, 0, 32, 256);
  ctx.fillStyle = "#0b1a33";
  for (let y = 4; y < 256; y += 10) {
    ctx.beginPath();
    ctx.ellipse(16, y + 3, 3, 4, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillRect(14.5, y + 5, 3, 3);
  }
  ctx.fillStyle = "rgba(255,255,255,0.08)";
  ctx.fillRect(0, 0, 3, 256);
  return toTexture(c, true, [1, 6]);
}

/** Wall cladding: profiled metal sheet. */
export function claddingTexture() {
  const [c, ctx] = canvas(256, 64);
  for (let x = 0; x < 256; x++) {
    const ph = (x % 32) / 32;
    const v = ph < 0.18 ? 200 : ph < 0.25 ? 238 : ph < 0.75 ? 222 : ph < 0.82 ? 196 : 214;
    ctx.fillStyle = `rgb(${v},${v + 2},${v + 4})`;
    ctx.fillRect(x, 0, 1, 64);
  }
  const r = rng(9);
  speckle(ctx, 256, 64, r, 800, 0.06);
  return toTexture(c, true, [24, 2]);
}

export function roofTexture() {
  const [c, ctx] = canvas(256, 64);
  for (let x = 0; x < 256; x++) {
    const ph = (x % 32) / 32;
    const v = ph < 0.3 ? 120 : ph < 0.4 ? 150 : 132;
    ctx.fillStyle = `rgb(${v},${v + 3},${v + 6})`;
    ctx.fillRect(x, 0, 1, 64);
  }
  return toTexture(c, true, [20, 1]);
}

/** Hi-vis vest for a cylinder torso facing +x: u=0.25 is the front, 0.75 the back. */
export function vestTexture(orange = false) {
  const [c, ctx] = canvas(256, 128);
  ctx.fillStyle = orange ? "#ff6a13" : "#cdf20a";
  ctx.fillRect(0, 0, 256, 128);
  // subtle fabric folds
  for (let i = 0; i < 30; i++) {
    ctx.fillStyle = `rgba(0,0,0,${0.03 + Math.random() * 0.04})`;
    ctx.fillRect(Math.random() * 256, 0, 2 + Math.random() * 5, 128);
  }
  const silver = "#d7dadc";
  ctx.fillStyle = silver;
  ctx.fillRect(0, 74, 256, 11); // two reflective bands round the waist
  ctx.fillRect(0, 98, 256, 11);
  // braces over the shoulders, front and back
  for (const u of [0.25, 0.75]) {
    ctx.fillRect(u * 256 - 30, 0, 11, 74);
    ctx.fillRect(u * 256 + 19, 0, 11, 74);
  }
  // front zip and a small chest badge
  ctx.fillStyle = "rgba(40,40,40,0.55)";
  ctx.fillRect(64 - 1, 0, 2, 128);
  ctx.fillStyle = "#1d3d6b";
  ctx.fillRect(64 + 6, 34, 14, 9);
  return toTexture(c);
}

/** Text on a plate, for signs, beam labels and decals. */
export function labelTexture(text: string, opts: { bg?: string; fg?: string; w?: number; h?: number; font?: string; border?: string; sub?: string } = {}) {
  const w = opts.w ?? 512, h = opts.h ?? 128;
  const [c, ctx] = canvas(w, h);
  ctx.fillStyle = opts.bg ?? "#ffffff";
  ctx.fillRect(0, 0, w, h);
  if (opts.border) {
    ctx.strokeStyle = opts.border;
    ctx.lineWidth = h * 0.08;
    ctx.strokeRect(ctx.lineWidth / 2, ctx.lineWidth / 2, w - ctx.lineWidth, h - ctx.lineWidth);
  }
  ctx.fillStyle = opts.fg ?? "#111";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.font = opts.font ?? `800 ${h * (opts.sub ? 0.42 : 0.56)}px Arial, sans-serif`;
  ctx.fillText(text, w / 2, opts.sub ? h * 0.38 : h / 2);
  if (opts.sub) {
    ctx.font = `600 ${h * 0.22}px Arial, sans-serif`;
    ctx.fillText(opts.sub, w / 2, h * 0.76);
  }
  return toTexture(c);
}

/** Wire-mesh decking for rack levels (alpha-tested). */
export function meshTexture() {
  const [c, ctx] = canvas(64, 64);
  ctx.clearRect(0, 0, 64, 64);
  ctx.strokeStyle = "#9aa0a6";
  ctx.lineWidth = 2;
  for (let i = 0; i <= 64; i += 8) {
    ctx.beginPath(); ctx.moveTo(i, 0); ctx.lineTo(i, 64); ctx.stroke();
  }
  ctx.lineWidth = 3;
  for (let i = 0; i <= 64; i += 32) {
    ctx.beginPath(); ctx.moveTo(0, i); ctx.lineTo(64, i); ctx.stroke();
  }
  return toTexture(c, true, [10, 1]);
}
