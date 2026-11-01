"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

function clamp(v: number, a: number, b: number) {
  return Math.max(a, Math.min(b, v));
}

type Pt = { x: number; y: number };

function dist(a: Pt, b: Pt) {
  return Math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2);
}

/* ── Colour palette ────────────────────────────────────────────── */
const C = {
  floor: "#1a1f2e",
  floorAisle: "#1e2436",
  floorBay: "#1a2a1f",
  gridLine: "rgba(100,116,139,0.12)",
  gridMajor: "rgba(100,116,139,0.25)",
  border: "#334155",
  shelf: "#374151",
  shelfTop: "#4b5563",
  obstacle: "#dc2626",
  obsBorder: "#991b1b",
  human: "#f59e0b",
  humanDanger: "rgba(239,68,68,0.20)",
  humanCaution: "rgba(245,158,11,0.10)",
  robot: "#06b6d4",
  robotDark: "#0e7490",
  robotGlow: "rgba(6,182,212,0.25)",
  path: "#3b82f6",
  target: "#10b981",
  plan: "#a855f7",
  zoneLabel: "rgba(148,163,184,0.50)",
  text: "#cbd5e1",
  textDim: "#64748b",
};

/**
 * Warehouse-style 2D operator map.
 *
 * Dark floor, zone differentiation, shelf racks, risk heatmap,
 * robot with heading + safety radius, human with proximity rings,
 * obstacle crates, path preview, LLM plan waypoints, trail, HUD.
 */
