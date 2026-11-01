"""Tests for Phase D implementations: optimizer, tuning, integrity, memory, hard-fail."""

from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone

from conftest import _TestSession, _engine


@pytest.fixture
def db():
    session = _TestSession()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


_counter = 0

def _make_run(db, run_id=None, mission_id=None, status="completed"):
    global _counter
    _counter += 1
    if run_id is None:
        run_id = f"run_d_{_counter}"
    if mission_id is None:
        mission_id = f"mis_d_{_counter}"
    from app.db.models import Mission, Run
    from app.utils.time import utc_now

    m = db.query(Mission).filter(Mission.id == mission_id).first()
    if not m:
        m = Mission(id=mission_id, title="Test Mission", goal_json='{"x":10,"y":10}', status="completed", created_at=utc_now())
        db.add(m)

    r = Run(id=run_id, mission_id=mission_id, status=status, started_at=utc_now(), ended_at=utc_now() if status != "running" else None)
    db.add(r)
    db.commit()
    return r


def _make_decisions(db, run_id, n_approved=5, n_denied=2):
    from app.db.models import GovernanceDecisionRecord
    from app.utils.time import utc_now

    for i in range(n_approved):
        db.add(GovernanceDecisionRecord(
            run_id=run_id, ts=utc_now(), decision="APPROVED", policy_state="SAFE",
            risk_score=0.1, policy_hits="[]", reasons="[]", proposal_intent="MOVE_TO",
            proposal_json="{}", telemetry_summary='{"x":5,"y":5,"speed":0.3,"zone":"aisle"}',
            was_executed="true", escalated="false",
        ))
    for i in range(n_denied):
        db.add(GovernanceDecisionRecord(
            run_id=run_id, ts=utc_now(), decision="DENIED", policy_state="STOP",
            risk_score=0.9, policy_hits='["GEOFENCE_01"]', reasons='["Out of bounds"]',
            proposal_intent="MOVE_TO", proposal_json="{}",
            telemetry_summary='{"x":5,"y":5,"speed":0.3,"zone":"aisle"}',
            was_executed="false", escalated="false",
        ))
    db.commit()


# ── Optimizer Tests ──

def test_optimization_envelope():
    from app.services.optimizer import get_optimization_envelope

    envelope = get_optimization_envelope()
    assert "hard_bounds" in envelope
    assert "current_params" in envelope
    assert "governance_constraints" in envelope
    assert len(envelope["governance_constraints"]) > 0
    # Speed bounds should be positive
    for param, bounds in envelope["hard_bounds"].items():
        assert bounds["min"] < bounds["max"]


def test_analyze_run_missing(db):
    from app.services.optimizer import analyze_run_performance

    result = analyze_run_performance(db, "nonexistent_run")
    assert result.get("error") == "run_not_found"


def test_analyze_run_with_data(db):
    from app.services.optimizer import analyze_run_performance

    r = _make_run(db)
    _make_decisions(db, r.id, n_approved=8, n_denied=4)
    result = analyze_run_performance(db, r.id)
    assert "recommendations" in result
    assert result["governance_led"] is True
    assert "hard_bounds" in result


# ── Adaptive Tuning Tests ──

def test_tuning_insufficient_data(db):
    from app.services.adaptive_tuning import compute_tuning_recommendations

    result = compute_tuning_recommendations(db)
    assert result["status"] == "insufficient_data"


# ── Integrity Monitor Tests ──

def test_integrity_clean_run(db):
    from app.services.integrity_monitor import check_run_integrity

    r = _make_run(db)
    _make_decisions(db, r.id, n_approved=10, n_denied=0)
    result = check_run_integrity(db, r.id)
    assert result["run_id"] == r.id
    assert "integrity_score" in result
    assert "verdict" in result


def test_integrity_cross_run_insufficient():
    # Own empty database: the shared test DB holds finished runs from other tests
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.db.session import Base
    import app.db.models  # noqa: F401  (registers tables)
    from app.services.integrity_monitor import check_cross_run_integrity

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    try:
        _make_run(session, status="completed")
        _make_run(session, status="stopped")
        session.commit()
        result = check_cross_run_integrity(session)
        assert result["status"] == "insufficient_data"
        assert result["runs_checked"] == 2
    finally:
        session.close()


