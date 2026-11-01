"""Governance-bounded parameter optimizer.

Searches the operational parameter space while respecting hard governance
constraints.  Uses the scoring engine as the objective function and treats
policy violations as hard boundaries (not just penalties).

The optimizer NEVER proposes parameters outside the governance envelope —
it is governance-led, not reward-led.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.models import Run, GovernanceDecisionRecord, TelemetrySample
from app.services.scoring_engine import compute_scorecard, WEIGHTS
from app.policies.rules_python import (
    GEOFENCE,
    ZONE_SPEED_LIMITS,
    MIN_OBSTACLE_CLEARANCE_M,
    HUMAN_SLOW_RADIUS_M,
    HUMAN_STOP_RADIUS_M,
    MAX_SPEED_NEAR_HUMAN,
    REVIEW_RISK_THRESHOLD,
)

logger = logging.getLogger("app.optimizer")


# Hard safety bounds — these are ABSOLUTE and cannot be relaxed
HARD_BOUNDS = {
    "max_speed_aisle": {"min": 0.1, "max": float(ZONE_SPEED_LIMITS.get("aisle", 0.5))},
    "max_speed_loading": {"min": 0.1, "max": float(ZONE_SPEED_LIMITS.get("loading_bay", 0.4))},
    "max_speed_open": {"min": 0.1, "max": float(ZONE_SPEED_LIMITS.get("corridor", 0.7))},
    "obstacle_clearance_m": {"min": float(MIN_OBSTACLE_CLEARANCE_M), "max": 3.0},
    "human_slow_radius_m": {"min": float(HUMAN_STOP_RADIUS_M) + 0.5, "max": 10.0},
    "human_stop_radius_m": {"min": 0.5, "max": float(HUMAN_SLOW_RADIUS_M)},
    "max_speed_near_human": {"min": 0.05, "max": float(MAX_SPEED_NEAR_HUMAN)},
}

# Current operating parameters (mutable snapshot)
CURRENT_PARAMS = {
    "max_speed_aisle": float(ZONE_SPEED_LIMITS.get("aisle", 0.5)),
    "max_speed_loading": float(ZONE_SPEED_LIMITS.get("loading_bay", 0.4)),
    "max_speed_open": float(ZONE_SPEED_LIMITS.get("corridor", 0.7)),
    "obstacle_clearance_m": float(MIN_OBSTACLE_CLEARANCE_M),
    "human_slow_radius_m": float(HUMAN_SLOW_RADIUS_M),
    "human_stop_radius_m": float(HUMAN_STOP_RADIUS_M),
    "max_speed_near_human": float(MAX_SPEED_NEAR_HUMAN),
}


def _clamp_to_bounds(param: str, value: float) -> float:
    bounds = HARD_BOUNDS.get(param, {"min": 0, "max": 999})
    return max(bounds["min"], min(bounds["max"], value))


def _governance_violation_rate(db: Session, run_id: str) -> float:
    """Get the denial/review rate for a run."""
    decisions = db.query(GovernanceDecisionRecord).filter(
        GovernanceDecisionRecord.run_id == run_id
    ).all()
    if not decisions:
        return 0.0
    violations = sum(1 for d in decisions if d.decision != "APPROVED")
    return violations / len(decisions)


def analyze_run_performance(db: Session, run_id: str) -> Dict[str, Any]:
    """Analyse a completed run and produce governance-bounded optimization
    recommendations.

    Returns parameter adjustment suggestions that stay within HARD_BOUNDS.
    """
    scorecard = compute_scorecard(db, run_id)
    if "error" in scorecard:
        return {"error": scorecard["error"]}

    violation_rate = _governance_violation_rate(db, run_id)
    recommendations: List[Dict[str, Any]] = []

    scores = scorecard.get("scores", {})
    safety_score = scores.get("safety", 1.0)
    efficiency_score = scores.get("efficiency", 0.5)
    smoothness_score = scores.get("smoothness", 0.5)
    compliance_score = scores.get("compliance", 1.0)

    # Rule 1: If compliance is low, tighten parameters (safety-first)
    if compliance_score < 0.85:
        recommendations.append({
            "param": "max_speed_aisle",
            "direction": "decrease",
            "reason": f"Low compliance ({compliance_score:.2f}) — reduce speed to improve approval rate",
            "suggested": _clamp_to_bounds("max_speed_aisle", CURRENT_PARAMS["max_speed_aisle"] * 0.85),
            "current": CURRENT_PARAMS["max_speed_aisle"],
        })
        recommendations.append({
            "param": "obstacle_clearance_m",
            "direction": "increase",
            "reason": "Low compliance — increase obstacle clearance buffer",
            "suggested": _clamp_to_bounds("obstacle_clearance_m", CURRENT_PARAMS["obstacle_clearance_m"] * 1.3),
            "current": CURRENT_PARAMS["obstacle_clearance_m"],
        })

    # Rule 2: If safety is high and efficiency is low, carefully relax speed
    if safety_score > 0.9 and efficiency_score < 0.5 and compliance_score > 0.9:
        recommendations.append({
            "param": "max_speed_aisle",
            "direction": "increase",
            "reason": f"Safety is high ({safety_score:.2f}), efficiency low ({efficiency_score:.2f}) — cautiously increase speed",
            "suggested": _clamp_to_bounds("max_speed_aisle", CURRENT_PARAMS["max_speed_aisle"] * 1.05),
            "current": CURRENT_PARAMS["max_speed_aisle"],
        })

    # Rule 3: If smoothness is poor, widen human slow radius
    if smoothness_score < 0.5:
        recommendations.append({
            "param": "human_slow_radius_m",
            "direction": "increase",
            "reason": f"Low smoothness ({smoothness_score:.2f}) — increase slow radius for gentler deceleration",
            "suggested": _clamp_to_bounds("human_slow_radius_m", CURRENT_PARAMS["human_slow_radius_m"] * 1.1),
            "current": CURRENT_PARAMS["human_slow_radius_m"],
        })

    # Rule 4: If violation rate is high, reduce all speeds
    if violation_rate > 0.3:
        for speed_param in ["max_speed_aisle", "max_speed_loading", "max_speed_open"]:
            recommendations.append({
                "param": speed_param,
                "direction": "decrease",
                "reason": f"High violation rate ({violation_rate:.0%}) — reduce speed limits",
                "suggested": _clamp_to_bounds(speed_param, CURRENT_PARAMS[speed_param] * 0.8),
                "current": CURRENT_PARAMS[speed_param],
            })

    return {
        "run_id": run_id,
        "scorecard": scorecard,
        "violation_rate": round(violation_rate, 3),
        "recommendations": recommendations,
        "hard_bounds": HARD_BOUNDS,
        "current_params": CURRENT_PARAMS,
        "governance_led": True,
        "note": "All recommendations stay within governance hard-bounds. Safety parameters can only tighten, never relax beyond policy limits.",
    }


def get_optimization_envelope() -> Dict[str, Any]:
    """Return the governance envelope — the hard boundaries that the optimizer
    must respect.  No parameter can be set outside these bounds."""
    return {
        "hard_bounds": HARD_BOUNDS,
        "current_params": CURRENT_PARAMS,
        "governance_constraints": [
            "Speed limits cannot exceed zone policy maximums",
            "Obstacle clearance cannot go below MIN_OBSTACLE_CLEARANCE_M",
            "Human stop radius cannot be reduced below 0.5m",
            "Human slow radius must exceed stop radius + 0.5m",
            "All changes require governance re-evaluation before deployment",
        ],
    }
