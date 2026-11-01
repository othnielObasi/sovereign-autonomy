"""Cross-run learning aggregation (#18 completion).

Analyses patterns across multiple completed runs to produce generalized
strategies and parameter recommendations. Builds on persistent_memory.py.
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.db.models import Run, AgentMemoryEntry, GovernanceDecisionRecord
from app.services.scoring_engine import compute_scorecard
from app.services.persistent_memory import PersistentMemory

logger = logging.getLogger("app.cross_run_learning")


def aggregate_cross_run_lessons(db: Session, limit: int = 20) -> Dict[str, Any]:
    """Aggregate lessons learned across multiple completed runs.

    Analyses denial patterns, successful strategies, and score trends
    to produce generalized guidance for future runs.
    """
    runs = (
        db.query(Run)
        .filter(Run.status.in_(["completed", "stopped"]))
        .order_by(Run.ended_at.desc())
        .limit(limit)
        .all()
    )

    if len(runs) < 2:
        return {"status": "insufficient_data", "message": "Need at least 2 completed runs"}

    # Compute scorecards for all runs
    scorecards = []
    for r in runs:
        sc = compute_scorecard(db, r.id)
        if "error" not in sc:
            scorecards.append(sc)

    if len(scorecards) < 2:
        return {"status": "insufficient_data", "message": "Not enough valid scorecards"}

    # Aggregate scores
    dimensions = ["safety", "compliance", "mission_success", "efficiency", "smoothness"]
    score_trends: Dict[str, List[float]] = {d: [] for d in dimensions}
    for sc in scorecards:
        for d in dimensions:
            score_trends[d].append(sc["scores"].get(d, 0.0))

    averages = {d: round(sum(v) / len(v), 3) for d, v in score_trends.items()}
    stdevs = {}
    for d, values in score_trends.items():
        mean = averages[d]
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        stdevs[d] = round(math.sqrt(variance), 3)

    # Identify improving/degrading trends
    trends: Dict[str, str] = {}
    for d in dimensions:
        vals = score_trends[d]
        if len(vals) >= 3:
            recent = sum(vals[:len(vals)//2]) / max(len(vals)//2, 1)
            older = sum(vals[len(vals)//2:]) / max(len(vals) - len(vals)//2, 1)
            diff = recent - older
            if diff > 0.05:
                trends[d] = "improving"
            elif diff < -0.05:
                trends[d] = "degrading"
            else:
                trends[d] = "stable"
        else:
            trends[d] = "insufficient_data"

    # Aggregate denial patterns across runs
    denial_patterns: Dict[str, int] = {}
    total_denials = 0
    total_decisions = 0
    for sc in scorecards:
        metrics = sc.get("metrics", {})
        total_denials += metrics.get("denied", 0) + metrics.get("needs_review", 0)
        total_decisions += metrics.get("total_decisions", 0)
        for policy, count in metrics.get("policy_hit_counts", {}).items():
            denial_patterns[policy] = denial_patterns.get(policy, 0) + count

    # Speed analysis from approved decisions
    successful_speeds: List[float] = []
    recent_decisions = (
        db.query(GovernanceDecisionRecord)
        .filter(
            GovernanceDecisionRecord.decision == "APPROVED",
            GovernanceDecisionRecord.proposal_intent == "MOVE_TO",
        )
        .order_by(GovernanceDecisionRecord.ts.desc())
        .limit(200)
        .all()
    )
    for d in recent_decisions:
        try:
            proposal = json.loads(d.proposal_json or "{}")
            s = float(proposal.get("max_speed", 0))
            if 0 < s < 2.0:
                successful_speeds.append(s)
        except Exception:
            continue

    speed_baseline = None
    if successful_speeds:
        speed_baseline = {
            "mean": round(sum(successful_speeds) / len(successful_speeds), 3),
            "min": round(min(successful_speeds), 3),
            "max": round(max(successful_speeds), 3),
            "p25": round(sorted(successful_speeds)[len(successful_speeds)//4], 3),
            "p75": round(sorted(successful_speeds)[3*len(successful_speeds)//4], 3),
            "samples": len(successful_speeds),
        }

    # Generate generalized lessons
    lessons: List[str] = []
    mem = PersistentMemory()

    if total_decisions > 0 and total_denials / total_decisions > 0.3:
        top_policy = max(denial_patterns, key=denial_patterns.get) if denial_patterns else "unknown"
        lesson = (
            f"Cross-run analysis ({len(runs)} runs): {total_denials}/{total_decisions} "
            f"({100*total_denials/total_decisions:.0f}%) denials, primarily from {top_policy}. "
            f"Recommend tighter pre-planning around {top_policy} constraints."
        )
        lessons.append(lesson)
        mem.store_learning(db, f"cross_run_{len(runs)}", lesson)

    if speed_baseline and speed_baseline["mean"] < 0.3:
        lesson = f"System-wide speed baseline is low ({speed_baseline['mean']:.2f} m/s). Efficiency may be improvable if safety margins allow."
        lessons.append(lesson)
        mem.store_learning(db, f"cross_run_{len(runs)}", lesson)

    for d in dimensions:
        if trends.get(d) == "degrading":
            lesson = f"{d.capitalize()} score is degrading across recent runs (avg: {averages[d]:.3f}, trend: {trends[d]}). Investigate root cause."
            lessons.append(lesson)
            mem.store_learning(db, f"cross_run_{len(runs)}", lesson)

    # Anti-poisoning: detect slow baseline drift ("boiling frog" attack)
    # If ALL dimensions are slowly declining, someone may be poisoning the learning.
    declining_count = sum(1 for d in dimensions if trends.get(d) == "degrading")
    if declining_count >= 3:
        lesson = (
            f"WARNING: {declining_count}/{len(dimensions)} dimensions declining simultaneously. "
            f"Possible baseline poisoning — recommend freezing adaptive tuning and manual audit."
        )
        lessons.append(lesson)
        mem.store_learning(db, f"cross_run_{len(runs)}", lesson)
        logger.warning("Cross-run poisoning alert: %d dimensions declining for %d runs", declining_count, len(runs))

    # Anti-poisoning: flag if recent composite is significantly below historical
    composites = [sc.get("scores", {}).get("composite", 0) for sc in scorecards]
    if len(composites) >= 6:
        recent_comp = sum(composites[:3]) / 3
        older_comp = sum(composites[3:6]) / 3
        if recent_comp < older_comp - 0.15:
            lesson = (
                f"Composite score dropped significantly: recent {recent_comp:.3f} vs historical {older_comp:.3f}. "
                f"Review recent parameter changes for possible gaming-induced drift."
            )
            lessons.append(lesson)
            mem.store_learning(db, f"cross_run_{len(runs)}", lesson)

    # Store successful strategy if safety is consistently high
    if averages.get("safety", 0) > 0.85 and stdevs.get("safety", 1) < 0.1:
        strategy = {
            "type": "proven_safe_baseline",
            "avg_safety": averages["safety"],
            "speed_baseline": speed_baseline,
            "sample_runs": len(runs),
        }
        mem.store_strategy(db, f"cross_run_{len(runs)}", strategy)

    db.commit()

    return {
        "status": "ok",
        "runs_analyzed": len(runs),
        "scorecards_valid": len(scorecards),
        "averages": averages,
        "standard_deviations": stdevs,
        "trends": trends,
        "denial_patterns": dict(sorted(denial_patterns.items(), key=lambda x: -x[1])),
        "denial_rate": round(total_denials / max(total_decisions, 1), 3),
        "speed_baseline": speed_baseline,
        "lessons": lessons,
    }
