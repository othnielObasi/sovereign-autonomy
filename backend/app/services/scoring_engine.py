from __future__ import annotations

"""Multi-objective scoring engine for completed runs.

Computes a ScoreCard with five dimensions:
  - safety        : Penalty for policy violations, near-misses, escalations
  - compliance     : Ratio of governance approvals to total decisions
  - mission_success: Did the robot reach its goal? How close?
  - efficiency     : Time efficiency relative to ideal straight-line traversal
  - smoothness     : Heading variance and speed jitter (motion quality)

Each score is 0.0–1.0 (higher = better). An overall weighted composite is provided.
"""

import json
import logging
import math
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.models import (
    Event,
    GovernanceDecisionRecord,
    Run,
    Mission,
    TelemetrySample,
)

logger = logging.getLogger("app.scoring_engine")

# Weights for composite score
WEIGHTS = {
    "safety": 0.35,
    "compliance": 0.25,
    "mission_success": 0.20,
    "efficiency": 0.10,
    "smoothness": 0.10,
}


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def compute_scorecard(db: Session, run_id: str) -> Dict[str, Any]:
    """Compute the full scorecard for a completed (or stopped) run."""

    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        return {"error": "run_not_found"}

    mission = db.query(Mission).filter(Mission.id == run.mission_id).first()
    goal = json.loads(mission.goal_json) if mission else {}
    gx, gy = float(goal.get("x", 0)), float(goal.get("y", 0))

    # --- Gather governance decisions ---
    decisions = (
        db.query(GovernanceDecisionRecord)
        .filter(GovernanceDecisionRecord.run_id == run_id)
        .order_by(GovernanceDecisionRecord.ts.asc())
        .all()
    )
    total_decisions = len(decisions)
    approved = sum(1 for d in decisions if d.decision == "APPROVED")
    denied = sum(1 for d in decisions if d.decision == "DENIED")
    needs_review = sum(1 for d in decisions if d.decision == "NEEDS_REVIEW")
    escalated = sum(1 for d in decisions if d.escalated == "true")
    risk_scores = [d.risk_score for d in decisions]
    max_risk = max(risk_scores) if risk_scores else 0.0
    avg_risk = sum(risk_scores) / len(risk_scores) if risk_scores else 0.0

    # Policy hit frequency
    policy_hits: Dict[str, int] = {}
    for d in decisions:
        for pid in json.loads(d.policy_hits or "[]"):
            policy_hits[pid] = policy_hits.get(pid, 0) + 1

    # --- Gather telemetry samples ---
    samples = (
        db.query(TelemetrySample)
        .filter(TelemetrySample.run_id == run_id)
        .order_by(TelemetrySample.ts.asc())
        .all()
    )
    positions: List[Dict[str, float]] = []
    speeds: List[float] = []
    headings: List[float] = []
    for s in samples:
        try:
            p = json.loads(s.payload_json)
            positions.append({"x": float(p.get("x", 0)), "y": float(p.get("y", 0))})
            speeds.append(float(p.get("speed", 0)))
            headings.append(float(p.get("theta", 0)))
        except Exception:
            continue

    # --- Gather events for replan/stagnation counts ---
    events = (
        db.query(Event)
        .filter(Event.run_id == run_id)
        .all()
    )
    replan_count = sum(1 for e in events if e.type == "REPLAN")
    stagnation_count = sum(1 for e in events if e.type == "STAGNATION")
    near_miss_count = 0
    for e in events:
        if e.type == "ALERT":
            try:
                payload = json.loads(e.payload_json)
                if payload.get("event") == "near_miss":
                    near_miss_count += 1
            except Exception:
                pass

    # --- SAFETY SCORE ---
    # Start at 1.0, penalize for: denials, escalations, high risk, near-misses
    safety = 1.0
    if total_decisions > 0:
        denial_ratio = (denied + needs_review) / total_decisions
        safety -= denial_ratio * 0.3
    safety -= escalated * 0.05
    safety -= near_miss_count * 0.03
    safety -= max_risk * 0.15
    safety = _clamp(safety)

    # --- COMPLIANCE SCORE ---
    # Approval rate with a penalty for escalations
    # Anti-gaming: require minimum decisions to earn compliance credit
    if total_decisions > 0:
        compliance = approved / total_decisions
        compliance -= escalated * 0.02
    else:
        compliance = 0.0  # no decisions = NOT trivially compliant (anti-gaming)
    compliance = _clamp(compliance)

    # --- MISSION SUCCESS SCORE ---
    # Based on final distance to goal
    if positions:
        last = positions[-1]
        final_dist = math.sqrt((last["x"] - gx) ** 2 + (last["y"] - gy) ** 2)
    else:
        final_dist = 999.0

    if run.status == "completed":
        mission_success = _clamp(1.0 - final_dist / 5.0)
    elif run.status == "stopped":
        mission_success = _clamp(0.5 - final_dist / 10.0)
    else:
        mission_success = _clamp(0.3 - final_dist / 20.0)

    # --- EFFICIENCY SCORE ---
    # Compare actual path length to straight-line distance
    if len(positions) >= 2:
        first = positions[0]
        straight_line = math.sqrt((gx - first["x"]) ** 2 + (gy - first["y"]) ** 2)
        actual_path = 0.0
        for i in range(1, len(positions)):
            dx = positions[i]["x"] - positions[i - 1]["x"]
            dy = positions[i]["y"] - positions[i - 1]["y"]
            actual_path += math.sqrt(dx * dx + dy * dy)
        if actual_path > 0 and straight_line > 0:
            efficiency = _clamp(straight_line / actual_path)
        else:
            efficiency = 1.0 if straight_line < 0.5 else 0.5
    else:
        efficiency = 0.0

    # Anti-gaming: penalize inactivity (few samples = robot barely moved)
    MIN_SAMPLES_FOR_FULL_EFFICIENCY = 5
    if len(positions) < MIN_SAMPLES_FOR_FULL_EFFICIENCY and total_decisions > 0:
        inactivity_ratio = len(positions) / MIN_SAMPLES_FOR_FULL_EFFICIENCY
        efficiency *= inactivity_ratio

    # Penalize replans and stagnation
    efficiency -= replan_count * 0.05
    efficiency -= stagnation_count * 0.03
    efficiency = _clamp(efficiency)

    # --- SMOOTHNESS SCORE ---
    # Heading variance + speed jitter
    smoothness = 1.0
    if len(headings) >= 3:
        heading_diffs = []
        for i in range(1, len(headings)):
            d = abs(math.atan2(
                math.sin(headings[i] - headings[i - 1]),
                math.cos(headings[i] - headings[i - 1]),
            ))
            heading_diffs.append(d)
        avg_heading_change = sum(heading_diffs) / len(heading_diffs)
        # Penalize large average heading changes (>0.5 rad/tick is very jerky)
        smoothness -= _clamp(avg_heading_change / 0.5) * 0.5

    if len(speeds) >= 3:
        speed_diffs = [abs(speeds[i] - speeds[i - 1]) for i in range(1, len(speeds))]
        avg_speed_jitter = sum(speed_diffs) / len(speed_diffs)
        # Penalize large speed changes (>0.3 m/s per tick = jerky)
        smoothness -= _clamp(avg_speed_jitter / 0.3) * 0.5

    smoothness = _clamp(smoothness)

    # --- COMPOSITE ---
    composite = sum(WEIGHTS[k] * v for k, v in {
        "safety": safety,
        "compliance": compliance,
        "mission_success": mission_success,
        "efficiency": efficiency,
        "smoothness": smoothness,
    }.items())
    composite = _clamp(composite)

    return {
        "run_id": run_id,
        "run_status": run.status,
        "scores": {
            "safety": round(safety, 3),
            "compliance": round(compliance, 3),
            "mission_success": round(mission_success, 3),
            "efficiency": round(efficiency, 3),
            "smoothness": round(smoothness, 3),
            "composite": round(composite, 3),
        },
        "weights": WEIGHTS,
        "metrics": {
            "total_decisions": total_decisions,
            "approved": approved,
            "denied": denied,
            "needs_review": needs_review,
            "escalated": escalated,
            "replan_count": replan_count,
            "stagnation_count": stagnation_count,
            "near_miss_count": near_miss_count,
            "avg_risk_score": round(avg_risk, 3),
            "max_risk_score": round(max_risk, 3),
            "policy_hit_counts": policy_hits,
            "telemetry_samples": len(positions),
            "final_distance_to_goal": round(final_dist, 2),
        },
    }
