"""Operator stop: the robot is halted first, the stop is recorded even for a run
still planning, and reading a run never restarts it."""
from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from conftest import _TestSession


class _FakeSim:
    def __init__(self):
        self.commands = []

    async def send_command(self, command):
        self.commands.append(command)
        return {"ok": True}

    async def reset_robot(self):
        self.commands.append({"intent": "RESET"})
        return {"ok": True}


def _cleanup(run_id):
    """Other tests count runs in the shared test DB, so leave nothing behind."""
    from app.db.models import Event, Mission, Run
    db = _TestSession()
    try:
        db.query(Event).filter(Event.run_id == run_id).delete()
        db.query(Run).filter(Run.id == run_id).delete()
        db.query(Mission).filter(Mission.id == f"mis_{run_id}").delete()
        db.commit()
    finally:
        db.close()


def _make_run(db, run_id, status):
    from app.db.models import Mission, Run
    from app.utils.time import utc_now
    db.add(Mission(id=f"mis_{run_id}", title="Stop test", goal_json='{"x":10,"y":10}',
                   status="executing", created_at=utc_now()))
    db.add(Run(id=run_id, mission_id=f"mis_{run_id}", status=status, started_at=utc_now()))
    db.commit()


def test_stop_halts_robot_first_and_records_planning_run():
    from app.db.models import Event, Run
    from app.services.run_service import RunService

    db = _TestSession()
    try:
        _make_run(db, "run_stop_planning", "planning")
        svc = RunService()
        sim = _FakeSim()
        svc.sim = sim
        asyncio.run(svc.stop_run(db, "run_stop_planning"))

        assert sim.commands[0] == {"intent": "STOP", "params": {}}
        db.expire_all()
        assert db.query(Run).filter(Run.id == "run_stop_planning").one().status == "stopped"
        types = [e.type for e in db.query(Event).filter(Event.run_id == "run_stop_planning")]
        assert "INTERVENTION" in types
    finally:
        db.close()
        _cleanup("run_stop_planning")


def test_reading_a_running_run_does_not_restart_it():
    from app.api.routes_runs import get_run_svc
    from app.main import app

    db = _TestSession()
    try:
        _make_run(db, "run_no_autoresume", "running")
    finally:
        db.close()

    try:
        client = TestClient(app)
        r = client.get("/runs/run_no_autoresume")
        assert r.status_code == 200 and r.json()["status"] == "running"
        assert "run_no_autoresume" not in get_run_svc()._tasks
    finally:
        _cleanup("run_no_autoresume")
