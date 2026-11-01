"""Robot-camera perception with an NVIDIA vision-language model, cross-checked.

The model (Nemotron 3.5 Super VL on Nebius Token Factory) reads the robot's camera
frame and reports people, the forklift, spills and pallets. Its output is never
trusted on its own:

- Every report is compared with the simulator's ground truth in the same view.
- A real hazard the model missed is recorded as a perception fault. The gate keeps
  using the sensors, so a vision miss cannot make the robot less careful.
- A sighting the sensors do not confirm becomes a short-lived slow zone. It goes
  through HAZARD_SLOW_09 like any other hazard zone, so vision can only add caution.

Positions are asked for in image coordinates (0-1000 grid), which the model reports
far more accurately than metres, and converted with the camera geometry.
"""
from __future__ import annotations

import base64
import logging
import math
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

import httpx

from app.config import settings

logger = logging.getLogger("app.perception")

# Camera geometry: must match sim/warehouse_sim/camera.py render()
FRAME_SIZE = 512
VIEW_M = 12.0
ROBOT_ROW = 0.72          # robot sits 72% of the way down the image, facing up
SELF_RADIUS_M = 0.5       # sightings this close to the robot's centre are the robot itself

KINDS = ("person", "forklift", "spill", "pallet")
# Ground-truth obstacle types mapped to what the camera shows
_TRUTH_KIND = {"spill": "spill", "forklift": "forklift", "dropped_pallet": "pallet", "pallet": "pallet"}
# Slow zone placed round an unconfirmed sighting: (slow radius m, max speed m/s)
CAUTION = {"person": (2.0, 0.3), "forklift": (2.5, 0.3), "spill": (1.5, 0.2), "pallet": (1.2, 0.3)}

PROMPT = """Top-down warehouse camera image, robot = blue triangle pointing up.
Find every PERSON (orange circle with a dark centre), FORKLIFT (yellow), SPILL (light-cyan blotchy patch) and
PALLET (brown square). Dark-brown long bars are racks: do not report them. Report only what is clearly visible.
For each object give the centre of the object in image coordinates on a 0-1000 grid (x from left, y from top).
JSON only: {"objects": [{"type": "person|forklift|spill|pallet", "x": 0, "y": 0}]}"""


def image_to_robot(px: float, py: float) -> Tuple[float, float]:
    """0-1000 image coordinates -> (ahead_m, right_m) relative to the robot."""
    scale = FRAME_SIZE / VIEW_M
    x, y = px / 1000.0 * FRAME_SIZE, py / 1000.0 * FRAME_SIZE
    return (FRAME_SIZE * ROBOT_ROW - y) / scale, (x - FRAME_SIZE / 2) / scale


def robot_to_world(tel: Dict[str, Any], ahead: float, right: float) -> Tuple[float, float]:
    th = float(tel.get("theta", 0.0))
    x0, y0 = float(tel.get("x", 0.0)), float(tel.get("y", 0.0))
    return x0 + ahead * math.cos(th) + right * math.sin(th), y0 + ahead * math.sin(th) - right * math.cos(th)


def world_to_robot(tel: Dict[str, Any], x: float, y: float) -> Tuple[float, float]:
    th = float(tel.get("theta", 0.0))
    dx, dy = x - float(tel.get("x", 0.0)), y - float(tel.get("y", 0.0))
    return dx * math.cos(th) + dy * math.sin(th), dx * math.sin(th) - dy * math.cos(th)


def _in_view(ahead: float, right: float) -> bool:
    half = VIEW_M / 2
    return abs(right) <= half and -VIEW_M * (1 - ROBOT_ROW) <= ahead <= VIEW_M * ROBOT_ROW


