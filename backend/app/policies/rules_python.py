from __future__ import annotations

import math
from typing import Dict, Any, Tuple, List
from app.schemas.governance import GovernanceDecision, ActionProposal
from app.policies.params import DEFAULT_PARAMS, active_params
from app.policies.retreat import is_slow_retreat
from app.policies.site_map import path_blocked


# --- Policy parameters ---
# Module constants are the DEFAULTS (kept for importers and tests). The gate
# itself reads the ACTIVE set (app/policies/params.py), which changes only via
# the governed proposal workflow.
GEOFENCE = DEFAULT_PARAMS["GEOFENCE"]
ZONE_SPEED_LIMITS = DEFAULT_PARAMS["ZONE_SPEED_LIMITS"]
MIN_OBSTACLE_CLEARANCE_M = DEFAULT_PARAMS["MIN_OBSTACLE_CLEARANCE_M"]
MIN_HUMAN_CONF = DEFAULT_PARAMS["MIN_HUMAN_CONF"]
MAX_SPEED_NEAR_HUMAN = DEFAULT_PARAMS["MAX_SPEED_NEAR_HUMAN"]
MIN_CONF_FOR_MOVE = DEFAULT_PARAMS["MIN_CONF_FOR_MOVE"]

# Distance-based human proximity thresholds (Fix 2)
HUMAN_SLOW_RADIUS_M = DEFAULT_PARAMS["HUMAN_SLOW_RADIUS_M"]   # slow down when human within this range
HUMAN_STOP_RADIUS_M = DEFAULT_PARAMS["HUMAN_STOP_RADIUS_M"]   # full stop when human within this range

REVIEW_RISK_THRESHOLD = DEFAULT_PARAMS["REVIEW_RISK_THRESHOLD"]

# --- Hard vs Soft failure classification (#14) ---
# HARD failures: immediate DENIED, no override possible, no upgrade to NEEDS_REVIEW
# SOFT failures: can be DENIED or upgraded to NEEDS_REVIEW for operator decision
HARD_FAIL_POLICIES = frozenset({
    "GEOFENCE_01",          # Outside operating boundary — absolute safety limit
    "HUMAN_PROXIMITY_02",   # Human within stop radius — must stop immediately
    "WORKER_PROXIMITY_06",  # Worker within stop radius — must stop immediately
    "OBSTACLE_CLEARANCE_03",  # Collision imminent — hard stop
    "PATH_CLEARANCE_07",    # Straight path runs through racking — replan along the aisles
    "HAZARD_EXCLUSION_08",  # Move enters or crosses a hazard exclusion zone — replan around it
})
SOFT_FAIL_POLICIES = frozenset({
    "SAFE_SPEED_01",        # Speed violation — can slow down
    "HUMAN_CLEARANCE_02",   # Near human — reduce speed
    "UNCERTAINTY_04",       # Low confidence — proceed cautiously
    "HITL_05",              # High risk threshold — operator review
    "HAZARD_SLOW_09",       # Too fast near a hazard zone — slow down
})


