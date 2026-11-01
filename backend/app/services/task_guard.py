"""Task-drift guard: every plan and replan must still serve the mission.

The gate judges each move for safety; this guard judges each *plan* for task
focus before the robot uses it. A model plan (or a replan after a denial) is
accepted only if:

1. it ends at the mission's destination (the goal comes from the mission record,
   never from the model);
2. every waypoint is inside the site boundary;
3. it is not a wandering detour: its length stays within a bounded multiple of
   the reference route along the aisles;
4. it is a sane size.

A plan that fails is not used. The robot follows the deterministic aisle route
to the same destination instead, and the decision is recorded (TASK_CHECK event)
so drift is visible in the audit chain and the UI.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

GOAL_TOLERANCE_M = 1.5        # last waypoint must be this close to the mission goal
MAX_DETOUR_RATIO = 2.0        # plan length ≤ ratio × reference route length + slack
DETOUR_SLACK_M = 8.0          # absolute allowance for sensible detours round people/hazards
MAX_WAYPOINTS = 60


def path_length(start: Dict[str, Any], waypoints: List[Dict[str, Any]]) -> float:
    pts = [(float(start["x"]), float(start["y"]))] + [(float(w["x"]), float(w["y"])) for w in waypoints]
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


def check_plan(start: Dict[str, Any], goal: Dict[str, Any], waypoints: List[Dict[str, Any]],
               geofence: Dict[str, float], reference: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Return {verdict: ON_TASK | DRIFT, reasons, metrics}. Pure function; no side effects."""
    reasons: List[str] = []
    gx, gy = float(goal["x"]), float(goal["y"])
    metrics: Dict[str, Any] = {"waypoints": len(waypoints), "goal": {"x": gx, "y": gy}}

    if not waypoints:
        return {"verdict": "DRIFT", "reasons": ["Plan has no waypoints."], "metrics": metrics}
    if len(waypoints) > MAX_WAYPOINTS:
        reasons.append(f"Plan has {len(waypoints)} waypoints (limit {MAX_WAYPOINTS}).")

    last = waypoints[-1]
    end_gap = math.dist((float(last["x"]), float(last["y"])), (gx, gy))
    metrics["end_distance_to_goal_m"] = round(end_gap, 2)
    if end_gap > GOAL_TOLERANCE_M:
        reasons.append(f"Plan ends {end_gap:.1f} m from the mission destination ({gx:.1f}, {gy:.1f}).")

    outside = [i for i, w in enumerate(waypoints)
               if not (geofence["min_x"] <= float(w["x"]) <= geofence["max_x"]
                       and geofence["min_y"] <= float(w["y"]) <= geofence["max_y"])]
    if outside:
        reasons.append(f"Waypoints outside the site boundary: {outside[:5]}.")

    length = path_length(start, waypoints)
    metrics["plan_length_m"] = round(length, 1)
    if reference:
        ref_len = path_length(start, reference)
        limit = MAX_DETOUR_RATIO * ref_len + DETOUR_SLACK_M
        metrics.update(reference_length_m=round(ref_len, 1), length_limit_m=round(limit, 1))
        if length > limit:
            reasons.append(f"Plan is {length:.0f} m long; the route along the aisles is {ref_len:.0f} m (limit {limit:.0f} m).")

    return {"verdict": "DRIFT" if reasons else "ON_TASK", "reasons": reasons, "metrics": metrics}


def guard(plan: Dict[str, Any], start: Dict[str, Any], goal: Dict[str, Any], world: Dict[str, Any],
          speed_limits: Dict[str, float], hazards: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Check a plan; on drift, replace its waypoints with the aisle route to the same goal.

    Returns {"plan": plan_to_use, "check": {...}, "replaced": bool}.
    """
    from app.services.site_router import route_plan
    from app.world_model import GEOFENCE

    reference = None
    try:
        reference = route_plan(world, start, goal, speed_limits, hazards=hazards)
    except Exception:
        reference = None
    check = check_plan(start, goal, plan.get("waypoints") or [], GEOFENCE, reference)
    if check["verdict"] == "ON_TASK":
        return {"plan": plan, "check": check, "replaced": False}
    if reference:
        fallback = {**plan, "waypoints": reference, "model_used": "site_router",
                    "rationale": "[Task guard] Model plan rejected for drift; following the aisle route to the mission destination.",
                    "rejected_plan": {"model_used": plan.get("model_used"), "waypoints": (plan.get("waypoints") or [])[:20]}}
        check["action"] = "replaced_with_aisle_route"
        return {"plan": fallback, "check": check, "replaced": True}
    check["action"] = "no_safe_route; plan kept for the gate to judge step by step"
    return {"plan": plan, "check": check, "replaced": False}
