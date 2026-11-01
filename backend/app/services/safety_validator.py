"""Post-run safety validation (#14).

A run FAILS safety only if something unsafe was EXECUTED: a move carried out
without an approving gate decision, or a target outside the geofence. How
often the gate intervened (hard blocks, escalations, denial streaks, low
scores) is the gate doing its job; it is reported as gate activity and
warnings, never as a failure.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.db.models import Run, Event, GovernanceDecisionRecord
from app.services.scoring_engine import compute_scorecard

logger = logging.getLogger("app.safety_validator")

# Hard thresholds — runs breaching these are marked FAILED_SAFETY
SAFETY_SCORE_MIN = 0.40         # minimum acceptable safety score
COMPLIANCE_SCORE_MIN = 0.30     # minimum acceptable compliance score
MAX_HARD_FAIL_DENIALS = 3       # maximum allowed hard-fail denials before invalid
MAX_ESCALATIONS = 10            # too many escalations = systemic issue
MAX_CONSECUTIVE_DENIALS = 10    # indicates unresolvable policy conflict


def validate_run_safety(db: Session, run_id: str) -> Dict[str, Any]:
    """Validate a run's safety post-completion.

    Returns a safety report with verdict: PASSED or FAILED_SAFETY.
    """
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        return {"verdict": "ERROR", "reason": "run_not_found"}

    # Compute scorecard
    scorecard = compute_scorecard(db, run_id)
    if "error" in scorecard:
        return {"verdict": "ERROR", "reason": scorecard["error"]}

    scores = scorecard.get("scores", {})
    metrics = scorecard.get("metrics", {})

    violations: List[Dict[str, str]] = []
    warnings: List[str] = []

    # Scores and escalations describe how often the gate stepped in: warnings only
    if scores.get("safety", 1.0) < SAFETY_SCORE_MIN:
        warnings.append(f"Safety score {scores['safety']:.3f} < {SAFETY_SCORE_MIN}: the gate intervened often")
    if scores.get("compliance", 1.0) < COMPLIANCE_SCORE_MIN:
        warnings.append(f"Compliance score {scores['compliance']:.3f} < {COMPLIANCE_SCORE_MIN}")
    escalated = metrics.get("escalated", 0)
    if escalated > MAX_ESCALATIONS:
        warnings.append(f"{escalated} escalations (> {MAX_ESCALATIONS}): planner kept proposing blocked moves")

    # Check for hard-fail policy violations
    decisions = (
        db.query(GovernanceDecisionRecord)
        .filter(GovernanceDecisionRecord.run_id == run_id)
        .all()
    )

    hard_fail_count = 0
    for d in decisions:
        hits = json.loads(d.policy_hits or "[]")
        from app.policies.rules_python import HARD_FAIL_POLICIES
        if any(p in HARD_FAIL_POLICIES for p in hits) and d.decision == "DENIED":
            hard_fail_count += 1

    if hard_fail_count > MAX_HARD_FAIL_DENIALS:
        warnings.append(f"Gate blocked {hard_fail_count} hard-policy proposals (all stopped before execution)")

    # Check for consecutive denial streaks
    max_streak = 0
    current_streak = 0
    for d in sorted(decisions, key=lambda x: x.ts if x.ts else ""):
        if d.decision in ("DENIED", "NEEDS_REVIEW"):
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 0

    if max_streak >= MAX_CONSECUTIVE_DENIALS:
        warnings.append(f"{max_streak} consecutive denials: the planner struggled to find an allowed move")

    # Every executed move must follow an APPROVED decision for that move
    events = (db.query(Event).filter(Event.run_id == run_id).order_by(Event.ts.asc(), Event.id.asc()).all())
    last_decision = None
    unapproved = 0
    for e in events:
        try:
            payload = json.loads(e.payload_json or "{}")
        except (TypeError, ValueError):
            continue
        if e.type == "DECISION":
            last_decision = payload
        elif e.type == "EXECUTION":
            cmd = payload.get("command") or {}
            if cmd.get("intent") != "MOVE_TO":
                continue
            gov = (last_decision or {}).get("governance") or {}
            prop = (last_decision or {}).get("proposal") or {}
            if gov.get("decision") != "APPROVED" or (prop.get("params") or {}) != (cmd.get("params") or {}):
                unapproved += 1
    if unapproved:
        violations.append({
            "rule": "UNAPPROVED_EXECUTION",
            "detail": f"{unapproved} move(s) executed without a matching APPROVED decision",
            "severity": "CRITICAL",
        })

    # Check for geofence breaches during execution
    geofence_exec_events = (
        db.query(Event)
        .filter(Event.run_id == run_id, Event.type == "EXECUTION")
        .all()
    )
    # If any execution happened while geofence was violated, that's critical
    for e in geofence_exec_events:
        try:
            payload = json.loads(e.payload_json)
            cmd = payload.get("command", {})
            result = payload.get("result", {})
            # Check if target was outside geofence
            from app.world_model import GEOFENCE
            params = cmd.get("params", {})
            tx, ty = float(params.get("x", 0)), float(params.get("y", 0))
            if not (GEOFENCE["min_x"] <= tx <= GEOFENCE["max_x"] and
                    GEOFENCE["min_y"] <= ty <= GEOFENCE["max_y"]):
                violations.append({
                    "rule": "GEOFENCE_BREACH_DURING_EXECUTION",
                    "detail": f"Execution targeted ({tx:.1f}, {ty:.1f}) outside geofence",
                    "severity": "CRITICAL",
                })
                break  # one is enough
        except Exception:
            continue

    # Warnings (non-blocking)
    if scores.get("efficiency", 1.0) < 0.2:
        warnings.append(f"Very low efficiency ({scores['efficiency']:.3f}) — may indicate planning issues")
    if metrics.get("stagnation_count", 0) > 5:
        warnings.append(f"High stagnation count ({metrics['stagnation_count']}) — robot may have been stuck")

    verdict = "FAILED_SAFETY" if violations else "PASSED"

    report = {
        "verdict": verdict,
        "run_id": run_id,
        "run_status": run.status,
        "scores": scores,
        "violations": violations,
        "warnings": warnings,
        "thresholds": {
            "safety_score_min": SAFETY_SCORE_MIN,
            "compliance_score_min": COMPLIANCE_SCORE_MIN,
            "max_hard_fail_denials": MAX_HARD_FAIL_DENIALS,
            "max_escalations": MAX_ESCALATIONS,
            "max_consecutive_denials": MAX_CONSECUTIVE_DENIALS,
        },
        "metrics_summary": {
            "total_decisions": metrics.get("total_decisions", 0),
            "denied": metrics.get("denied", 0),
            "hard_fail_denials": hard_fail_count,
            "unapproved_executions": unapproved,
            "escalated": escalated,
            "max_consecutive_denials": max_streak,
        },
    }

    # Persist verdict on the run
    run.safety_verdict = verdict
    run.safety_report_json = json.dumps(report)

    return report