export function Map2D({
  world,
  telemetry,
  pathPoints,
  planWaypoints,
  missionGoal,
  showHeatmap = true,
  showTrail = true,
  safetyState = "OK",
  hoveredWaypointIdx = null,
  riskCells = [],
  executedPath = [],
  destinationBayId = null,
  fullscreenTargetRef,
  trailPoints,
}: {
  world: any | null;
  telemetry: any | null;
  pathPoints: Array<Pt> | null;
  planWaypoints?: Array<Pt & { max_speed?: number }> | null;
  missionGoal?: Pt | null;
  showHeatmap?: boolean;
  showTrail?: boolean;
  safetyState?: string;
  hoveredWaypointIdx?: number | null;
  riskCells?: Array<{ x: number; y: number; risk: number }>;
  executedPath?: Array<Pt>;
  destinationBayId?: string | null;
  fullscreenTargetRef?: React.RefObject<HTMLElement | null>;
  trailPoints?: Pt[];
}) {
  const ref = useRef<HTMLCanvasElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const minimapRef = useRef<HTMLCanvasElement | null>(null);
  const [size, setSize] = useState({ w: 600, h: 380 });
  const W = size.w;
  const H = size.h;
  const [isFullscreen, setIsFullscreen] = useState(() => typeof document !== "undefined" && !!document.fullscreenElement);

  const geo = world?.geofence ?? { min_x: 0, max_x: 40, min_y: 0, max_y: 25 };
  const zones: any[] = world?.zones ?? [];
  const obstacles: any[] = telemetry?.obstacles ?? world?.obstacles ?? [];
  const human = telemetry?.human ?? world?.human ?? null;
  const walkingHumans: any[] = telemetry?.walking_humans ?? world?.walking_humans ?? [];
  const idleRobots: any[] = telemetry?.idle_robots ?? world?.idle_robots ?? [];
  const bays: any[] = world?.bays ?? [];

  const baseScale = useMemo(() => {
    const wx = (geo.max_x - geo.min_x) || 1;
    const wy = (geo.max_y - geo.min_y) || 1;
    return Math.min((W - 40) / wx, (H - 40) / wy);
  }, [geo, W, H]);

  const pad = useMemo(
    () => ({
      x: (W - (geo.max_x - geo.min_x) * baseScale) / 2,
      y: (H - (geo.max_y - geo.min_y) * baseScale) / 2,
    }),
    [baseScale, geo, W, H],
  );

  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [tick, setTick] = useState(0);

  const dragging = useRef(false);
  const lastMouse = useRef<Pt | null>(null);
  const trailRef = useRef<Pt[]>([]);

  /* ── ResizeObserver: track container size ──────────────────── */
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        const { width, height } = e.contentRect;
        if (width > 0 && height > 0) {
          setSize({ w: Math.round(width), h: Math.round(height) });
        }
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  /* ── Fullscreen toggle ─────────────────────────────────────── */
  const toggleFullscreen = useCallback(() => {
    const el = fullscreenTargetRef?.current || containerRef.current;
    if (!el) return;
    if (!document.fullscreenElement) {
      el.requestFullscreen().catch(() => {});
    } else {
      document.exitFullscreen().catch(() => {});
    }
  }, [fullscreenTargetRef]);

  useEffect(() => {
    const handler = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", handler);
    return () => document.removeEventListener("fullscreenchange", handler);
  }, []);

  /* pulse timer */
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 60);
    return () => clearInterval(id);
  }, []);

  /* ── Coordinate helpers ────────────────────────────────────── */
  function w2c(p: Pt) {
    const sx = pad.x + (p.x - geo.min_x) * baseScale;
    const sy = H - pad.y - (p.y - geo.min_y) * baseScale;
    return { x: sx * zoom + pan.x, y: sy * zoom + pan.y };
  }
  function c2w(p: Pt) {
    const sx = (p.x - pan.x) / Math.max(zoom, 1e-6);
    const sy = (p.y - pan.y) / Math.max(zoom, 1e-6);
    return {
      x: (sx - pad.x) / baseScale + geo.min_x,
      y: (H - pad.y - sy) / baseScale + geo.min_y,
    };
  }

  /* ── Pointer interactions (zoom + pan) ────────────────────── */
  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = cv.getBoundingClientRect();
      const cx = e.clientX - r.left;
      const cy = e.clientY - r.top;
      const f = e.deltaY > 0 ? 0.9 : 1.1;
      const before = c2w({ x: cx, y: cy });
      const nz = clamp(zoom * f, 0.6, 6);
      setZoom(nz);
      const sx = pad.x + (before.x - geo.min_x) * baseScale;
      const sy = H - pad.y - (before.y - geo.min_y) * baseScale;
      setPan({ x: cx - sx * nz, y: cy - sy * nz });
    };
    const onDown = (e: PointerEvent) => {
      dragging.current = true;
      lastMouse.current = { x: e.clientX, y: e.clientY };
      cv.setPointerCapture(e.pointerId);
    };
    const onMove = (e: PointerEvent) => {
      if (!dragging.current || !lastMouse.current) return;
      const dx = e.clientX - lastMouse.current.x;
      const dy = e.clientY - lastMouse.current.y;
      lastMouse.current = { x: e.clientX, y: e.clientY };
      setPan((p) => ({ x: p.x + dx, y: p.y + dy }));
    };
    const onUp = (e: PointerEvent) => {
      dragging.current = false;
      lastMouse.current = null;
      try { cv.releasePointerCapture(e.pointerId); } catch {}
    };
    cv.addEventListener("wheel", onWheel, { passive: false });
    cv.addEventListener("pointerdown", onDown);
    cv.addEventListener("pointermove", onMove);
    cv.addEventListener("pointerup", onUp);
    cv.addEventListener("pointercancel", onUp);
    return () => {
      cv.removeEventListener("wheel", onWheel as any);
      cv.removeEventListener("pointerdown", onDown as any);
      cv.removeEventListener("pointermove", onMove as any);
      cv.removeEventListener("pointerup", onUp as any);
      cv.removeEventListener("pointercancel", onUp as any);
    };
  }, [zoom, baseScale, geo.min_x, geo.min_y, pad]);

  /* ── Trail accumulation ────────────────────────────────────── */
  useEffect(() => {
    if (!telemetry) return;
    const next = { x: Number(telemetry.x ?? 0), y: Number(telemetry.y ?? 0) };
    const t = trailRef.current;
    const last = t.length ? t[t.length - 1] : null;
    if (!last || dist(last, next) > 0.03) {
      t.push(next);
      if (t.length > 300) t.splice(0, t.length - 300);
    }
  }, [telemetry]);

  /* ════════════════════════════════════════════════════════════ */
  /*  MAIN DRAW                                                  */
  /* ════════════════════════════════════════════════════════════ */
  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const pulse = Math.sin(tick * 0.12) * 0.5 + 0.5;

    /* background */
    ctx.fillStyle = C.floor;
    ctx.fillRect(0, 0, W, H);

    /* ── zones ──────────────────────────────────────────────── */
    for (const z of zones) {
      const r = z.rect;
      if (!r) continue;
      const tl = w2c({ x: r.min_x, y: r.max_y });
      const br = w2c({ x: r.max_x, y: r.min_y });
      const zw = br.x - tl.x,
        zh = br.y - tl.y;

      if (z.name === "loading_bay") {
        ctx.fillStyle = C.floorBay;
        ctx.fillRect(tl.x, tl.y, zw, zh);
        ctx.save();
        ctx.setLineDash([8, 6]);
        ctx.strokeStyle = "rgba(245,158,11,0.3)";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(tl.x, tl.y);
        ctx.lineTo(br.x, tl.y);
        ctx.stroke();
        ctx.restore();
      } else if (z.name === "staging") {
        ctx.fillStyle = "#1a2230";
        ctx.fillRect(tl.x, tl.y, zw, zh);
        ctx.save();
        ctx.setLineDash([4, 4]);
        ctx.strokeStyle = "rgba(168,85,247,0.25)";
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(tl.x, tl.y);
        ctx.lineTo(br.x, tl.y);
        ctx.stroke();
        ctx.restore();
      } else if (z.name === "corridor") {
        ctx.fillStyle = "#1e2838";
        ctx.fillRect(tl.x, tl.y, zw, zh);
      } else {
        ctx.fillStyle = C.floorAisle;
        ctx.fillRect(tl.x, tl.y, zw, zh);
      }
      /* zone name tucked into the zone's top-left corner, clear of robots and people */
      ctx.fillStyle = C.zoneLabel;
      ctx.font = `bold ${Math.max(10, 11 * zoom)}px system-ui`;
      ctx.textAlign = "left";
      ctx.textBaseline = "top";
      const zoneText = z.name.toUpperCase().replace("_", " ");
      ctx.strokeStyle = "rgba(0,0,0,0.5)";
      ctx.lineWidth = 3;
      ctx.strokeText(zoneText, tl.x + 6, tl.y + 4);
      ctx.fillText(zoneText, tl.x + 6, tl.y + 4);
    }

    /* ── warehouse bays (docks, picks, staging) ────────────── */
    for (const bay of bays) {
      if (typeof bay.x !== "number") continue;
      const p = w2c({ x: +bay.x, y: +bay.y });
      const isDock = bay.type === "dock";
      const isPick = bay.type === "pick";
      const isStaging = bay.type === "staging";
      const bw = isDock ? 4 * baseScale * zoom : 1.5 * baseScale * zoom;
      const bh = isDock ? 1.2 * baseScale * zoom : 3 * baseScale * zoom;

      if (isDock) {
        /* dock bay — wide rectangle at top wall */
        ctx.fillStyle = "rgba(245,158,11,0.08)";
        ctx.strokeStyle = "rgba(245,158,11,0.35)";
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.roundRect(p.x - bw / 2, p.y - bh / 2, bw, bh, 2);
        ctx.fill();
        ctx.stroke();

        /* dock chevron markers */
        ctx.strokeStyle = "rgba(245,158,11,0.25)";
        ctx.lineWidth = 1;
        for (let ci = -1; ci <= 1; ci += 2) {
          ctx.beginPath();
          ctx.moveTo(p.x + ci * bw * 0.15, p.y - bh * 0.3);
          ctx.lineTo(p.x + ci * bw * 0.25, p.y);
          ctx.lineTo(p.x + ci * bw * 0.15, p.y + bh * 0.3);
          ctx.stroke();
        }
      } else if (isPick) {
        /* pick face — small diamond marker in aisle */
        const ds = Math.max(4, 5 * zoom);
        ctx.fillStyle = "rgba(59,130,246,0.12)";
        ctx.strokeStyle = "rgba(59,130,246,0.45)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(p.x, p.y - ds);
        ctx.lineTo(p.x + ds, p.y);
        ctx.lineTo(p.x, p.y + ds);
        ctx.lineTo(p.x - ds, p.y);
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
      } else if (isStaging) {
        /* staging — small square marker */
        const ss = Math.max(4, 5 * zoom);
        ctx.fillStyle = "rgba(168,85,247,0.1)";
        ctx.strokeStyle = "rgba(168,85,247,0.35)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.roundRect(p.x - ss, p.y - ss, ss * 2, ss * 2, 2);
        ctx.fill();
        ctx.stroke();
      } else {
        /* shelf bay — narrow vertical rectangle on walls */
        ctx.fillStyle = "rgba(100,116,139,0.1)";
        ctx.strokeStyle = "rgba(100,116,139,0.3)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.roundRect(p.x - bw / 2, p.y - bh / 2, bw, bh, 1);
        ctx.fill();
        ctx.stroke();

        /* shelf lines */
        for (let s = 0.25; s < 1; s += 0.25) {
          const sy = p.y - bh / 2 + bh * s;
          ctx.strokeStyle = "rgba(100,116,139,0.2)";
          ctx.beginPath();
          ctx.moveTo(p.x - bw / 2 + 1, sy);
          ctx.lineTo(p.x + bw / 2 - 1, sy);
          ctx.stroke();
        }
      }

      /* bay label */
      const labelColor = isDock ? "rgba(245,158,11,0.6)"
        : isPick ? "rgba(59,130,246,0.55)"
        : isStaging ? "rgba(168,85,247,0.5)"
        : "rgba(148,163,184,0.5)";
      ctx.fillStyle = labelColor;
      ctx.font = `bold ${Math.max(7, 8 * zoom)}px monospace`;
      ctx.textAlign = "center";
      ctx.textBaseline = isDock ? "top" : "middle";
      ctx.fillText(bay.id, p.x, isDock ? p.y + bh / 2 + 2 : p.y + (isPick ? 8 * zoom : 0));
    }

    /* ── grid ───────────────────────────────────────────────── */
    for (let wx = Math.ceil(geo.min_x); wx <= geo.max_x; wx++) {
      const p = w2c({ x: wx, y: 0 });
      ctx.strokeStyle = wx % 5 === 0 ? C.gridMajor : C.gridLine;
      ctx.lineWidth = wx % 5 === 0 ? 1 : 0.5;
      ctx.beginPath();
      ctx.moveTo(p.x, 0);
      ctx.lineTo(p.x, H);
      ctx.stroke();
    }
    for (let wy = Math.ceil(geo.min_y); wy <= geo.max_y; wy++) {
      const p = w2c({ x: 0, y: wy });
      ctx.strokeStyle = wy % 5 === 0 ? C.gridMajor : C.gridLine;
      ctx.lineWidth = wy % 5 === 0 ? 1 : 0.5;
      ctx.beginPath();
      ctx.moveTo(0, p.y);
      ctx.lineTo(W, p.y);
      ctx.stroke();
    }

    /* axis labels */
    ctx.fillStyle = C.textDim;
    ctx.font = `${Math.max(8, 9 * zoom)}px monospace`;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (let wx = 0; wx <= geo.max_x; wx += 5) {
      const p = w2c({ x: wx, y: geo.min_y });
      ctx.fillText(`${wx}m`, p.x, Math.min(p.y + 4, H - 12));
    }
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (let wy = 0; wy <= geo.max_y; wy += 5) {
      const p = w2c({ x: geo.min_x, y: wy });
      ctx.fillText(`${wy}m`, Math.max(p.x - 4, 24), p.y);
    }

    /* ── rack rows (data-driven from world.racks) ──────────── */
    const racks: { id: string; x1: number; x2: number; y: number; depth: number; levels?: number }[] = world?.racks ?? [];
    for (const rack of racks) {
      const depth = rack.depth ?? 1.0;
      const tl = w2c({ x: rack.x1, y: rack.y + depth });
      const br = w2c({ x: rack.x2, y: rack.y });
      const rw = br.x - tl.x,
        rh = br.y - tl.y;
      /* rack body */
      ctx.fillStyle = C.shelf;
      ctx.strokeStyle = C.shelfTop;
      ctx.lineWidth = 1;
      ctx.fillRect(tl.x, tl.y, rw, rh);
      ctx.strokeRect(tl.x, tl.y, rw, rh);
      /* upright dividers every ~2m */
      const span = rack.x2 - rack.x1;
      const segs = Math.max(1, Math.round(span / 2));
      for (let i = 1; i < segs; i++) {
        const sx = rack.x1 + (i * span) / segs;
        const sp = w2c({ x: sx, y: rack.y });
        ctx.strokeStyle = "rgba(100,116,139,0.35)";
        ctx.beginPath();
        ctx.moveTo(sp.x, tl.y);
        ctx.lineTo(sp.x, tl.y + rh);
        ctx.stroke();
      }
      /* horizontal shelf lines for multi-level racks */
      const levels = rack.levels ?? 1;
      if (levels > 1) {
        for (let lv = 1; lv < levels; lv++) {
          const ly = tl.y + (rh * lv) / levels;
          ctx.strokeStyle = "rgba(100,116,139,0.18)";
          ctx.beginPath();
          ctx.moveTo(tl.x + 1, ly);
          ctx.lineTo(tl.x + rw - 1, ly);
          ctx.stroke();
        }
      }
      /* rack label */
      ctx.fillStyle = "rgba(148,163,184,0.45)";
      ctx.font = `${Math.max(7, 8 * zoom)}px monospace`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(rack.id, tl.x + rw / 2, tl.y + rh / 2);
    }

    /* ── features (charging, packing, fire exits) ───────────── */
    const features: { type: string; x: number; y: number; label: string }[] = world?.features ?? [];
    for (const feat of features) {
      const p = w2c({ x: feat.x, y: feat.y });
      const sz = Math.max(6, 7 * zoom);
      if (feat.type === "charging_station") {
        ctx.fillStyle = "rgba(34,197,94,0.15)";
        ctx.strokeStyle = "rgba(34,197,94,0.5)";
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(p.x, p.y, sz, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        /* lightning bolt */
        ctx.fillStyle = "rgba(34,197,94,0.7)";
        ctx.font = `bold ${Math.max(10, 12 * zoom)}px system-ui`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText("⚡", p.x, p.y);
      } else if (feat.type === "packing_station") {
        ctx.fillStyle = "rgba(168,85,247,0.12)";
        ctx.strokeStyle = "rgba(168,85,247,0.4)";
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.roundRect(p.x - sz, p.y - sz * 0.7, sz * 2, sz * 1.4, 3);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = "rgba(168,85,247,0.6)";
        ctx.font = `bold ${Math.max(8, 9 * zoom)}px system-ui`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText("📦", p.x, p.y);
      } else if (feat.type === "fire_exit") {
        ctx.fillStyle = "rgba(239,68,68,0.15)";
        ctx.strokeStyle = "rgba(239,68,68,0.5)";
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.roundRect(p.x - sz * 0.6, p.y - sz, sz * 1.2, sz * 2, 2);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = "rgba(239,68,68,0.7)";
        ctx.font = `bold ${Math.max(8, 9 * zoom)}px system-ui`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText("🚪", p.x, p.y);
      }
      /* feature label */
      ctx.fillStyle = "rgba(148,163,184,0.5)";
      ctx.font = `${Math.max(6, 7 * zoom)}px monospace`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillText(feat.label, p.x, p.y + sz + 2);
    }

    /* ── geofence border ────────────────────────────────────── */
    const gf0 = w2c({ x: geo.min_x, y: geo.max_y });
    const gf1 = w2c({ x: geo.max_x, y: geo.min_y });
    ctx.strokeStyle = C.border;
    ctx.lineWidth = 2;
    ctx.strokeRect(gf0.x, gf0.y, gf1.x - gf0.x, gf1.y - gf0.y);

    /* ── heatmap ────────────────────────────────────────────── */
    if (showHeatmap) {
      const g = 12;
      const bump = (d: number, r: number, w: number) => {
        const x = (r - d) / Math.max(w, 1e-6);
        return x <= 0 ? 0 : clamp(x, 0, 1);
      };
      for (let py = 0; py < H; py += g) {
        for (let px = 0; px < W; px += g) {
          const wp = c2w({ x: px + g / 2, y: py + g / 2 });
          let risk = 0;
          if (human && typeof human.x === "number")
            risk += 1.2 * bump(dist(wp, { x: +human.x, y: +human.y }), 2.5, 1.2);
          for (const ob of obstacles) {
            const d = dist(wp, { x: +ob.x, y: +ob.y }) - +(ob.r ?? ob.radius ?? 0.4);
            risk += 0.6 * bump(d, 1.1, 0.9);
          }
          const dEdge = Math.min(
            Math.abs(wp.x - geo.min_x),
            Math.abs(geo.max_x - wp.x),
            Math.abs(wp.y - geo.min_y),
            Math.abs(geo.max_y - wp.y),
          );
          risk += 0.35 * bump(dEdge, 0.6, 0.6);
          risk = clamp(risk, 0, 1);
          if (risk < 0.05) continue;
          ctx.fillStyle = `rgba(239,68,68,${0.04 + 0.3 * risk})`;
          ctx.fillRect(px, py, g, g);
        }
      }

      /* ── governance risk cells overlay (#21) ──────────────── */
      if (riskCells && riskCells.length > 0) {
        const gridPx = 2.0 * baseScale * zoom; // 2m grid cells
        for (const cell of riskCells) {
          const p = w2c({ x: cell.x, y: cell.y + 2.0 }); // top-left of cell
          const p2 = w2c({ x: cell.x + 2.0, y: cell.y }); // bottom-right
          const w = p2.x - p.x;
          const h = p2.y - p.y;
          const alpha = 0.08 + cell.risk * 0.35;
          const r = cell.risk > 0.7 ? 239 : cell.risk > 0.4 ? 245 : 59;
          const g2 = cell.risk > 0.7 ? 68 : cell.risk > 0.4 ? 158 : 130;
          const b = cell.risk > 0.7 ? 68 : cell.risk > 0.4 ? 11 : 246;
          ctx.fillStyle = `rgba(${r},${g2},${b},${alpha})`;
          ctx.fillRect(p.x, p.y, w, h);
          // Border
          if (cell.risk > 0.3) {
            ctx.strokeStyle = `rgba(${r},${g2},${b},${alpha * 1.5})`;
            ctx.lineWidth = 0.5;
            ctx.strokeRect(p.x, p.y, w, h);
          }
        }
      }
    }

    /* ── trail ──────────────────────────────────────────────── */
    if (showTrail) {
      const tr = trailPoints ?? trailRef.current;
      if (tr.length >= 2) {
        for (let i = 1; i < tr.length; i++) {
          const a = 0.08 + (i / tr.length) * 0.4;
          const p0 = w2c(tr[i - 1]);
          const p1 = w2c(tr[i]);
          ctx.strokeStyle = `rgba(6,182,212,${a})`;
          ctx.lineWidth = 1.5 + (i / tr.length) * 1.5;
          ctx.beginPath();
          ctx.moveTo(p0.x, p0.y);
          ctx.lineTo(p1.x, p1.y);
          ctx.stroke();
        }
        for (let i = 0; i < tr.length; i += 8) {
          const p = w2c(tr[i]);
          ctx.fillStyle = `rgba(6,182,212,${0.15 + (i / tr.length) * 0.5})`;
          ctx.beginPath();
          ctx.arc(p.x, p.y, 2, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }

    /* ── executed path overlay (#3) ────────────────────────── */
    if (executedPath && executedPath.length >= 2) {
      /* Thick translucent underline */
      ctx.strokeStyle = "rgba(16,185,129,0.15)";
      ctx.lineWidth = 7;
      ctx.beginPath();
      const ef = w2c(executedPath[0]);
      ctx.moveTo(ef.x, ef.y);
      for (let i = 1; i < executedPath.length; i++) {
        const pt = w2c(executedPath[i]);
        ctx.lineTo(pt.x, pt.y);
      }
      ctx.stroke();

      /* Solid green line */
      ctx.strokeStyle = "#10b981";
      ctx.lineWidth = 2.5;
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.moveTo(ef.x, ef.y);
      for (let i = 1; i < executedPath.length; i++) {
        const pt = w2c(executedPath[i]);
        ctx.lineTo(pt.x, pt.y);
      }
      ctx.stroke();

      /* Direction dots every 5 points */
      for (let i = 0; i < executedPath.length; i += 5) {
        const pt = w2c(executedPath[i]);
        ctx.fillStyle = `rgba(16,185,129,${0.3 + (i / executedPath.length) * 0.7})`;
        ctx.beginPath();
        ctx.arc(pt.x, pt.y, 2.5, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    /* ── destination bay highlight (#25) ─────────────────── */
    if (destinationBayId) {
      const destBay = bays.find((b: any) => b.id === destinationBayId);
      if (destBay && typeof destBay.x === "number") {
        const dp = w2c({ x: +destBay.x, y: +destBay.y });
        const isDock = destBay.type === "dock";
        const bw = isDock ? 4 * baseScale * zoom : 1.5 * baseScale * zoom;
        const bh = isDock ? 1.2 * baseScale * zoom : 3 * baseScale * zoom;

        /* Pulsing highlight ring */
        const highlightR = Math.max(bw, bh) * 0.8;
        ctx.save();
        ctx.strokeStyle = `rgba(16,185,129,${0.4 + pulse * 0.5})`;
        ctx.lineWidth = 3;
        ctx.shadowColor = "rgba(16,185,129,0.4)";
        ctx.shadowBlur = 12;
        ctx.beginPath();
        ctx.arc(dp.x, dp.y, highlightR, 0, Math.PI * 2);
        ctx.stroke();

        /* Outer expanding pulse */
        ctx.strokeStyle = `rgba(16,185,129,${0.15 * (1 - pulse)})`;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(dp.x, dp.y, highlightR + pulse * 10, 0, Math.PI * 2);
        ctx.stroke();
        ctx.restore();

        /* Destination label */
        ctx.fillStyle = "#10b981";
        ctx.font = `bold ${Math.max(9, 11 * zoom)}px system-ui`;
        ctx.textAlign = "center";
        ctx.textBaseline = isDock ? "bottom" : "top";
        const labelY = isDock ? dp.y - bh / 2 - highlightR - 4 : dp.y + bh / 2 + highlightR + 4;
        ctx.strokeStyle = "rgba(0,0,0,0.6)";
        ctx.lineWidth = 3;
        ctx.strokeText(`DEST: ${destinationBayId}`, dp.x, labelY);
        ctx.fillText(`DEST: ${destinationBayId}`, dp.x, labelY);
        ctx.textAlign = "start";
        ctx.textBaseline = "alphabetic";
      }
    }

    /* ── obstacles (typed: pallet, handcart, tote_stack) ───── */
    const obstTypeColors: Record<string, { fill: string; border: string; label: string }> = {
      pallet:     { fill: "#b45309", border: "#92400e", label: "PALLET" },
      handcart:   { fill: "#6366f1", border: "#4338ca", label: "HANDCART" },
      tote_stack: { fill: "#0891b2", border: "#0e7490", label: "TOTES" },
      dropped_pallet: { fill: "#b45309", border: "#f59e0b", label: "DROPPED PALLET" },
      spill:      { fill: "#2563eb", border: "#60a5fa", label: "SPILL" },
      forklift:   { fill: "#eab308", border: "#a16207", label: "FORKLIFT" },
    };
    for (const ob of obstacles) {
      const p = w2c({ x: +ob.x, y: +ob.y });
      const r = Math.max(5, +(ob.r ?? ob.radius ?? 0.5) * baseScale * zoom);
      const ot = obstTypeColors[ob.type] ?? { fill: C.obstacle, border: C.obsBorder, label: "OBSTACLE" };

      /* glow */
      const grad = ctx.createRadialGradient(p.x, p.y, r * 0.3, p.x, p.y, r * 2.5);
      grad.addColorStop(0, `${ot.fill}33`);
      grad.addColorStop(1, `${ot.fill}00`);
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(p.x, p.y, r * 2.5, 0, Math.PI * 2);
      ctx.fill();

      if (ob.type === "spill") {
        /* puddle */
        ctx.fillStyle = `${ot.fill}cc`;
        ctx.beginPath();
        ctx.ellipse(p.x, p.y, r * 1.3, r, 0.4, 0, Math.PI * 2);
        ctx.ellipse(p.x + r * 0.6, p.y - r * 0.4, r * 0.7, r * 0.55, 0, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "rgba(255,255,255,0.8)";
        ctx.font = `bold ${Math.max(7, 8 * zoom)}px system-ui`;
        ctx.textAlign = "center";
        ctx.textBaseline = "bottom";
        ctx.fillText(ot.label, p.x, p.y - r * 1.4);
        continue;
      }
      if (ob.type === "forklift") {
        /* vehicle body + forks, rotated to its heading (world y is flipped on screen) */
        const h = -(+(ob.heading ?? 0));
        ctx.save();
        ctx.translate(p.x, p.y);
        ctx.rotate(h);
        ctx.fillStyle = ot.fill;
        ctx.strokeStyle = ot.border;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.roundRect(-r, -r * 0.6, r * 2, r * 1.2, 3);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = "#9ca3af";
        ctx.fillRect(r, -r * 0.45, r * 0.7, r * 0.2);
        ctx.fillRect(r, r * 0.25, r * 0.7, r * 0.2);
        ctx.restore();
        ctx.fillStyle = "rgba(255,255,255,0.8)";
        ctx.font = `bold ${Math.max(7, 8 * zoom)}px system-ui`;
        ctx.textAlign = "center";
        ctx.textBaseline = "bottom";
        ctx.fillText(ot.label, p.x, p.y - r - 3);
        continue;
      }

      /* box */
      const bs = r * 1.4;
      ctx.fillStyle = ot.fill;
      ctx.strokeStyle = ot.border;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.roundRect(p.x - bs, p.y - bs, bs * 2, bs * 2, 3);
      ctx.fill();
      ctx.stroke();

      /* cross hatching */
      ctx.strokeStyle = "rgba(255,255,255,0.25)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(p.x - bs + 2, p.y - bs + 2);
      ctx.lineTo(p.x + bs - 2, p.y + bs - 2);
      ctx.moveTo(p.x + bs - 2, p.y - bs + 2);
      ctx.lineTo(p.x - bs + 2, p.y + bs - 2);
      ctx.stroke();

      ctx.fillStyle = "rgba(255,255,255,0.7)";
      ctx.font = `bold ${Math.max(7, 8 * zoom)}px system-ui`;
      ctx.textAlign = "center";
      ctx.textBaseline = "bottom";
      if (zoom >= 1.6 || ob.type === "dropped_pallet") ctx.fillText(ot.label, p.x, p.y - bs - 3); // parked clutter: label only when zoomed in
    }

    /* ── hazard exclusion zones (site intelligence) ─────────── */
    for (const z of (telemetry?.site_constraints ?? []) as any[]) {
      if (typeof z.x !== "number") continue;
      const p = w2c({ x: z.x, y: z.y });
      const r = z.radius * baseScale * zoom, sr = z.slow_radius * baseScale * zoom;
      const noEntry = z.radius > 0.1; // vision caution zones are slow-only
      if (noEntry) {
        ctx.fillStyle = "rgba(239,68,68,0.14)";
        ctx.strokeStyle = `rgba(239,68,68,${0.6 + pulse * 0.3})`;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
      }
      ctx.strokeStyle = noEntry ? "rgba(245,158,11,0.5)" : `rgba(245,158,11,${0.55 + pulse * 0.35})`;
      ctx.lineWidth = 1;
      ctx.setLineDash([5, 4]);
      ctx.beginPath();
      ctx.arc(p.x, p.y, sr, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = noEntry ? "#fecaca" : "#fde68a";
      ctx.font = `bold ${Math.max(8, 9 * zoom)}px system-ui`;
      ctx.textAlign = "center";
      ctx.textBaseline = "bottom";
      ctx.fillText(noEntry ? `NO ENTRY ${Number(z.radius).toFixed(1)}m`
                           : `VISION · SLOW ${Number(z.max_speed).toFixed(1)} m/s`, p.x, p.y - (noEntry ? r : sr) - 2);
    }

    /* ── human ──────────────────────────────────────────────── */
    if (human && typeof human.x === "number") {
      const p = w2c({ x: +human.x, y: +human.y });

      /* danger 1m */
      const dr = 1.0 * baseScale * zoom;
      ctx.fillStyle = C.humanDanger;
      ctx.strokeStyle = `rgba(239,68,68,${0.3 + pulse * 0.3})`;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(p.x, p.y, dr, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      /* caution 3m */
      const cr = 3.0 * baseScale * zoom;
      ctx.fillStyle = C.humanCaution;
      ctx.strokeStyle = "rgba(245,158,11,0.2)";
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.arc(p.x, p.y, cr, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      ctx.setLineDash([]);

      /* ring labels */
      ctx.fillStyle = "rgba(239,68,68,0.6)";
      ctx.font = `${Math.max(7, 8 * zoom)}px system-ui`;
      ctx.textAlign = "center";
      ctx.fillText("STOP 1m", p.x, p.y - dr - 2);
      ctx.fillStyle = "rgba(245,158,11,0.5)";
      ctx.fillText("SLOW 3m", p.x, p.y - cr - 2);

      /* body */
      ctx.fillStyle = C.human;
      ctx.strokeStyle = "#92400e";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(p.x, p.y, 7 * zoom, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      /* head */
      ctx.beginPath();
      ctx.arc(p.x, p.y - 3 * zoom, 2.5 * zoom, 0, Math.PI * 2);
      ctx.strokeStyle = "#92400e";
      ctx.lineWidth = 1.5;
      ctx.stroke();
      /* body line */
      ctx.beginPath();
      ctx.moveTo(p.x, p.y - 0.5 * zoom);
      ctx.lineTo(p.x, p.y + 3 * zoom);
      ctx.stroke();

      ctx.fillStyle = C.human;
      ctx.font = `bold ${Math.max(8, 9 * zoom)}px system-ui`;
      ctx.textAlign = "center";
      ctx.fillText("PERSON", p.x, p.y + 12 * zoom);

      /* distance from robot */
      if (telemetry) {
        const d = dist(
          { x: +(telemetry.x ?? 0), y: +(telemetry.y ?? 0) },
          { x: +human.x, y: +human.y },
        );
        ctx.fillStyle = d < 1 ? "#ef4444" : d < 3 ? "#f59e0b" : "#22c55e";
        ctx.font = `bold ${Math.max(9, 10 * zoom)}px monospace`;
        ctx.fillText(`${d.toFixed(1)}m`, p.x, p.y + 22 * zoom);
      }
    }

    /* ── walking humans (secondary workers) ──────────────────── */
    for (const wh of walkingHumans) {
      if (typeof wh.x !== "number") continue;
      /* the primary human is drawn above with its safety rings; don't draw it twice */
      if (human && Math.hypot(+wh.x - +human.x, +wh.y - +human.y) < 0.3) continue;
      const p = w2c({ x: +wh.x, y: +wh.y });
      const nearRobot = telemetry && typeof telemetry.x === "number" && Math.hypot(+wh.x - +telemetry.x, +wh.y - +telemetry.y) < 1.5;

      /* soft proximity glow */
      const gr = 1.5 * baseScale * zoom;
      ctx.fillStyle = "rgba(245,158,11,0.06)";
      ctx.beginPath();
      ctx.arc(p.x, p.y, gr, 0, Math.PI * 2);
      ctx.fill();

      /* walking animation – small "legs" that alternate */
      const walkPhase = Math.sin(tick * 0.3 + (wh.x * 7 + wh.y * 13));
      const legSpread = wh.speed > 0 ? 3 * zoom * walkPhase : 0;

      /* body circle */
      ctx.fillStyle = "#fbbf24";
      ctx.strokeStyle = "#92400e";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(p.x, p.y, 5 * zoom, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      /* head */
      ctx.beginPath();
      ctx.arc(p.x, p.y - 2.5 * zoom, 2 * zoom, 0, Math.PI * 2);
      ctx.strokeStyle = "#92400e";
      ctx.lineWidth = 1;
      ctx.stroke();

      /* legs (animated) */
      ctx.strokeStyle = "#92400e";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(p.x - legSpread, p.y + 3 * zoom);
      ctx.lineTo(p.x, p.y + 1 * zoom);
      ctx.lineTo(p.x + legSpread, p.y + 3 * zoom);
      ctx.stroke();

      /* direction indicator when moving */
      if (wh.speed > 0 && typeof wh.theta === "number") {
        const dLen = 8 * zoom;
        ctx.strokeStyle = "rgba(251,191,36,0.5)";
        ctx.lineWidth = 1;
        ctx.setLineDash([2, 2]);
        ctx.beginPath();
        ctx.moveTo(p.x, p.y);
        ctx.lineTo(p.x + Math.cos(wh.theta) * dLen, p.y - Math.sin(wh.theta) * dLen);
        ctx.stroke();
        ctx.setLineDash([]);
      }

      /* name label */
      const label = wh.label ?? wh.name ?? "Worker";
      if (!nearRobot) {
      ctx.fillStyle = "rgba(251,191,36,0.8)";
      ctx.font = `${Math.max(7, 8 * zoom)}px system-ui`;
      ctx.textAlign = "center";
      ctx.fillText(label, p.x, p.y + 9 * zoom);
      }

      /* distance from robot */
      if (telemetry && typeof telemetry.x === "number") {
        const d = dist(
          { x: +(telemetry.x ?? 0), y: +(telemetry.y ?? 0) },
          { x: +wh.x, y: +wh.y },
        );
        if (d < 5) {
          ctx.fillStyle = d < 1 ? "#ef4444" : d < 3 ? "#f59e0b" : "#22c55e";
          ctx.font = `bold ${Math.max(7, 8 * zoom)}px monospace`;
          ctx.fillText(`${d.toFixed(1)}m`, p.x, p.y + 17 * zoom);
        }
      }
    }

    /* ── path preview ───────────────────────────────────────── */
    if (pathPoints && pathPoints.length >= 2) {
      ctx.strokeStyle = "rgba(59,130,246,0.15)";
      ctx.lineWidth = 6;
      ctx.beginPath();
      const f = w2c(pathPoints[0]);
      ctx.moveTo(f.x, f.y);
      for (let i = 1; i < pathPoints.length; i++) {
        const pt = w2c(pathPoints[i]);
        ctx.lineTo(pt.x, pt.y);
      }
      ctx.stroke();

      ctx.strokeStyle = C.path;
      ctx.lineWidth = 2;
      ctx.setLineDash([6, 3]);
      ctx.beginPath();
      ctx.moveTo(f.x, f.y);
      for (let i = 1; i < pathPoints.length; i++) {
        const pt = w2c(pathPoints[i]);
        ctx.lineTo(pt.x, pt.y);
      }
      ctx.stroke();
      ctx.setLineDash([]);
    }

    /* ── LLM plan waypoints ─────────────────────────────────── */
    if (planWaypoints && planWaypoints.length > 0) {
      ctx.strokeStyle = C.plan;
      ctx.lineWidth = 2;
      ctx.setLineDash([6, 4]);
      ctx.beginPath();
      const sp = telemetry
        ? w2c({ x: +(telemetry.x ?? 0), y: +(telemetry.y ?? 0) })
        : w2c(planWaypoints[0]);
      ctx.moveTo(sp.x, sp.y);
      for (const wp of planWaypoints) {
        const p = w2c(wp);
        ctx.lineTo(p.x, p.y);
      }
      ctx.stroke();
      ctx.setLineDash([]);

      for (let i = 0; i < planWaypoints.length; i++) {
        const wp = planWaypoints[i];
        const p = w2c(wp);
        ctx.strokeStyle = C.plan;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(p.x, p.y, 12, 0, Math.PI * 2);
        ctx.stroke();
        ctx.fillStyle = C.plan;
        ctx.beginPath();
        ctx.arc(p.x, p.y, 8, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "#fff";
        ctx.font = `bold ${Math.max(9, 10 * zoom)}px system-ui`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(String(i + 1), p.x, p.y);
        if (wp.max_speed != null) {
          ctx.fillStyle = C.textDim;
          ctx.font = `${Math.max(7, 8 * zoom)}px monospace`;
          ctx.textBaseline = "top";
          ctx.fillText(`${wp.max_speed.toFixed(1)}m/s`, p.x, p.y + 14);
        }
        // hovered waypoint highlight (if provided)
        if (typeof hoveredWaypointIdx === "number" && hoveredWaypointIdx === i) {
          ctx.save();
          ctx.strokeStyle = "rgba(168,85,247,0.95)";
          ctx.lineWidth = 3;
          ctx.shadowColor = "rgba(168,85,247,0.45)";
          ctx.shadowBlur = 12;
          ctx.beginPath();
          ctx.arc(p.x, p.y, 18, 0, Math.PI * 2);
          ctx.stroke();
          ctx.restore();
        }
      }
      ctx.textAlign = "start";
      ctx.textBaseline = "alphabetic";
    }

    /* ── idle robots ──────────────────────────────────────────── */
    for (const ir of idleRobots) {
      if (typeof ir.x !== "number") continue;
      const p = w2c({ x: +ir.x, y: +ir.y });

      /* dim glow */
      const rg = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, 14);
      rg.addColorStop(0, "rgba(100,116,139,0.15)");
      rg.addColorStop(1, "rgba(100,116,139,0)");
      ctx.fillStyle = rg;
      ctx.beginPath();
      ctx.arc(p.x, p.y, 14, 0, Math.PI * 2);
      ctx.fill();

      /* body (gray) */
      const rb = 8;
      ctx.fillStyle = "#475569";
      ctx.strokeStyle = "#334155";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.roundRect(p.x - rb, p.y - rb, rb * 2, rb * 2, 3);
      ctx.fill();
      ctx.stroke();
      /* inner */
      ctx.fillStyle = "#334155";
      ctx.beginPath();
      ctx.roundRect(p.x - 3, p.y - 3, 6, 6, 1.5);
      ctx.fill();
      /* center dot */
      ctx.fillStyle = "#94a3b8";
      ctx.beginPath();
      ctx.arc(p.x, p.y, 2, 0, Math.PI * 2);
      ctx.fill();

      /* heading arrow (dim) */
      const irt = +(ir.theta ?? 0);
      const al = 14;
      const ax = p.x + Math.cos(irt) * al;
      const ay = p.y - Math.sin(irt) * al;
      ctx.strokeStyle = "rgba(148,163,184,0.4)";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(p.x, p.y);
      ctx.lineTo(ax, ay);
      ctx.stroke();

      /* label */
      const lbl = ir.label ?? "Robot (Idle)";
      ctx.fillStyle = "#94a3b8";
      ctx.font = `bold ${Math.max(7, 8 * zoom)}px system-ui`;
      ctx.textAlign = "center";
      ctx.textBaseline = "bottom";
      ctx.fillText(lbl, p.x, p.y - rb - 3);

      /* IDLE badge */
      const bw = 30;
      ctx.fillStyle = "#334155";
      ctx.beginPath();
      ctx.roundRect(p.x - bw / 2, p.y + rb + 2, bw, 12, 2);
      ctx.fill();
      ctx.fillStyle = "#94a3b8";
      ctx.font = `bold ${Math.max(7, 8 * zoom)}px system-ui`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText("IDLE", p.x, p.y + rb + 8);
    }
    ctx.textAlign = "start";
    ctx.textBaseline = "alphabetic";

    /* ── robot ──────────────────────────────────────────────── */
    if (telemetry) {
      const rx = +(telemetry.x ?? 0);
      const ry = +(telemetry.y ?? 0);
      const rt = +(telemetry.theta ?? 0);
      const spd = +(telemetry.speed ?? 0);
      const p = w2c({ x: rx, y: ry });
      const st = String(safetyState).toUpperCase();

      /* safety ring */
      const sr = 22;
      if (st === "STOP") {
        ctx.strokeStyle = `rgba(239,68,68,${0.6 + pulse * 0.4})`;
        ctx.fillStyle = `rgba(239,68,68,${0.05 + pulse * 0.08})`;
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.arc(p.x, p.y, sr, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
      } else if (st === "SLOW") {
        ctx.strokeStyle = `rgba(245,158,11,${0.5 + pulse * 0.3})`;
        ctx.fillStyle = "rgba(245,158,11,0.06)";
        ctx.lineWidth = 2.5;
        ctx.beginPath();
        ctx.arc(p.x, p.y, sr, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
      } else if (st === "REPLAN") {
        ctx.strokeStyle = `rgba(99,102,241,${0.5 + pulse * 0.3})`;
        ctx.fillStyle = "rgba(99,102,241,0.06)";
        ctx.lineWidth = 2.5;
        ctx.setLineDash([5, 3]);
        ctx.beginPath();
        ctx.arc(p.x, p.y, sr, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        ctx.setLineDash([]);
      }

      /* glow */
      const rg = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, 20);
      rg.addColorStop(0, C.robotGlow);
      rg.addColorStop(1, "rgba(6,182,212,0)");
      ctx.fillStyle = rg;
      ctx.beginPath();
      ctx.arc(p.x, p.y, 20, 0, Math.PI * 2);
      ctx.fill();

      /* body */
      const rb = 10;
      ctx.fillStyle = C.robot;
      ctx.strokeStyle = C.robotDark;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.roundRect(p.x - rb, p.y - rb, rb * 2, rb * 2, 4);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = C.robotDark;
      ctx.beginPath();
      ctx.roundRect(p.x - 4, p.y - 4, 8, 8, 2);
      ctx.fill();
      ctx.fillStyle = "#67e8f9";
      ctx.beginPath();
      ctx.arc(p.x, p.y, 2.5, 0, Math.PI * 2);
      ctx.fill();

      /* heading arrow */
      const al = 20;
      const ax = p.x + Math.cos(rt) * al;
      const ay = p.y - Math.sin(rt) * al;
      ctx.strokeStyle = "#22d3ee";
      ctx.lineWidth = 2.5;
      ctx.beginPath();
      ctx.moveTo(p.x, p.y);
      ctx.lineTo(ax, ay);
      ctx.stroke();
      const hl = 7;
      const ang = Math.atan2(-(ay - p.y), ax - p.x);
      ctx.fillStyle = "#22d3ee";
      ctx.beginPath();
      ctx.moveTo(ax, ay);
      ctx.lineTo(ax - hl * Math.cos(ang - 0.45), ay + hl * Math.sin(ang - 0.45));
      ctx.lineTo(ax - hl * Math.cos(ang + 0.45), ay + hl * Math.sin(ang + 0.45));
      ctx.closePath();
      ctx.fill();

      /* labels */
      ctx.fillStyle = "#22d3ee";
      ctx.font = `bold ${Math.max(9, 10 * zoom)}px system-ui`;
      ctx.textAlign = "center";
      ctx.textBaseline = "bottom";
      ctx.fillText("ROBOT", p.x, p.y - rb - 4);
      ctx.fillStyle = C.textDim;
      ctx.font = `${Math.max(8, 9 * zoom)}px monospace`;
      ctx.textBaseline = "top";
      ctx.fillText(`${spd.toFixed(2)} m/s`, p.x, p.y + rb + 4);

      /* safety badge */
      if (st !== "OK" && st !== "SAFE") {
        const bc: Record<string, { bg: string; fg: string }> = {
          STOP: { bg: "#dc2626", fg: "#fff" },
          SLOW: { bg: "#d97706", fg: "#fff" },
          REPLAN: { bg: "#4f46e5", fg: "#fff" },
        };
        const c = bc[st] ?? { bg: "#475569", fg: "#fff" };
        const bw = st.length * 7 + 12;
        ctx.fillStyle = c.bg;
        ctx.beginPath();
        ctx.roundRect(p.x - bw / 2, p.y - rb - 22, bw, 14, 3);
        ctx.fill();
        ctx.fillStyle = c.fg;
        ctx.font = `bold ${Math.max(8, 9 * zoom)}px system-ui`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(st, p.x, p.y - rb - 15);
      }
      ctx.textAlign = "start";
      ctx.textBaseline = "alphabetic";

      /* target cross-hair — priority: mission goal (bay) > plan last waypoint > sim target */
      const tgt = (missionGoal && typeof missionGoal.x === "number" ? missionGoal : null)
        || (planWaypoints && planWaypoints.length > 0 ? planWaypoints[planWaypoints.length - 1] : null)
        || telemetry.target;
      const tgtLabel = (missionGoal && typeof missionGoal.x === "number") ? "GOAL"
        : (planWaypoints && planWaypoints.length > 0) ? "DEST" : "TARGET";
      if (tgt && typeof tgt.x === "number") {
        const tp = w2c({ x: +tgt.x, y: +tgt.y });
        const cr = 10;

        /* pulsing outer ring */
        ctx.strokeStyle = `rgba(16,185,129,${0.4 + pulse * 0.3})`;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.arc(tp.x, tp.y, cr + 4 + pulse * 2, 0, Math.PI * 2);
        ctx.stroke();

        ctx.strokeStyle = C.target;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(tp.x, tp.y, cr, 0, Math.PI * 2);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(tp.x - cr - 4, tp.y);
        ctx.lineTo(tp.x + cr + 4, tp.y);
        ctx.moveTo(tp.x, tp.y - cr - 4);
        ctx.lineTo(tp.x, tp.y + cr + 4);
        ctx.stroke();
        ctx.fillStyle = C.target;
        ctx.beginPath();
        ctx.arc(tp.x, tp.y, 3, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = C.target;
        ctx.font = `bold ${Math.max(8, 9 * zoom)}px system-ui`;
        ctx.textAlign = "center";
        ctx.fillText(tgtLabel, tp.x, tp.y - cr - 5);
        ctx.textAlign = "start";
      }
    }

    /* ── Mission Goal target (fallback when no telemetry) ── */
    if (!telemetry && missionGoal && typeof missionGoal.x === "number") {
      const tp = w2c({ x: +missionGoal.x, y: +missionGoal.y });
      const cr = 10;
      ctx.strokeStyle = `rgba(16,185,129,${0.4 + pulse * 0.3})`;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(tp.x, tp.y, cr + 4 + pulse * 2, 0, Math.PI * 2);
      ctx.stroke();
      ctx.strokeStyle = C.target;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(tp.x, tp.y, cr, 0, Math.PI * 2);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(tp.x - cr - 4, tp.y);
      ctx.lineTo(tp.x + cr + 4, tp.y);
      ctx.moveTo(tp.x, tp.y - cr - 4);
      ctx.lineTo(tp.x, tp.y + cr + 4);
      ctx.stroke();
      ctx.fillStyle = C.target;
      ctx.beginPath();
      ctx.arc(tp.x, tp.y, 3, 0, Math.PI * 2);
      ctx.fill();
      ctx.font = `bold ${Math.max(8, 9 * zoom)}px system-ui`;
      ctx.textAlign = "center";
      ctx.fillText("GOAL", tp.x, tp.y - cr - 5);
      ctx.textAlign = "start";
    }

    /* ── HUD (top-left) ─────────────────────────────────────── */
    ctx.fillStyle = "rgba(15,23,42,0.75)";
    ctx.beginPath();
    ctx.roundRect(6, 6, 96, 40, 4);
    ctx.fill();
    ctx.fillStyle = C.textDim;
    ctx.font = "9px monospace";
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillText("WAREHOUSE SIM", 12, 12);
    ctx.fillText(`${(geo.max_x - geo.min_x).toFixed(0)}×${(geo.max_y - geo.min_y).toFixed(0)}m`, 12, 24);
    ctx.fillText(`Zoom: ${zoom.toFixed(1)}×`, 12, 36);

    /* ── Legend (bottom-right) ──────────────────────────────── */
    const legend = [
      { color: C.robot, label: "Robot" },
      { color: "#475569", label: "Idle Robot" },
      { color: C.human, label: "Human" },
      { color: "#fbbf24", label: "Workers" },
      { color: C.obstacle, label: "Obstacle" },
      { color: "rgba(245,158,11,0.6)", label: "Bay/Dock" },
      { color: C.path, label: "Path" },
      { color: C.plan, label: "LLM Plan" },
      { color: "#10b981", label: "Executed" },
      { color: C.target, label: "Target" },
    ];
    const lx = W - 80,
      ly = H - 10 - legend.length * 14;
    ctx.fillStyle = "rgba(15,23,42,0.75)";
    ctx.beginPath();
    ctx.roundRect(lx - 6, ly - 6, 84, legend.length * 14 + 10, 4);
    ctx.fill();
    legend.forEach((it, i) => {
      const y = ly + i * 14;
      ctx.fillStyle = it.color;
      ctx.beginPath();
      ctx.roundRect(lx, y, 8, 8, 2);
      ctx.fill();
      ctx.fillStyle = C.text;
      ctx.font = "9px system-ui";
      ctx.textAlign = "left";
      ctx.textBaseline = "top";
      ctx.fillText(it.label, lx + 12, y);
    });
  }, [world, telemetry, pathPoints, planWaypoints, baseScale, zoom, pan, showHeatmap, showTrail, safetyState, tick, pad, zones, obstacles, human, walkingHumans, idleRobots, bays, geo, W, H, riskCells, executedPath, destinationBayId, hoveredWaypointIdx, trailPoints]);

  /* ── Minimap (when zoomed > 1.5x) ─────────────────────────── */
  useEffect(() => {
    if (zoom <= 1.5) return;
    const mc = minimapRef.current;
    if (!mc) return;
    const mctx = mc.getContext("2d");
    if (!mctx) return;
    const MW = 140, MH = 90;
    mc.width = MW;
    mc.height = MH;

    const mScale = Math.min((MW - 8) / ((geo.max_x - geo.min_x) || 1), (MH - 8) / ((geo.max_y - geo.min_y) || 1));
    const mPad = { x: (MW - (geo.max_x - geo.min_x) * mScale) / 2, y: (MH - (geo.max_y - geo.min_y) * mScale) / 2 };

    function mw2c(p: Pt) {
      return { x: mPad.x + (p.x - geo.min_x) * mScale, y: MH - mPad.y - (p.y - geo.min_y) * mScale };
    }

    /* bg */
    mctx.fillStyle = "rgba(15,23,42,0.85)";
    mctx.fillRect(0, 0, MW, MH);

    /* geofence outline */
    const g0 = mw2c({ x: geo.min_x, y: geo.max_y });
    const g1 = mw2c({ x: geo.max_x, y: geo.min_y });
    mctx.strokeStyle = "#475569";
    mctx.lineWidth = 1;
    mctx.strokeRect(g0.x, g0.y, g1.x - g0.x, g1.y - g0.y);

    /* obstacles */
    for (const ob of obstacles) {
      const p = mw2c({ x: +ob.x, y: +ob.y });
      mctx.fillStyle = "#ef4444";
      mctx.fillRect(p.x - 2, p.y - 2, 4, 4);
    }

    /* human */
    if (human && typeof human.x === "number") {
      const p = mw2c({ x: +human.x, y: +human.y });
      mctx.fillStyle = "#f59e0b";
      mctx.beginPath();
      mctx.arc(p.x, p.y, 3, 0, Math.PI * 2);
      mctx.fill();
    }

    /* robot */
    if (telemetry) {
      const p = mw2c({ x: +(telemetry.x ?? 0), y: +(telemetry.y ?? 0) });
      mctx.fillStyle = "#06b6d4";
      mctx.beginPath();
      mctx.arc(p.x, p.y, 3, 0, Math.PI * 2);
      mctx.fill();
    }

    /* viewport rectangle */
    const viewTL = { x: -pan.x / zoom, y: -pan.y / zoom };
    const viewBR = { x: (W - pan.x) / zoom, y: (H - pan.y) / zoom };
    /* convert from canvas-space back to world-space */
    function cs2w(sx: number, sy: number) {
      return { x: (sx - pad.x) / baseScale + geo.min_x, y: (H - pad.y - sy) / baseScale + geo.min_y };
    }
    const wTL = cs2w(viewTL.x, viewTL.y);
    const wBR = cs2w(viewBR.x, viewBR.y);
    const vp0 = mw2c({ x: wTL.x, y: wTL.y });
    const vp1 = mw2c({ x: wBR.x, y: wBR.y });
    mctx.strokeStyle = "rgba(6,182,212,0.7)";
    mctx.lineWidth = 1.5;
    mctx.strokeRect(Math.min(vp0.x, vp1.x), Math.min(vp0.y, vp1.y), Math.abs(vp1.x - vp0.x), Math.abs(vp1.y - vp0.y));
  }, [zoom, pan, telemetry, obstacles, human, geo, W, H, pad, baseScale]);

  return (
    <div
      ref={containerRef}
      className="relative w-full border border-slate-700"
      style={{ minHeight: 300, height: isFullscreen ? "100vh" : "100%", borderRadius: 12, overflow: "hidden", background: C.floor }}
    >
      <canvas
        ref={ref}
        width={W}
        height={H}
        style={{ width: "100%", height: "100%", touchAction: "none", display: "block" }}
      />
      {/* Fullscreen toggle */}
      <button
        onClick={toggleFullscreen}
        className="absolute top-2 right-2 bg-slate-800/80 hover:bg-slate-700 text-slate-300 rounded-md px-2 py-1 text-xs backdrop-blur-sm transition-colors"
        title={isFullscreen ? "Exit fullscreen" : "Fullscreen"}
      >
        {isFullscreen ? "⛶ Exit" : "⛶ Fullscreen"}
      </button>
      {/* Minimap overlay when zoomed */}
      {zoom > 1.5 && (
        <canvas
          ref={minimapRef}
          width={140}
          height={90}
          className="absolute bottom-2 left-2 border border-slate-600 rounded"
          style={{ background: "rgba(15,23,42,0.85)" }}
        />
      )}
    </div>
  );
}