def _segment_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    """Shortest distance from point P to segment AB."""
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def evaluate_policies(
    telemetry: Dict[str, Any],
    proposal: ActionProposal,
    params: Dict[str, Any] | None = None,
) -> GovernanceDecision:
    """Evaluate a proposal against a small policy set.

    Returns an APPROVED / DENIED / NEEDS_REVIEW decision with reasons
    and an explicit policy_state (SAFE / SLOW / STOP / REPLAN).
    """
    p = params if params is not None else active_params()
    GEOFENCE = p["GEOFENCE"]
    ZONE_SPEED_LIMITS = p["ZONE_SPEED_LIMITS"]
    MIN_OBSTACLE_CLEARANCE_M = float(p["MIN_OBSTACLE_CLEARANCE_M"])
    MIN_HUMAN_CONF = float(p["MIN_HUMAN_CONF"])
    MAX_SPEED_NEAR_HUMAN = float(p["MAX_SPEED_NEAR_HUMAN"])
    MIN_CONF_FOR_MOVE = float(p["MIN_CONF_FOR_MOVE"])
    HUMAN_SLOW_RADIUS_M = float(p["HUMAN_SLOW_RADIUS_M"])
    HUMAN_STOP_RADIUS_M = float(p["HUMAN_STOP_RADIUS_M"])
    REVIEW_RISK_THRESHOLD = float(p["REVIEW_RISK_THRESHOLD"])

    policy_hits: List[str] = []
    reasons: List[str] = []
    required_action: str | None = None
    # Explicit safety state for the UI
    policy_state: str = "SAFE"

    # Risk score is a simple heuristic (0..1) for demo purposes
    risk_score = 0.0

    x = float(telemetry.get("x", 0.0))
    y = float(telemetry.get("y", 0.0))
    zone = telemetry.get("zone", "aisle")
    nearest_obstacle_m = float(telemetry.get("nearest_obstacle_m", 999.0))
    human_detected = bool(telemetry.get("human_detected", False))
    human_conf = float(telemetry.get("human_conf", 0.0))
    human_distance_m = float(telemetry.get("human_distance_m", 999.0))

    # Consider walking humans (workers) separately if provided by telemetry
    walking_humans = telemetry.get("walking_humans", []) or []
    nearest_worker_dist = 999.0
    nearest_worker_conf = 0.0
    for wh in walking_humans:
        try:
            wd = float(wh.get("x", 0))
            wd_y = float(wh.get("y", 0))
            d = ((wd - x) ** 2 + (wd_y - y) ** 2) ** 0.5
            if d < nearest_worker_dist:
                nearest_worker_dist = d
                nearest_worker_conf = float(wh.get("conf", 0.9))
        except Exception:
            continue

    intent = proposal.intent
    params = proposal.params or {}
    max_speed = float(params.get("max_speed", 0.0)) if intent == "MOVE_TO" else 0.0

    # --- GEOFENCE_01 ---
    if not (GEOFENCE["min_x"] <= x <= GEOFENCE["max_x"] and GEOFENCE["min_y"] <= y <= GEOFENCE["max_y"]):
        policy_hits.append("GEOFENCE_01")
        reasons.append(f"Robot out of geofence at ({x:.2f},{y:.2f}).")
        risk_score = max(risk_score, 0.95)
        policy_state = "STOP"

    # Also check proposed destination
    if intent == "MOVE_TO":
        dest_x = float(params.get("x", x))
        dest_y = float(params.get("y", y))
        if not (GEOFENCE["min_x"] <= dest_x <= GEOFENCE["max_x"] and GEOFENCE["min_y"] <= dest_y <= GEOFENCE["max_y"]):
            if "GEOFENCE_01" not in policy_hits:
                policy_hits.append("GEOFENCE_01")
            reasons.append(f"Proposed destination ({dest_x:.2f},{dest_y:.2f}) is outside geofence.")
            risk_score = max(risk_score, 0.95)
            policy_state = "STOP"

    # --- OBSTACLE_CLEARANCE_03 ---
    if (intent == "MOVE_TO" and nearest_obstacle_m < MIN_OBSTACLE_CLEARANCE_M
            and not is_slow_retreat(telemetry, params)):
        policy_hits.append("OBSTACLE_CLEARANCE_03")
        reasons.append(f"Obstacle clearance too low: {nearest_obstacle_m:.2f}m < {MIN_OBSTACLE_CLEARANCE_M:.2f}m.")
        required_action = "Stop and replan with safer clearance."
        risk_score = max(risk_score, 0.9)
        policy_state = "REPLAN"

    # --- PATH_CLEARANCE_07: the straight path must not run through permanent racking ---
    if intent == "MOVE_TO" and "x" in params and "y" in params:
        blocked_by = path_blocked(x, y, float(params["x"]), float(params["y"]))
        if blocked_by:
            policy_hits.append("PATH_CLEARANCE_07")
            reasons.append(f"Path to ({float(params['x']):.1f},{float(params['y']):.1f}) runs through rack {blocked_by}.")
            required_action = "Replan along the aisles."
            risk_score = max(risk_score, 0.9)
            policy_state = "REPLAN"

    # --- HAZARD_EXCLUSION_08 / HAZARD_SLOW_09: temporary zones round hazards ---
    # Zones only ever restrict motion; the gate reads their geometry and limits,
    # never the outside text they were derived from.
    if intent == "MOVE_TO" and "x" in params and "y" in params:
        tx, ty = float(params["x"]), float(params["y"])
        for z in telemetry.get("site_constraints") or []:
            try:
                zx, zy, zr = float(z["x"]), float(z["y"]), float(z["radius"])
                zs, zv = float(z.get("slow_radius", zr)), float(z.get("max_speed", 0.3))
            except (KeyError, TypeError, ValueError):
                continue
            label = str(z.get("label", "hazard"))
            here = math.hypot(x - zx, y - zy)
            there = math.hypot(tx - zx, ty - zy)
            closest = _segment_distance(zx, zy, x, y, tx, ty)
            inside = here < zr
            leaving = inside and there > here and closest >= here - 1e-6
            if (not inside and closest < zr) or (inside and not leaving):
                policy_hits.append("HAZARD_EXCLUSION_08")
                reasons.append(f"Move would enter the {zr:.1f} m exclusion zone round the {label}.")
                required_action = "Replan around the hazard zone."
                risk_score = max(risk_score, 0.92)
                policy_state = "REPLAN"
            elif leaving and max_speed > zv:
                policy_hits.append("HAZARD_EXCLUSION_08")
                reasons.append(f"Leaving the {label} zone must be at <= {zv:.2f} m/s (requested {max_speed:.2f}).")
                required_action = f"Back out of the zone at <= {zv:.2f} m/s."
                risk_score = max(risk_score, 0.9)
                policy_state = "STOP"
            elif min(here, closest) < zs and max_speed > zv:
                policy_hits.append("HAZARD_SLOW_09")
                reasons.append(f"Within {zs:.1f} m of the {label}: speed {max_speed:.2f} exceeds {zv:.2f} m/s.")
                required_action = f"Reduce speed to <= {zv:.2f} near the hazard."
                risk_score = max(risk_score, 0.78)
                if policy_state == "SAFE":
                    policy_state = "SLOW"

    # --- HUMAN / WORKER PROXIMITY ---
    # Prefer worker (walking_humans) proximity if one is nearer; otherwise use primary human
    use_worker = nearest_worker_dist < human_distance_m
    prox_dist = nearest_worker_dist if use_worker else human_distance_m
    prox_conf = nearest_worker_conf if use_worker else human_conf
    prox_label = "worker" if use_worker else "human"

    if intent == "MOVE_TO" and prox_dist < HUMAN_STOP_RADIUS_M:
        policy_key = "WORKER_PROXIMITY_06" if use_worker else "HUMAN_PROXIMITY_02"
        policy_hits.append(policy_key)
        reasons.append(
            f"{prox_label.capitalize()} too close: {prox_dist:.2f}m < stop radius {HUMAN_STOP_RADIUS_M:.1f}m. Full stop required."
        )
        required_action = "Full stop — human within safety perimeter."
        risk_score = max(risk_score, 0.95)
        policy_state = "STOP"

    elif intent == "MOVE_TO" and prox_dist < HUMAN_SLOW_RADIUS_M:
        # Slow radius: only trigger a policy hit if speed exceeds the safe limit.
        # Use HUMAN_CLEARANCE_02 (SOFT fail) — robot CAN proceed at safe speed.
        if max_speed > MAX_SPEED_NEAR_HUMAN:
            policy_hits.append("HUMAN_CLEARANCE_02")
            reasons.append(
                f"{prox_label.capitalize()} nearby: {prox_dist:.2f}m < slow radius {HUMAN_SLOW_RADIUS_M:.1f}m. "
                f"Speed {max_speed:.2f} exceeds safe limit {MAX_SPEED_NEAR_HUMAN:.2f}."
            )
            required_action = f"Reduce speed to <= {MAX_SPEED_NEAR_HUMAN:.2f} while {prox_label} is within {HUMAN_SLOW_RADIUS_M:.1f}m."
            risk_score = max(risk_score, 0.65)
            if policy_state == "SAFE":
                policy_state = "SLOW"

    # --- UNCERTAINTY_04 ---
    if intent == "MOVE_TO" and human_detected and human_conf < MIN_HUMAN_CONF:
        policy_hits.append("UNCERTAINTY_04")
        reasons.append(f"Human detected but confidence too low: {human_conf:.2f} < {MIN_HUMAN_CONF:.2f}.")
        required_action = "Slow down and request operator review; improve perception confidence."
        risk_score = max(risk_score, 0.8)
        if policy_state == "SAFE":
            policy_state = "SLOW"

    # --- SAFE_SPEED_01 ---
    if intent == "MOVE_TO":
        limit = float(ZONE_SPEED_LIMITS.get(zone, 0.5))
        if max_speed > limit:
            policy_hits.append("SAFE_SPEED_01")
            reasons.append(f"Speed too high for zone '{zone}': {max_speed:.2f} > {limit:.2f}.")
            required_action = f"Reduce max_speed to <= {limit:.2f}."
            risk_score = max(risk_score, 0.85)
            if policy_state == "SAFE":
                policy_state = "SLOW"

    # --- HUMAN_CLEARANCE_02 (confidence-based, legacy) ---
    if intent == "MOVE_TO" and human_detected and human_conf >= MIN_HUMAN_CONF:
        if max_speed > MAX_SPEED_NEAR_HUMAN:
            if "HUMAN_PROXIMITY_02" not in policy_hits and "HUMAN_CLEARANCE_02" not in policy_hits:
                policy_hits.append("HUMAN_CLEARANCE_02")
            reasons.append(f"Human nearby (conf={human_conf:.2f}); max_speed {max_speed:.2f} too high.")
            required_action = f"Reduce max_speed to <= {MAX_SPEED_NEAR_HUMAN:.2f} near humans."
            risk_score = max(risk_score, 0.88)
            if policy_state == "SAFE":
                policy_state = "SLOW"

    # --- MIN_CONF_FOR_MOVE (part of uncertainty) ---
    if intent == "MOVE_TO" and telemetry.get("human_detected") and human_conf < MIN_CONF_FOR_MOVE:
        risk_score = max(risk_score, 0.7)

    # --- HITL_05 (Human-in-the-loop trigger) ---
    if risk_score >= REVIEW_RISK_THRESHOLD and not policy_hits:
        policy_hits.append("HITL_05")
        reasons.append(f"Risk score {risk_score:.2f} exceeds review threshold {REVIEW_RISK_THRESHOLD:.2f}; human review required.")

    # Decision logic — with hard vs soft failure classification (#14)
    if policy_hits:
        # Check if any hard-fail policies triggered
        has_hard_fail = any(p in HARD_FAIL_POLICIES for p in policy_hits)
        hard_policies = [p for p in policy_hits if p in HARD_FAIL_POLICIES]
        soft_policies = [p for p in policy_hits if p in SOFT_FAIL_POLICIES]

        if has_hard_fail:
            # Hard failure: always DENIED, no operator override possible
            return GovernanceDecision(
                decision="DENIED",
                policy_hits=policy_hits,
                reasons=reasons,
                required_action=required_action,
                risk_score=risk_score,
                policy_state=policy_state,
                hard_fail=True,
                hard_fail_policies=hard_policies,
            )

        # Soft failure: can be upgraded to NEEDS_REVIEW for operator review
        if risk_score >= REVIEW_RISK_THRESHOLD:
            return GovernanceDecision(
                decision="NEEDS_REVIEW",
                policy_hits=policy_hits,
                reasons=reasons,
                required_action=required_action,
                risk_score=risk_score,
                policy_state=policy_state,
                hard_fail=False,
                hard_fail_policies=[],
            )
        return GovernanceDecision(
            decision="DENIED",
            policy_hits=policy_hits,
            reasons=reasons,
            required_action=required_action,
            risk_score=risk_score,
            policy_state=policy_state,
            hard_fail=False,
            hard_fail_policies=[],
        )

    return GovernanceDecision(
        decision="APPROVED",
        policy_hits=[],
        reasons=[],
        required_action=None,
        risk_score=risk_score,
        policy_state="SAFE",
        hard_fail=False,
        hard_fail_policies=[],
    )
