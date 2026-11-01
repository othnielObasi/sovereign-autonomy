"""Resume after an interruption: kill switches block it, uncertain moves are settled
with the controller first, and the plan continues from the last confirmed waypoint."""
from __future__ import annotations

import asyncio
import json
import os

import pytest

from app.autonomy.core import Action, Rejected
from conftest import _TestSession

SECRET = os.environ["PERMIT_SECRET"]
PLAN = [{"x": 6.0, "y": 3.5, "max_speed": 0.4}, {"x": 9.0, "y": 3.5, "max_speed": 0.4},
        {"x": 12.0, "y": 3.5, "max_speed": 0.4}, {"x": 12.0, "y": 8.0, "max_speed": 0.3}]


class Sim:
    def __init__(self, target=None):
        self.target = target

    async def get_telemetry(self):
        return {"x": 8.0, "y": 3.5, "speed": 0.0, "target": self.target}


@pytest.fixture
def setup(monkeypatch, tmp_path):
    import app.services.execution_authority as ea
    from app.db.models import Event, Mission, Run
    from app.services.run_service import RunService
    from app.utils.time import utc_now

    authority = ea.ExecutionAuthority(secret=SECRET, db_path=str(tmp_path / "resume.db"))
    monkeypatch.setattr(ea, "_authority", authority)
    import app.services.run_service as rs
    monkeypatch.setattr(rs, "SessionLocal", _TestSession, raising=False)
    svc = RunService()
    monkeypatch.setattr(svc, "_launch_loop", lambda run_id: None)   # no background loop in this test

    db = _TestSession()
    db.add(Mission(id="mis_resume", title="Resume", goal_json=json.dumps({"x": 12, "y": 8}), status="paused",
                   created_at=utc_now()))
    db.add(Run(id="run_resume", mission_id="mis_resume", status="paused", started_at=utc_now(),
               planning_mode="fallback"))
    db.commit()
    svc._append_event(db, "run_resume", "PLAN", {"plan": {"waypoints": PLAN}})
    # Waypoints 1 and 2 were sent and acknowledged; the robot was heading to waypoint 2 (9, 3.5)
    for wp in PLAN[:2]:
        svc._append_event(db, "run_resume", "EXECUTION", {"command": {"intent": "MOVE_TO", "params": wp},
                                                          "result": {"ok": True}})
    db.commit()
    yield svc, authority, db
    db.query(Event).filter(Event.run_id == "run_resume").delete()
    db.query(Run).filter(Run.id == "run_resume").delete()
    db.query(Mission).filter(Mission.id == "mis_resume").delete()
    db.commit()
    db.close()


def test_resume_continues_from_the_last_confirmed_waypoint(setup):
    svc, authority, db = setup
    svc.sim = Sim()
    result = asyncio.run(svc.resume_run(db, "run_resume"))
    assert result["waypoints_remaining"] == 3
    assert svc._plans["run_resume"][0] == PLAN[1]       # heads on to (9, 3.5), not back to the start


def test_resume_refused_while_a_kill_switch_is_active(setup):
    svc, authority, db = setup
    svc.sim = Sim()
    authority.kills.activate("mission", "mis_resume")
    with pytest.raises(Rejected, match="kill"):
        asyncio.run(svc.resume_run(db, "run_resume"))
    from app.db.models import Run
    assert db.query(Run).filter(Run.id == "run_resume").one().status == "paused"


def test_resume_settles_a_lost_answer_before_moving(setup):
    svc, authority, db = setup
    lost = Action("robot-1", "mis_resume", "run_resume:9:1", "MOVE_TO", {"x": 9.0, "y": 3.5, "max_speed": 0.4}, 1, "v")
    authority.checkpoints.begin_action(lost)
    svc.sim = Sim(target={"x": 9.0, "y": 3.5, "max_speed": 0.4})   # the controller did take it
    result = asyncio.run(svc.resume_run(db, "run_resume"))
    assert result["reconciled"] == [{"action_id": lost.action_id, "executed": True}]
    assert authority.checkpoints.in_doubt("mis_resume") == []


def test_resume_refused_when_the_controller_cannot_be_asked(setup):
    svc, authority, db = setup
    authority.checkpoints.begin_action(Action("robot-1", "mis_resume", "a-x", "MOVE_TO", {"x": 9, "y": 3.5}, 1, "v"))

    class Down:
        async def get_telemetry(self):
            raise ConnectionError("down")

    svc.sim = Down()
    with pytest.raises(Rejected, match="cannot_reconcile"):
        asyncio.run(svc.resume_run(db, "run_resume"))
