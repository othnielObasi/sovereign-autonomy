from __future__ import annotations

import yaml
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import Any, Dict, List, Optional

from app.schemas.governance import (
    PolicyInfo, ActionProposal, GovernanceDecision,
    GovernanceDecisionOut, GovernanceReceiptOut, GovernanceStatsOut,
)
from app.policies.rules_python import evaluate_policies
from app.db.session import SessionLocal
from app.deps import get_db
from app.services.governance_engine import GovernanceEngine

router = APIRouter()

# Shared engine instance — will be replaced by run_service's engine at startup
_gov_engine = GovernanceEngine()


@router.get("/policies", response_model=list[PolicyInfo])
def list_policies():
    import pathlib
    catalog_path = pathlib.Path(__file__).resolve().parent.parent / "policies" / "policy_catalog.yaml"
    with open(catalog_path, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    policies = doc.get("policies", [])
    return [
        PolicyInfo(
            policy_id=p["policy_id"],
            name=p["name"],
            description=p["description"],
            severity=p.get("severity", "MEDIUM"),
            parameters=p.get("parameters"),
            trigger=p.get("trigger"),
            action=p.get("action"),
        )
        for p in policies
    ]


@router.post("/policies/test", response_model=GovernanceDecision)
def test_policy(payload: Dict[str, Any]):
    """Test an action proposal against policies without running a full mission."""
    telemetry = payload.get("telemetry") or {}
    proposal_raw = payload.get("proposal") or {}
    proposal = ActionProposal(**proposal_raw)
    return evaluate_policies(telemetry, proposal)


@router.post("/governance/evaluate", response_model=GovernanceDecision)
def governance_evaluate(payload: Dict[str, Any]):
    """Evaluate an AI-generated action against the governance policy layer.

    Every AI-planned action is intercepted here before execution.
    """
    telemetry = payload.get("telemetry") or {}
    proposal_raw = payload.get("proposal") or {}
    proposal = ActionProposal(**proposal_raw)
    return evaluate_policies(telemetry, proposal)


@router.get("/governance/decisions/{run_id}", response_model=List[GovernanceDecisionOut])
def get_governance_decisions(
    run_id: str,
    decision: Optional[str] = Query(None, description="Filter: APPROVED|DENIED|NEEDS_REVIEW"),
    policy_state: Optional[str] = Query(None, description="Filter: SAFE|SLOW|STOP|REPLAN"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Query governance decision history for a run.

    Returns all persisted governance decisions with filters for
    decision type and policy state. Ordered by most recent first.
    """
    db = SessionLocal()
    try:
        rows = _gov_engine.get_decisions(
            db, run_id,
            decision_filter=decision,
            policy_state_filter=policy_state,
            limit=limit,
            offset=offset,
        )
        return rows
    finally:
        db.close()


@router.get("/governance/decisions/{run_id}/stats", response_model=GovernanceStatsOut)
def get_governance_stats(run_id: str):
    """Get aggregate governance statistics for a run.

    Returns counts of decisions by type, policy hit frequency,
    risk score distribution, and escalation count.
    """
    db = SessionLocal()
    try:
        return _gov_engine.get_decision_stats(db, run_id)
    finally:
        db.close()


@router.get("/governance/receipts/{run_id}")
def get_governance_receipts(
    run_id: str,
    limit: int = Query(100, ge=1, le=1000),
):
    """Get governance receipts for a run.

    A receipt is structured proof of why each action was allowed or blocked,
    including the verdict, proposal, policy evaluation, context snapshot,
    and integrity hash linking to the chain-of-trust.
    """
    db = SessionLocal()
    try:
        return _gov_engine.get_receipts(db, run_id, limit=limit)
    finally:
        db.close()


@router.get("/governance/receipts/{run_id}/{decision_id}")
def get_governance_receipt(run_id: str, decision_id: int):
    """Get a single governance receipt by decision ID."""
    db = SessionLocal()
    try:
        receipt = _gov_engine.get_receipt(db, run_id, decision_id)
        if not receipt:
            raise HTTPException(status_code=404, detail="Decision not found")
        return receipt
    finally:
        db.close()


@router.get("/governance/receipts/{run_id}/{decision_id}/verify")
def verify_governance_receipt(run_id: str, decision_id: int, db: Session = Depends(get_db)):
    """Verify a receipt's Ed25519 signature against the stored decision content."""
    result = _gov_engine.verify_receipt(db, run_id, decision_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    return result


@router.get("/governance/signing-key")
def get_signing_key():
    """Public key that signs governance receipts on this deployment, for independent verification."""
    from app.utils.signing import public_key_info

    return public_key_info()


@router.get("/policies/version")
def get_policy_version():
    """Return the current policy version hash and all active parameters.

    The hash changes whenever any policy parameter is modified, enabling
    traceability of which policy configuration was active for each decision.
    """
    from app.policies.versioning import policy_version_info

    return policy_version_info()


# ── Governance-bounded optimizer (#7) ──

@router.get("/optimizer/envelope")
def get_optimization_envelope():
    """Return the governance envelope — hard safety bounds the optimizer respects."""
    from app.services.optimizer import get_optimization_envelope

    return get_optimization_envelope()


@router.get("/optimizer/analyze/{run_id}")
def analyze_run_optimization(run_id: str):
    """Analyse a run and produce governance-bounded optimization recommendations."""
    from app.services.optimizer import analyze_run_performance

    db = SessionLocal()
    try:
        return analyze_run_performance(db, run_id)
    finally:
        db.close()


# ── Adaptive tuning (#12, #13) ──

@router.get("/tuning/recommendations")
def get_tuning_recommendations():
    """Analyse historical runs and produce safe parameter tuning recommendations."""
    from app.services.adaptive_tuning import compute_tuning_recommendations

    db = SessionLocal()
    try:
        return compute_tuning_recommendations(db)
    finally:
        db.close()


# ── Anti-reward-hacking integrity monitor (#15) ──

@router.get("/integrity/run/{run_id}")
def check_run_integrity(run_id: str):
    """Check a run's scorecard for reward-hacking indicators."""
    from app.services.integrity_monitor import check_run_integrity

    db = SessionLocal()
    try:
        return check_run_integrity(db, run_id)
    finally:
        db.close()


@router.get("/integrity/cross-run")
def check_cross_run_integrity(limit: int = Query(10, ge=3, le=50)):
    """Analyse trends across multiple runs for systemic gaming patterns."""
    from app.services.integrity_monitor import check_cross_run_integrity

    db = SessionLocal()
    try:
        return check_cross_run_integrity(db, limit=limit)
    finally:
        db.close()


# ── Persistent agent memory (#17, #18) ──

@router.get("/agent/memory")
def get_agent_memory(
    category: Optional[str] = Query(None, description="Filter: decision|denial|learning|strategy"),
    limit: int = Query(30, ge=1, le=200),
):
    """Retrieve persistent agent memory entries."""
    from app.services.persistent_memory import PersistentMemory

    db = SessionLocal()
    try:
        mem = PersistentMemory()
        return mem.recall(db, category=category, limit=limit)
    finally:
        db.close()


@router.get("/agent/memory/stats")
def get_agent_memory_stats():
    """Get agent memory statistics."""
    from app.services.persistent_memory import PersistentMemory

    db = SessionLocal()
    try:
        mem = PersistentMemory()
        return mem.stats(db) if hasattr(mem, 'stats') else mem.get_stats(db)
    finally:
        db.close()


@router.post("/agent/memory/learn/{run_id}")
def extract_lessons(run_id: str):
    """Extract internalized lessons from a completed run (#18)."""
    from app.services.persistent_memory import PersistentMemory

    db = SessionLocal()
    try:
        mem = PersistentMemory()
        lessons = mem.extract_lessons_from_run(db, run_id)
        db.commit()
        return {"run_id": run_id, "lessons_extracted": len(lessons), "lessons": lessons}
    finally:
        db.close()


# ── Policy hard-failure classification (#14) ──

@router.get("/policies/classification")
def get_policy_classification():
    """Return the hard-fail vs soft-fail classification of all policies."""
    from app.policies.rules_python import HARD_FAIL_POLICIES, SOFT_FAIL_POLICIES

    return {
        "hard_fail": sorted(HARD_FAIL_POLICIES),
        "soft_fail": sorted(SOFT_FAIL_POLICIES),
        "description": {
            "hard_fail": "Immediate DENIED, no operator override possible",
            "soft_fail": "Can be DENIED or upgraded to NEEDS_REVIEW for operator decision",
        },
    }


# ── Policy version history (#16) ──

@router.get("/policies/versions")
def list_policy_versions(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Return policy version history — every distinct config ever active."""
    from app.db.models import PolicyVersion

    rows = (
        db.query(PolicyVersion)
        .order_by(PolicyVersion.created_at.desc())
        .limit(limit)
        .all()
    )
    import json as _json
    return [
        {
            "id": r.id,
            "version_hash": r.version_hash,
            "parameters": _json.loads(r.parameters_json) if r.parameters_json else {},
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "description": r.description,
        }
        for r in rows
    ]


# ── Post-run safety report (#14) ──

@router.get("/runs/{run_id}/safety-report")
def get_safety_report(run_id: str, db: Session = Depends(get_db)):
    """Get safety validation report for a completed run."""
    from app.db.models import Run
    import json as _json

    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "run_id": run_id,
        "safety_verdict": run.safety_verdict,
        "safety_report": _json.loads(run.safety_report_json) if run.safety_report_json else None,
        "policy_version": run.policy_version,
        "planning_mode": run.planning_mode,
    }


# ── Adversarial + holdout validation (#15) ──

@router.get("/adversarial/validate")
def adversarial_validate():
    """Run the full adversarial + holdout validation suite."""
    from app.services.adversarial_validator import run_full_validation

    return run_full_validation()


@router.get("/adversarial/adversarial")
def adversarial_suite():
    """Run only the adversarial scenario suite."""
    from app.services.adversarial_validator import run_adversarial_suite

    return run_adversarial_suite()


@router.get("/adversarial/holdout")
def holdout_suite():
    """Run only the holdout scenario suite."""
    from app.services.adversarial_validator import run_holdout_suite

    return run_holdout_suite()


# ── Semantic memory search (#17) ──

@router.get("/agent/memory/search")
def search_agent_memory(
    query: str = Query(..., min_length=1, max_length=500, description="Search query"),
    category: Optional[str] = Query(None, description="Filter: decision|denial|learning|strategy"),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Semantic similarity search across agent memory entries."""
    from app.services.persistent_memory import PersistentMemory

    mem = PersistentMemory()
    return mem.recall_similar(db, query=query, category=category, limit=limit)


# ── Cross-run learning aggregation (#18) ──

@router.get("/agent/cross-run-learning")
def get_cross_run_learning(
    limit: int = Query(20, ge=3, le=100),
    db: Session = Depends(get_db),
):
    """Get cross-run learning aggregation: trends, patterns, baselines."""
    from app.services.cross_run_learning import aggregate_cross_run_lessons

    return aggregate_cross_run_lessons(db, limit=limit)


# ── Planner learning loop: spatial lessons from gate decisions ──

@router.get("/agent/lessons")
def get_planner_lessons(
    all_versions: bool = Query(False, description="Include lessons learned under older policy versions"),
    db: Session = Depends(get_db),
):
    """Lessons the planner has learned from the gate's past decisions.

    Only lessons learned under the active policy version are fed to the planner.
    """
    from app.policies.versioning import policy_version_hash
    from app.services.planner_lessons import all_lessons

    lessons = all_lessons(db, current_version_only=not all_versions)
    return {"policy_version": policy_version_hash(), "count": len(lessons), "lessons": lessons}


@router.get("/agent/lessons/route")
def get_lessons_for_route(
    sx: float = Query(..., description="Start x (m)"),
    sy: float = Query(..., description="Start y (m)"),
    gx: Optional[float] = Query(None, description="Goal x (m)"),
    gy: Optional[float] = Query(None, description="Goal y (m)"),
    limit: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
):
    """Preview the lessons the planner would receive for a route."""
    from app.services.planner_lessons import format_for_prompt, lessons_for_route

    goal = {"x": gx, "y": gy} if gx is not None and gy is not None else None
    lessons = lessons_for_route(db, {"x": sx, "y": sy}, goal, limit=limit)
    return {"lessons": lessons, "prompt_block": format_for_prompt(lessons)}


# ── Score trends across runs (#10) ──

@router.get("/analytics/score-trends")
def get_score_trends(
    limit: int = Query(20, ge=3, le=100),
    db: Session = Depends(get_db),
):
    """Get score trends across recent runs for dashboard charts."""
    from app.services.scoring_engine import compute_scorecard
    from app.db.models import Run

    try:
        runs = (
            db.query(Run)
            .filter(Run.status.in_(["completed", "failed_safety", "stopped"]))
            .order_by(Run.started_at.desc())
            .limit(limit)
            .all()
        )
        trends = []
        for r in reversed(runs):  # chronological order
            try:
                scores = compute_scorecard(db, r.id)
                trends.append({
                    "run_id": r.id,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "status": r.status,
                    "safety_score": scores.get("safety_score"),
                    "compliance_score": scores.get("compliance_score"),
                    "efficiency_score": scores.get("efficiency_score"),
                    "overall_score": scores.get("overall_score"),
                })
            except Exception:
                pass
        return {"count": len(trends), "trends": trends}
    except Exception:
        return {"count": 0, "trends": []}


# ── LLM divergence explanation (#20) ──

@router.post("/runs/{run_id}/divergence-explanation")
def generate_divergence_explanation(run_id: str, db: Session = Depends(get_db)):
    """Generate LLM-powered natural language explanation of plan vs execution divergence."""
    import json as _json
    from app.db.models import Run, Event

    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # Get plan events
    plan_events = (
        db.query(Event)
        .filter(Event.run_id == run_id, Event.type == "PLAN")
        .order_by(Event.ts.asc())
        .all()
    )
    planned_waypoints = []
    for pe in plan_events:
        payload = _json.loads(pe.payload_json)
        wps = (payload.get("plan") or {}).get("waypoints") or []
        planned_waypoints.extend(wps)

    # Get execution events
    exec_events = (
        db.query(Event)
        .filter(Event.run_id == run_id, Event.type == "EXECUTION")
        .order_by(Event.ts.asc())
        .all()
    )
    executed_commands = []
    for ee in exec_events:
        payload = _json.loads(ee.payload_json)
        cmd = payload.get("command", {})
        executed_commands.append(cmd)

    # Get denial events
    denial_events = (
        db.query(Event)
        .filter(Event.run_id == run_id, Event.type == "DECISION")
        .order_by(Event.ts.asc())
        .all()
    )
    denials = []
    for de in denial_events:
        payload = _json.loads(de.payload_json)
        gov = payload.get("governance", {})
        if gov.get("decision") != "APPROVED":
            denials.append({
                "decision": gov.get("decision"),
                "policies": gov.get("policy_hits", []),
                "reasons": gov.get("reasons", []),
            })

    # Get replan events
    replan_events = (
        db.query(Event)
        .filter(Event.run_id == run_id, Event.type == "REPLAN")
        .order_by(Event.ts.asc())
        .all()
    )
    replans = []
    for re_evt in replan_events:
        payload = _json.loads(re_evt.payload_json)
        replans.append(payload)

    # Build explanation without LLM (deterministic, no external dependency)
    explanation_parts = []

    if not planned_waypoints:
        explanation_parts.append("No LLM plan was generated for this run — the fallback planner was used exclusively.")
    else:
        explanation_parts.append(f"The LLM plan contained {len(planned_waypoints)} waypoints.")

    if denials:
        policy_counts: dict = {}
        for d in denials:
            for p in d.get("policies", []):
                policy_counts[p] = policy_counts.get(p, 0) + 1
        top_policies = sorted(policy_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        explanation_parts.append(
            f"{len(denials)} actions were denied. Top blocking policies: "
            + ", ".join(f"{p} ({c}x)" for p, c in top_policies) + "."
        )
    else:
        explanation_parts.append("All proposed actions were approved — no governance denials occurred.")

    if replans:
        explanation_parts.append(
            f"{len(replans)} replanning events occurred, triggered by consecutive denials "
            "forcing the agent to find alternative routes."
        )

    exec_count = len(executed_commands)
    plan_count = len(planned_waypoints)
    if plan_count > 0 and exec_count > 0:
        ratio = exec_count / plan_count
        if ratio > 1.5:
            explanation_parts.append(
                f"The robot executed {exec_count} commands for {plan_count} planned waypoints, "
                "indicating significant path adaptation beyond the original plan."
            )
        elif ratio < 0.5:
            explanation_parts.append(
                f"Only {exec_count} of {plan_count} planned waypoints were executed, "
                "suggesting the run was stopped early or the plan was too ambitious."
            )
        else:
            explanation_parts.append(
                f"Execution followed the plan closely ({exec_count} commands for {plan_count} waypoints)."
            )

    return {
        "run_id": run_id,
        "planned_waypoints": len(planned_waypoints),
        "executed_commands": exec_count,
        "denials": len(denials),
        "replans": len(replans),
        "explanation": " ".join(explanation_parts),
    }


# ── Executed path for run (#3) ──

@router.get("/runs/{run_id}/executed-path")
def get_executed_path(run_id: str, db: Session = Depends(get_db)):
    """Get the actual executed positions for a completed/running run."""
    import json as _json
    from app.db.models import Run, Event, TelemetrySample

    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # Build executed path from telemetry samples
    samples = (
        db.query(TelemetrySample)
        .filter(TelemetrySample.run_id == run_id)
        .order_by(TelemetrySample.ts.asc())
        .all()
    )
    path = []
    prev_x, prev_y = None, None
    for s in samples:
        try:
            payload = _json.loads(s.payload_json)
            x = float(payload.get("x", 0))
            y = float(payload.get("y", 0))
            # Downsample: only include points that moved > 0.1m
            if prev_x is not None:
                d = ((x - prev_x) ** 2 + (y - prev_y) ** 2) ** 0.5
                if d < 0.1:
                    continue
            path.append({
                "x": round(x, 3),
                "y": round(y, 3),
                "speed": round(float(payload.get("speed", 0)), 3),
                "ts": s.ts.isoformat() if s.ts else None,
            })
            prev_x, prev_y = x, y
        except Exception:
            continue

    # Also get planned waypoints for comparison
    plan_event = (
        db.query(Event)
        .filter(Event.run_id == run_id, Event.type == "PLAN")
        .order_by(Event.ts.desc())
        .first()
    )
    planned = []
    if plan_event:
        try:
            payload = _json.loads(plan_event.payload_json)
            planned = (payload.get("plan") or {}).get("waypoints") or []
        except Exception:
            pass

    return {
        "run_id": run_id,
        "executed_path": path,
        "planned_waypoints": planned,
        "executed_count": len(path),
        "planned_count": len(planned),
    }
