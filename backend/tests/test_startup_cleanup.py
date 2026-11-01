from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.db.models import Mission, Run
from app.db.session import SessionLocal
from app.main import app
from app.utils.time import utc_now


def test_startup_marks_stale_runs_and_missions_failed():
    mission_id = "mis_startup_cleanup"
    run_id = "run_startup_cleanup"

    db = SessionLocal()
    try:
        existing_run = db.query(Run).filter(Run.id == run_id).first()
        if existing_run:
            db.delete(existing_run)
        existing_mission = db.query(Mission).filter(Mission.id == mission_id).first()
        if existing_mission:
            db.delete(existing_mission)
        db.commit()

        mission = Mission(
            id=mission_id,
            title="Startup Cleanup",
            goal_json=json.dumps({"x": 1, "y": 1}),
            status="executing",
            created_at=utc_now(),
            updated_at=None,
        )
        run = Run(
            id=run_id,
            mission_id=mission_id,
            status="planning",
            started_at=utc_now(),
            ended_at=None,
            policy_version=None,
            planning_mode="fallback",
        )
        db.add(mission)
        db.add(run)
        db.commit()
    finally:
        db.close()

    with TestClient(app):
        pass

    db = SessionLocal()
    try:
        cleaned_run = db.query(Run).filter(Run.id == run_id).first()
        cleaned_mission = db.query(Mission).filter(Mission.id == mission_id).first()

        assert cleaned_run is not None
        assert cleaned_run.status == "failed"
        assert cleaned_run.ended_at is not None

        assert cleaned_mission is not None
        assert cleaned_mission.status == "failed"

        db.delete(cleaned_run)
        db.delete(cleaned_mission)
        db.commit()
    finally:
        db.close()