def ground_truth(tel: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Objects the camera should show, from the simulator's telemetry."""
    out: List[Dict[str, Any]] = []
    for p in tel.get("walking_humans") or []:
        a, r = world_to_robot(tel, float(p["x"]), float(p["y"]))
        if _in_view(a, r):
            out.append({"type": "person", "x": float(p["x"]), "y": float(p["y"]), "ahead_m": round(a, 2), "right_m": round(r, 2)})
    for o in tel.get("obstacles") or []:
        kind = _TRUTH_KIND.get(str(o.get("type")))
        if not kind:
            continue
        a, r = world_to_robot(tel, float(o["x"]), float(o["y"]))
        if _in_view(a, r):
            out.append({"type": kind, "x": float(o["x"]), "y": float(o["y"]), "ahead_m": round(a, 2), "right_m": round(r, 2)})
    return out


def compare(seen: List[Dict[str, Any]], truth: List[Dict[str, Any]], match_m: float) -> Dict[str, Any]:
    """Greedy nearest match by type. People close together may be seen as one, so an
    unmatched person within match_m of a matched one is not counted as missed."""
    pairs = sorted(
        ((math.dist((s["x"], s["y"]), (t["x"], t["y"])), i, j)
         for i, s in enumerate(seen) for j, t in enumerate(truth) if s["type"] == t["type"]),
        key=lambda p: p[0])
    used_s, used_t, matched = set(), set(), []
    for d, i, j in pairs:
        if d > match_m or i in used_s or j in used_t:
            continue
        used_s.add(i); used_t.add(j)
        matched.append({**truth[j], "error_m": round(d, 2)})
    missed = []
    for j, t in enumerate(truth):
        if j in used_t:
            continue
        merged = any(truth[k]["type"] == t["type"] and math.dist((truth[k]["x"], truth[k]["y"]), (t["x"], t["y"])) <= match_m
                     for k in used_t)
        if not merged:
            missed.append(t)
    unconfirmed = [s for i, s in enumerate(seen) if i not in used_s]
    if missed:
        verdict = "missed_hazard"
    elif unconfirmed:
        verdict = "unconfirmed_sighting"
    else:
        verdict = "agree"
    return {"matched": matched, "missed": missed, "unconfirmed": unconfirmed, "verdict": verdict}


def parse_objects(obj: Any, tel: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = obj.get("objects", []) if isinstance(obj, dict) else obj if isinstance(obj, list) else []
    seen = []
    for o in items:
        try:
            kind = str(o.get("type", "")).lower().strip()
            px, py = float(o["x"]), float(o["y"])
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        if kind not in KINDS or not (0 <= px <= 1000 and 0 <= py <= 1000):
            continue
        a, r = image_to_robot(px, py)
        if math.hypot(a, r) < SELF_RADIUS_M:
            continue  # the model sometimes labels the robot itself
        wx, wy = robot_to_world(tel, a, r)
        seen.append({"type": kind, "x": round(wx, 2), "y": round(wy, 2), "ahead_m": round(a, 2), "right_m": round(r, 2),
                     "image": {"x": px, "y": py}})
    return seen


class Perception:
    def __init__(self) -> None:
        self.recent: Deque[Dict[str, Any]] = deque(maxlen=50)
        self._caution: Dict[str, Dict[str, Any]] = {}      # id -> slow zone with expiry
        self._pending: Dict[str, List[Dict[str, Any]]] = {}  # run_id -> results to record
        self._last_check: Dict[str, float] = {}
        self._busy: set = set()
        self._seq = 0

    # ----------------------------------------------------------------- model
    async def _ask(self, png: bytes) -> Tuple[Optional[Any], Dict[str, Any]]:
        from app.services.gemini_planner import _extract_json
        from app.services.nemotron_planner import _get_client, usage_log
        body = {
            "model": settings.vision_model, "temperature": 0, "max_tokens": 1024,
            # Thinking off: with it on, the model spends its whole budget reasoning
            # about the image and returns no answer; off, it answers in about a second.
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}},
            ]}],
        }
        record: Dict[str, Any] = {"model": settings.vision_model, "tier": "vision", "ok": False}
        t0 = time.monotonic()
        try:
            r = await _get_client().post(
                f"{settings.nebius_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.nebius_api_key}"}, json=body,
                timeout=settings.vision_timeout_s)
            record.update(latency_ms=round((time.monotonic() - t0) * 1000), status=r.status_code)
            if r.status_code >= 400:
                logger.warning("Vision model HTTP %s: %s", r.status_code, r.text[:200])
                return None, record
            data = r.json()
            usage = data.get("usage") or {}
            record.update(prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"))
            text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            obj = _extract_json(text)
            record["ok"] = True
            return obj, record
        except Exception as e:
            record.setdefault("latency_ms", round((time.monotonic() - t0) * 1000))
            record["error"] = type(e).__name__
            logger.warning("Vision check failed: %s", e)
            return None, record
        finally:
            usage_log.record(**record)

    # ----------------------------------------------------------------- check
    async def check(self, sim, telemetry: Optional[Dict[str, Any]] = None, run_id: Optional[str] = None) -> Dict[str, Any]:
        """Read one camera frame, compare it with ground truth, update caution zones."""
        tel = telemetry if telemetry is not None else await sim.get_telemetry()
        png = await sim.get_frame(size=FRAME_SIZE)
        obj, call = await self._ask(png)
        truth = ground_truth(tel)
        self._seq += 1
        result: Dict[str, Any] = {
            "id": f"vis-{self._seq}", "ts": time.time(), "run_id": run_id, "model": settings.vision_model,
            "latency_ms": call.get("latency_ms"), "robot": {k: tel.get(k) for k in ("x", "y", "theta")},
            "truth": truth,
        }
        if obj is None:
            result.update(ok=False, verdict="no_answer", seen=[], matched=[], missed=truth, unconfirmed=[],
                          note="Vision model gave no usable answer; the gate relies on the sensors as always.")
        else:
            seen = parse_objects(obj, tel)
            result.update(ok=True, seen=seen, **compare(seen, truth, settings.vision_match_m))
            self._add_caution(result)
        result["caution_zones"] = [dict(z) for z in self.caution_zones()]
        self.recent.append(result)
        if run_id:
            self._pending.setdefault(run_id, []).append(result)
        return result

    def _add_caution(self, result: Dict[str, Any]) -> None:
        now = time.time()
        for s in result.get("unconfirmed", []):
            slow_r, vmax = CAUTION.get(s["type"], (1.5, 0.3))
            zid = f"vision-{result['id']}-{s['type']}-{len(self._caution)}"
            self._caution[zid] = {
                "id": zid, "x": s["x"], "y": s["y"], "radius": 0.0, "slow_radius": slow_r, "max_speed": vmax,
                "label": f"unconfirmed vision sighting ({s['type']})", "expires": now + settings.vision_caution_ttl_s,
            }

    def caution_zones(self) -> List[Dict[str, Any]]:
        now = time.time()
        for zid in [z for z, v in self._caution.items() if v["expires"] <= now]:
            del self._caution[zid]
        return [{k: v for k, v in z.items() if k != "expires"} for z in self._caution.values()]

    def apply(self, telemetry: Dict[str, Any]) -> Dict[str, Any]:
        """Add vision caution zones to what the gate sees (slow only, radius 0: no exclusion)."""
        zones = self.caution_zones()
        if zones:
            telemetry["site_constraints"] = list(telemetry.get("site_constraints") or []) + zones
        return telemetry

    # ------------------------------------------------------- run-loop helpers
    def due(self, run_id: str) -> bool:
        return (settings.vision_configured and run_id not in self._busy
                and time.time() - self._last_check.get(run_id, 0.0) >= settings.vision_interval_s)

    async def run_check(self, sim, telemetry: Dict[str, Any], run_id: str) -> None:
        """Background check for a run; results are recorded by the run loop itself
        (drain_results) so the audit chain is only ever written from one place."""
        self._busy.add(run_id)
        self._last_check[run_id] = time.time()
        try:
            await self.check(sim, dict(telemetry), run_id=run_id)
        except Exception as e:
            logger.warning("Run %s: vision check skipped: %s", run_id, e)
        finally:
            self._busy.discard(run_id)

    def drain_results(self, run_id: str) -> List[Dict[str, Any]]:
        return self._pending.pop(run_id, [])

    def forget(self, run_id: str) -> None:
        self._pending.pop(run_id, None)
        self._last_check.pop(run_id, None)
        self._busy.discard(run_id)

    def status(self) -> Dict[str, Any]:
        return {
            "enabled": settings.vision_configured, "model": settings.vision_model,
            "interval_s": settings.vision_interval_s, "match_m": settings.vision_match_m,
            "caution_ttl_s": settings.vision_caution_ttl_s, "caution_zones": self.caution_zones(),
            "recent": list(self.recent)[-10:],
        }


def audit_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    """Compact PERCEPTION event payload for the hash chain."""
    def brief(items):
        return [{k: o.get(k) for k in ("type", "x", "y", "ahead_m", "right_m", "error_m") if k in o} for o in items]
    return {
        "check_id": result["id"], "model": result["model"], "verdict": result["verdict"],
        "latency_ms": result.get("latency_ms"), "robot": result.get("robot"),
        "matched": brief(result.get("matched", [])), "missed": brief(result.get("missed", [])),
        "unconfirmed": brief(result.get("unconfirmed", [])),
        "caution_zones": [z["id"] for z in result.get("caution_zones", [])],
        "note": result.get("note") or {
            "agree": "Vision agrees with the sensors.",
            "missed_hazard": "Vision missed a hazard the sensors see; the gate kept using the sensors.",
            "unconfirmed_sighting": "Vision reported something the sensors do not see; a short slow zone was added.",
        }.get(result["verdict"], ""),
    }


perception = Perception()
