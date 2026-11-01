"""Adaptive tuning service: safe parameter *recommendations* (#12, #13).

Analyses historical run data to recommend parameter adjustments, bounded
by hard safety limits. Nothing here changes the active rules: a
recommendation only takes effect through the governed proposal workflow
(app/policies/proposals.py): replay gate, named human approval, versioned
activation, rollback.  Implements conservative Bayesian-style update:
only tightens safety parameters when evidence demands it, and only relaxes
efficiency parameters when safety margin is demonstrably sufficient.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.db.models import Run, GovernanceDecisionRecord
from app.services.scoring_engine import compute_scorecard
from app.services.optimizer import HARD_BOUNDS, CURRENT_PARAMS, _clamp_to_bounds

logger = logging.getLogger("app.adaptive_tuning")

# Safety margin: how much headroom required before relaxing a parameter
SAFETY_MARGIN = 0.15  # 15% above threshold required

# Minimum number of completed runs before recommendations are produced
MIN_RUNS_FOR_TUNING = 3

# Maximum adjustment per tuning cycle (prevents oscillation)
MAX_ADJUSTMENT_RATIO = 0.10  # 10% max change per cycle


def _gather_run_scorecards(db: Session, limit: int = 10) -> List[Dict[str, Any]]:
    """Collect scorecards from recent completed runs."""
    runs = (
        db.query(Run)
        .filter(Run.status.in_(["completed", "stopped"]))
        .order_by(Run.ended_at.desc())
        .limit(limit)
        .all()
    )
    scorecards = []
    for r in runs:
        sc = compute_scorecard(db, r.id)
        if "error" not in sc:
            sc["run_id"] = r.id
            scorecards.append(sc)
    return scorecards


def compute_tuning_recommendations(db: Session) -> Dict[str, Any]:
    """Analyse historical runs and produce safe parameter tuning recommendations.

    Safety parameters can only tighten. Efficiency parameters can only relax
    if safety scores consistently exceed thresholds.
    """
    scorecards = _gather_run_scorecards(db)
    n = len(scorecards)

    if n < MIN_RUNS_FOR_TUNING:
        return {
            "status": "insufficient_data",
            "mode": "recommend_only",
            "auto_tuning_active": False,
            "runs_analysed": n,
            "min_required": MIN_RUNS_FOR_TUNING,
            "recommendations": [],
            "message": f"Need at least {MIN_RUNS_FOR_TUNING} completed runs for tuning. Currently have {n}.",
        }

    # Compute averages across runs
    avg_scores: Dict[str, float] = {}
    for dim in ["safety", "compliance", "mission_success", "efficiency", "smoothness"]:
        vals = [sc.get("scores", {}).get(dim, 0.0) for sc in scorecards]
        avg_scores[dim] = sum(vals) / len(vals) if vals else 0.0

    avg_composite = sum(sc.get("composite", 0.0) for sc in scorecards) / n

    # Standard deviations for stability check
    std_scores: Dict[str, float] = {}
    for dim in ["safety", "compliance"]:
        vals = [sc.get("scores", {}).get(dim, 0.0) for sc in scorecards]
        mean = avg_scores[dim]
        variance = sum((v - mean) ** 2 for v in vals) / max(len(vals) - 1, 1)
        std_scores[dim] = math.sqrt(variance)

    recommendations: List[Dict[str, Any]] = []
    tuning_log: List[str] = []

    # Rule 1: Safety consistently high + stable → cautiously increase efficiency params
    safety_stable = std_scores.get("safety", 1.0) < 0.1
    safety_high = avg_scores["safety"] > (0.85 + SAFETY_MARGIN)

    if safety_high and safety_stable and avg_scores["efficiency"] < 0.6:
        for param in ["max_speed_aisle", "max_speed_open"]:
            delta = CURRENT_PARAMS[param] * MAX_ADJUSTMENT_RATIO
            new_val = _clamp_to_bounds(param, CURRENT_PARAMS[param] + delta)
            if new_val > CURRENT_PARAMS[param]:
                recommendations.append({
                    "param": param,
                    "direction": "increase",
                    "current": CURRENT_PARAMS[param],
                    "suggested": round(new_val, 3),
                    "confidence": round(1.0 - std_scores["safety"], 2),
                    "reason": f"Safety consistently high ({avg_scores['safety']:.2f}±{std_scores['safety']:.2f}), efficiency low ({avg_scores['efficiency']:.2f})",
                    "safe": True,
                })
        tuning_log.append("Safety headroom sufficient for cautious efficiency improvement")

    # Rule 2: Compliance dropping → tighten speed limits
    if avg_scores["compliance"] < 0.80:
        for param in ["max_speed_aisle", "max_speed_loading", "max_speed_open"]:
            delta = CURRENT_PARAMS[param] * MAX_ADJUSTMENT_RATIO
            new_val = _clamp_to_bounds(param, CURRENT_PARAMS[param] - delta)
            if new_val < CURRENT_PARAMS[param]:
                recommendations.append({
                    "param": param,
                    "direction": "decrease",
                    "current": CURRENT_PARAMS[param],
                    "suggested": round(new_val, 3),
                    "confidence": 0.9,
                    "reason": f"Compliance declining ({avg_scores['compliance']:.2f}) — tighten speed",
                    "safe": True,
                })
        tuning_log.append("Compliance below threshold — tightening speed parameters")

    # Rule 3: Smoothness consistently poor → increase human radii
    if avg_scores["smoothness"] < 0.4:
        for param in ["human_slow_radius_m"]:
            delta = CURRENT_PARAMS[param] * (MAX_ADJUSTMENT_RATIO * 0.5)
            new_val = _clamp_to_bounds(param, CURRENT_PARAMS[param] + delta)
            recommendations.append({
                "param": param,
                "direction": "increase",
                "current": CURRENT_PARAMS[param],
                "suggested": round(new_val, 3),
                "confidence": 0.7,
                "reason": f"Smoothness consistently low ({avg_scores['smoothness']:.2f}) — widen deceleration zone",
                "safe": True,
            })
        tuning_log.append("Smoothness low — increasing human slow radius")

    # Rule 4: Safety dropping → immediately tighten everything
    if avg_scores["safety"] < 0.7:
        for param in ["max_speed_aisle", "max_speed_loading", "max_speed_open", "max_speed_near_human"]:
            delta = CURRENT_PARAMS[param] * (MAX_ADJUSTMENT_RATIO * 2)  # double rate for safety
            new_val = _clamp_to_bounds(param, CURRENT_PARAMS[param] - delta)
            recommendations.append({
                "param": param,
                "direction": "decrease",
                "current": CURRENT_PARAMS[param],
                "suggested": round(new_val, 3),
                "confidence": 0.95,
                "reason": f"SAFETY ALERT: Average safety score {avg_scores['safety']:.2f} below threshold",
                "safe": True,
                "urgent": True,
            })
        tuning_log.append("URGENT: Safety below threshold — aggressive tightening recommended")

    return {
        "status": "ok",
        "runs_analysed": n,
        "avg_scores": {k: round(v, 3) for k, v in avg_scores.items()},
        "avg_composite": round(avg_composite, 3),
        "score_stability": {k: round(v, 3) for k, v in std_scores.items()},
        "recommendations": recommendations,
        "tuning_log": tuning_log,
        "hard_bounds": HARD_BOUNDS,
        "current_params": CURRENT_PARAMS,
        "auto_tuning_active": False,
        "mode": "recommend_only",
        "how_to_apply": "POST /policies/proposals/from-tuning, then evaluate, approve and activate",
        "safety_margin": SAFETY_MARGIN,
        "max_adjustment_per_cycle": MAX_ADJUSTMENT_RATIO,
    }