# ── Persistent Memory Tests ──

def test_persistent_memory_store_and_recall(db):
    from app.services.persistent_memory import PersistentMemory

    mem = PersistentMemory()
    mem.store_decision(
        db, "run_test1", "MOVE_TO", {"x": 5, "y": 5},
        "DENIED", ["GEOFENCE_01"], ["Out of bounds"], False,
    )
    db.commit()

    entries = mem.recall(db, category="decision")
    assert len(entries) >= 1
    assert entries[0]["content"]["decision"] == "DENIED"
    assert entries[0]["content"]["policy_hits"] == ["GEOFENCE_01"]


def test_persistent_memory_stats(db):
    from app.services.persistent_memory import PersistentMemory

    mem = PersistentMemory()
    mem.store_decision(db, "r_stat1", "MOVE_TO", {}, "APPROVED", [], [], True)
    mem.store_learning(db, "r_stat1", "Use slower speed near obstacles")
    db.commit()

    stats = mem.get_stats(db)
    assert stats["total_entries"] >= 2
    assert stats["by_category"].get("decision", 0) >= 1
    assert stats["by_category"].get("learning", 0) >= 1


def test_persistent_memory_context_string(db):
    from app.services.persistent_memory import PersistentMemory

    mem = PersistentMemory()
    mem.store_learning(db, "r1", "Avoid zone X due to high denial rate")
    db.commit()

    ctx = mem.recall_for_context(db)
    assert "Avoid zone X" in ctx


# ── Hard-Failure Mode Tests ──

def test_hard_fail_geofence():
    from app.policies.rules_python import evaluate_policies, HARD_FAIL_POLICIES
    from app.schemas.governance import ActionProposal

    # Robot outside geofence — should be hard fail
    telemetry = {"x": -5, "y": -5, "zone": "aisle", "nearest_obstacle_m": 999, "human_detected": False, "human_distance_m": 999}
    proposal = ActionProposal(intent="MOVE_TO", params={"x": 10, "y": 10, "max_speed": 0.3})
    decision = evaluate_policies(telemetry, proposal)
    assert decision.decision == "DENIED"
    assert decision.hard_fail is True
    assert "GEOFENCE_01" in decision.hard_fail_policies


def test_soft_fail_speed():
    from app.policies.rules_python import evaluate_policies
    from app.schemas.governance import ActionProposal

    # Speed too high — should be soft fail (possibly NEEDS_REVIEW at high risk)
    telemetry = {"x": 5, "y": 5, "zone": "loading", "nearest_obstacle_m": 999,
                 "human_detected": False, "human_distance_m": 999}
    proposal = ActionProposal(intent="MOVE_TO", params={"x": 10, "y": 10, "max_speed": 1.0})
    decision = evaluate_policies(telemetry, proposal)
    assert decision.decision in ("DENIED", "NEEDS_REVIEW")
    assert decision.hard_fail is False


def test_approved_no_hard_fail():
    from app.policies.rules_python import evaluate_policies
    from app.schemas.governance import ActionProposal

    telemetry = {"x": 5, "y": 5, "zone": "aisle", "nearest_obstacle_m": 999,
                 "human_detected": False, "human_distance_m": 999}
    proposal = ActionProposal(intent="MOVE_TO", params={"x": 10, "y": 10, "max_speed": 0.3})
    decision = evaluate_policies(telemetry, proposal)
    assert decision.decision == "APPROVED"
    assert decision.hard_fail is False
    assert decision.hard_fail_policies == []


def test_hard_fail_human_stop_radius():
    from app.policies.rules_python import evaluate_policies
    from app.schemas.governance import ActionProposal

    # Human within stop radius — should be hard fail
    telemetry = {"x": 5, "y": 5, "zone": "aisle", "nearest_obstacle_m": 999,
                 "human_detected": True, "human_conf": 0.9, "human_distance_m": 0.5}
    proposal = ActionProposal(intent="MOVE_TO", params={"x": 10, "y": 10, "max_speed": 0.3})
    decision = evaluate_policies(telemetry, proposal)
    assert decision.decision == "DENIED"
    assert decision.hard_fail is True
