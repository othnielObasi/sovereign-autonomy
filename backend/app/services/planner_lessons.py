"""Planner learning loop — location-aware lessons distilled from the governance gate.

How Sovereign Autonomy learns (the "fast loop"):

1. After each run, the gate's own decision records are distilled into lessons:
   *where* a policy denied moves (a 2 m grid cell + zone), how often, across
   which runs, and which speeds the gate approved in that same cell.
2. Before planning or replanning, lessons near the route corridor are retrieved
   and handed to the planner (Muse Spark) as advisory context.
3. Every PLAN / REPLAN event records which lesson IDs were applied, so the
   effect of learning is auditable and replayable.

Safety properties:
- Lessons come only from deterministic gate records, never from model output
  or external context, so a model or a poisoned web page cannot write a lesson.
- Lessons only shape what the planner *proposes*. The gate's rules are untouched;
  changing a rule is a separate, human-approved process.
- Lessons are scoped to the policy version they were learned under. When the
  rules change, old lessons stop being retrieved instead of misleading the planner.
"""
from __future__ import annotations

import json
import logging
import math
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.db.models import AgentMemoryEntry, GovernanceDecisionRecord
from app.policies.versioning import policy_version_hash
from app.utils.time import utc_now

logger = logging.getLogger("app.planner_lessons")

CATEGORY_SPATIAL = "spatial_lesson"
CELL_M = 2.0                 # lesson grid resolution (metres)
ROUTE_CORRIDOR_M = 4.0       # lessons within this distance of the planned route are relevant
NEAR_START_M = 6.0           # fallback radius when no goal is known
MAX_LESSONS_IN_PROMPT = 5
MAX_SPATIAL_LESSONS = 200

HARD_POLICIES = {"GEOFENCE_01", "HUMAN_PROXIMITY_02", "WORKER_PROXIMITY_06", "OBSTACLE_CLEARANCE_03",
                 "PATH_CLEARANCE_07"}

# Policies about where the robot is or how fast it moves there: an approved speed
# in the same cell is real evidence of what the gate accepts at that spot.
STATIC_POLICIES = {"SAFE_SPEED_01", "GEOFENCE_01"}

# Plain-English meaning of each policy, used in lesson wording. A decision can
# hit several policies with one shared reasons list, so lessons describe the
# policy itself rather than guessing which reason belongs to it.
POLICY_DESCRIPTIONS = {
    "GEOFENCE_01": "position or target outside the operating boundary",
    "SAFE_SPEED_01": "speed above this zone's limit",
    "HUMAN_PROXIMITY_02": "a person inside the stop radius",
    "HUMAN_CLEARANCE_02": "too fast with a person detected nearby",
    "OBSTACLE_CLEARANCE_03": "obstacle clearance below the minimum",
    "UNCERTAINTY_04": "a person detected with low perception confidence",
    "HITL_05": "risk high enough to need operator review",
    "WORKER_PROXIMITY_06": "a walking worker inside the stop radius",
    "PATH_CLEARANCE_07": "a straight path through racking",
    "HAZARD_EXCLUSION_08": "a move into a hazard exclusion zone",
    "HAZARD_SLOW_09": "too fast near a hazard zone",
}

# Temporary hazards (a spill is cleaned up) must not become lessons about a place.
TRANSIENT_POLICIES = {"HAZARD_EXCLUSION_08", "HAZARD_SLOW_09"}

ADVICE = {
    "HUMAN_PROXIMITY_02": "People are often here: approach slowly and prefer a route with more clearance.",
    "WORKER_PROXIMITY_06": "Workers often cross here: approach slowly and prefer a route with more clearance.",
    "HUMAN_CLEARANCE_02": "Slow down earlier when people are nearby here.",
    "UNCERTAINTY_04": "Perception is often uncertain here: slow down before entering.",
    "OBSTACLE_CLEARANCE_03": "Obstacles often block this spot: route around it.",
    "GEOFENCE_01": "Keep waypoints well inside the boundary here.",
    "HITL_05": "Moves here often need operator review: choose a lower-risk route.",
    "PATH_CLEARANCE_07": "Plans from here cut through racking: route via the aisles and cross-aisles.",
}

_DENIED = ("DENIED", "NEEDS_REVIEW")


def _cell(x: float, y: float) -> Tuple[float, float]:
    """Centre of the CELL_M grid cell containing (x, y)."""
    return (math.floor(x / CELL_M) * CELL_M + CELL_M / 2,
            math.floor(y / CELL_M) * CELL_M + CELL_M / 2)


