"""Post-run validation fails only on unsafe execution, not on gate activity."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.db.models import Event, Mission, Run
from app.services.safety_validator import validate_run_safety
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base

_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.create_all(_engine)
_TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def _run(db, rid, events):
    db.add(Mission(id=f"m-{rid}", title="t", goal_json=json.dumps({"x": 5, "y": 5}), status="completed",
                   created_at=datetime.now(timezone.utc)))
    db.add(Run(id=rid, mission_id=f"m-{rid}", status="completed", started_at=datetime.now(timezone.utc)))
    t0 = datetime.now(timezone.utc)
    for i, (etype, payload) in enumerate(events):
        db.add(Event(id=f"{rid}-{i}", run_id=rid, ts=t0 + timedelta(milliseconds=i), type=etype,
                     payload_json=json.dumps(payload), hash=f"h{i}", prev_hash="0" * 64))
    db.commit()


MOVE = {"intent": "MOVE_TO", "params": {"x": 5.0, "y": 3.5, "max_speed": 0.3}}


def test_blocked_moves_are_not_a_failure():
    db = _TestSession()
    events = []
    for _ in range(6):   # the gate blocks six unsafe proposals; robot is stopped each time
        events.append(("DECISION", {"proposal": MOVE, "governance": {"decision": "DENIED", "hard_fail": True}}))
        events.append(("EXECUTION", {"command": {"intent": "STOP", "params": {}}, "enforced_by_gate": True}))
    events.append(("DECISION", {"proposal": MOVE, "governance": {"decision": "APPROVED"}}))
    events.append(("EXECUTION", {"command": MOVE}))
    _run(db, "r-ok", events)
    rep = validate_run_safety(db, "r-ok")
    assert rep["verdict"] == "PASSED" and rep["metrics_summary"]["unapproved_executions"] == 0
    db.close()


def test_move_executed_after_denial_fails():
    db = _TestSession()
    _run(db, "r-bad", [
        ("DECISION", {"proposal": MOVE, "governance": {"decision": "DENIED"}}),
        ("EXECUTION", {"command": MOVE}),
    ])
    rep = validate_run_safety(db, "r-bad")
    assert rep["verdict"] == "FAILED_SAFETY"
    assert rep["violations"][0]["rule"] == "UNAPPROVED_EXECUTION"
    db.close()


def test_executing_different_params_than_approved_fails():
    db = _TestSession()
    _run(db, "r-swap", [
        ("DECISION", {"proposal": MOVE, "governance": {"decision": "APPROVED"}}),
        ("EXECUTION", {"command": {"intent": "MOVE_TO", "params": {"x": 5.0, "y": 3.5, "max_speed": 1.5}}}),
    ])
    assert validate_run_safety(db, "r-swap")["verdict"] == "FAILED_SAFETY"
    db.close()