def _key(policy: str, zone: str, cell: Tuple[float, float], version: str) -> str:
    return f"{version}|{policy}|{zone}|{cell[0]:.1f},{cell[1]:.1f}"


def _load(entries: Iterable[AgentMemoryEntry]) -> Dict[str, Tuple[AgentMemoryEntry, Dict[str, Any]]]:
    out: Dict[str, Tuple[AgentMemoryEntry, Dict[str, Any]]] = {}
    for e in entries:
        try:
            c = json.loads(e.content_json)
        except (TypeError, ValueError):
            continue
        if "key" in c:
            out[c["key"]] = (e, c)
    return out


def lesson_text(c: Dict[str, Any]) -> str:
    """Deterministic, plain-English wording of one lesson."""
    runs = len(c.get("runs", []))
    where = f"near ({c['cell_x']:.0f}, {c['cell_y']:.0f}) in {c['zone']}"
    what = POLICY_DESCRIPTIONS.get(c["policy"], "a policy violation")
    text = (f"{where}: {c['denials']} denial{'s' if c['denials'] != 1 else ''} "
            f"across {runs} run{'s' if runs != 1 else ''} for {c['policy']} ({what}).")
    if c["policy"] in STATIC_POLICIES and c.get("max_approved_speed") is not None:
        text += f" Moves here were approved at up to {c['max_approved_speed']:.2f} m/s."
    elif c["policy"] in ADVICE:
        text += " " + ADVICE[c["policy"]]
    return text


# ---------------------------------------------------------------------------
# Distil: run decisions -> lessons
# ---------------------------------------------------------------------------

def distill_run(db: Session, run_id: str) -> List[Dict[str, Any]]:
    """Fold one run's gate decisions into the spatial lesson store.

    Idempotent: a run already counted in a lesson is never counted again.
    Returns the lessons created or updated by this run.
    """
    records = (
        db.query(GovernanceDecisionRecord)
        .filter(GovernanceDecisionRecord.run_id == run_id)
        .order_by(GovernanceDecisionRecord.id.asc())
        .all()
    )
    if not records:
        return []

    # Aggregate this run's denials by (version, policy, zone, cell)
    agg: Dict[str, Dict[str, Any]] = {}
    approved_speed: Dict[Tuple[str, float, float], float] = {}  # (version, cell) -> max approved speed

    for r in records:
        try:
            tel = json.loads(r.telemetry_summary or "{}")
            prop = json.loads(r.proposal_json or "{}")
            hits = json.loads(r.policy_hits or "[]")
            reasons = json.loads(r.reasons or "[]")
        except (TypeError, ValueError):
            continue
        if "x" not in tel or "y" not in tel:
            continue
        version = r.policy_version or policy_version_hash()
        cell = _cell(float(tel["x"]), float(tel["y"]))
        zone = str(tel.get("zone") or "unknown")

        if r.decision == "APPROVED" and r.was_executed == "true" and r.proposal_intent == "MOVE_TO":
            speed = (prop.get("params") or {}).get("max_speed")
            if speed is not None:
                k = (version, cell[0], cell[1])
                approved_speed[k] = max(approved_speed.get(k, 0.0), float(speed))
            continue

        if r.decision not in _DENIED:
            continue
        hits = [h for h in hits if h not in TRANSIENT_POLICIES]
        if not hits:
            continue
        for policy in hits or ["UNSPECIFIED"]:
            if policy == "CIRCUIT_BREAKER":
                continue
            key = _key(policy, zone, cell, version)
            a = agg.setdefault(key, {
                "key": key, "policy": policy, "zone": zone, "policy_version": version,
                "cell_x": cell[0], "cell_y": cell[1], "denials": 0, "example_reason": None,
            })
            a["denials"] += 1
            if not a["example_reason"] and len(hits) == 1:  # reasons only map cleanly to a single hit
                a["example_reason"] = next((s for s in reasons if not s.startswith("Circuit breaker")), None)

    if not agg:
        return []

    existing = _load(db.query(AgentMemoryEntry).filter(AgentMemoryEntry.category == CATEGORY_SPATIAL).all())
    touched: List[Dict[str, Any]] = []
    now = utc_now()

    for key, a in agg.items():
        speed = approved_speed.get((a["policy_version"], a["cell_x"], a["cell_y"]))
        if key in existing:
            entry, c = existing[key]
            if run_id in c.get("runs", []):
                continue  # already counted
            c["denials"] += a["denials"]
            c["runs"] = (c.get("runs", []) + [run_id])[-50:]
            c["example_reason"] = c.get("example_reason") or a["example_reason"]
            if speed is not None:
                prev = c.get("max_approved_speed")
                c["max_approved_speed"] = speed if prev is None else max(prev, speed)
            c["text"] = lesson_text(c)
            entry.content_json = json.dumps(c)
            entry.ts = now
            entry.importance = _importance(c)
            entry.run_id = run_id
        else:
            c = dict(a, runs=[run_id], max_approved_speed=speed)
            c["text"] = lesson_text(c)
            entry = AgentMemoryEntry(run_id=run_id, category=CATEGORY_SPATIAL, ts=now,
                                     content_json=json.dumps(c), importance=_importance(c))
            db.add(entry)
        touched.append(c)

    _enforce_limit(db)
    db.commit()
    logger.info("Run %s: distilled %d spatial lesson(s)", run_id, len(touched))
    return touched


def _importance(c: Dict[str, Any]) -> float:
    base = 0.9 if c["policy"] in HARD_POLICIES else 0.7
    return min(1.0, base + 0.02 * (c["denials"] - 1))


def _enforce_limit(db: Session) -> None:
    q = db.query(AgentMemoryEntry).filter(AgentMemoryEntry.category == CATEGORY_SPATIAL)
    excess = q.count() - MAX_SPATIAL_LESSONS
    if excess > 0:
        for e in q.order_by(AgentMemoryEntry.importance.asc(), AgentMemoryEntry.ts.asc()).limit(excess).all():
            db.delete(e)


# ---------------------------------------------------------------------------
# Retrieve: lessons relevant to a route
# ---------------------------------------------------------------------------

def _dist_to_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def lessons_for_route(
    db: Session,
    start: Dict[str, Any],
    goal: Optional[Dict[str, Any]] = None,
    limit: int = MAX_LESSONS_IN_PROMPT,
    avoid: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Lessons near the straight-line corridor from start to goal, current policy version only.

    `avoid` (e.g. a blocked waypoint during a replan) is treated as part of the route.
    """
    version = policy_version_hash()
    sx, sy = float(start.get("x", 0)), float(start.get("y", 0))
    pts = [(sx, sy)]
    if avoid and "x" in avoid and "y" in avoid:
        pts.append((float(avoid["x"]), float(avoid["y"])))
    if goal and "x" in goal and "y" in goal:
        pts.append((float(goal["x"]), float(goal["y"])))
    segments = list(zip(pts, pts[1:], strict=False))

    scored: List[Tuple[float, int, Dict[str, Any]]] = []
    for entry in db.query(AgentMemoryEntry).filter(AgentMemoryEntry.category == CATEGORY_SPATIAL).all():
        try:
            c = json.loads(entry.content_json)
        except (TypeError, ValueError):
            continue
        if c.get("policy_version") != version:
            continue
        cx, cy = c["cell_x"], c["cell_y"]
        if segments:
            d = min(_dist_to_segment(cx, cy, a[0], a[1], b[0], b[1]) for a, b in segments)
            radius = ROUTE_CORRIDOR_M
        else:
            d = math.hypot(cx - sx, cy - sy)
            radius = NEAR_START_M
        if d > radius:
            continue
        weight = (2.0 if c["policy"] in HARD_POLICIES else 1.0) * c["denials"] * len(c.get("runs", [1]))
        scored.append((weight / (1.0 + d), entry.id, c))

    scored.sort(key=lambda s: (-s[0], s[1]))
    return [
        {"id": eid, "text": lesson_text(c), "policy": c["policy"], "zone": c["zone"],
         "cell": [c["cell_x"], c["cell_y"]], "denials": c["denials"], "runs": len(c.get("runs", []))}
        for _, eid, c in scored[:limit]
    ]


def format_for_prompt(lessons: List[Dict[str, Any]]) -> str:
    if not lessons:
        return ""
    lines = ["LESSONS FROM PAST RUNS (learned from the safety gate's decisions; advisory only, "
             "the gate still evaluates every move):"]
    lines += [f"- [L{l['id']}] {l['text']}" for l in lessons]
    lines.append("Plan routes and speeds that avoid repeating these denials.")
    return "\n".join(lines)


def all_lessons(db: Session, current_version_only: bool = True) -> List[Dict[str, Any]]:
    version = policy_version_hash()
    out = []
    for e in (db.query(AgentMemoryEntry).filter(AgentMemoryEntry.category == CATEGORY_SPATIAL)
              .order_by(AgentMemoryEntry.importance.desc(), AgentMemoryEntry.ts.desc()).all()):
        c = json.loads(e.content_json)
        if current_version_only and c.get("policy_version") != version:
            continue
        out.append({"id": e.id, "updated": e.ts.isoformat() if e.ts else None, **c, "text": lesson_text(c)})
    return out
