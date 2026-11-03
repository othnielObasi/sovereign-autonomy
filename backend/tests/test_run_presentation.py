"""Presentation must retain milestones and report the actual current rules."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import Event, Mission, Run
from app.db.session import Base
from app.deps import get_db
from app.main import app
from app.policies import params as P
from app.services.run_presentation import run_presentation


@pytest.fixture
def db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def seed(db):
    now = datetime.now(timezone.utc)
    db.add(Mission(id='presentation-mission', title='Navigation', goal_json='{}', created_at=now))
    db.add(Run(id='presentation-run', mission_id='presentation-mission', status='running', started_at=now))
    def event(n, kind, payload):
        db.add(Event(id=f'presentation-{n}', run_id='presentation-run', ts=now + timedelta(seconds=n),
                     type=kind, payload_json=json.dumps(payload), hash='test-only', prev_hash='test-only'))
    event(-1, 'AUTHORITY', {'event': 'controller_refused', 'reason': 'permit_used'})
    event(0, 'PLAN', {'source': 'muse', 'plan': {'waypoints': [1]}})
    event(1, 'AUTHORITY', {'event': 'permit_used'})
    for n in range(2, 102):
        event(n, 'TELEMETRY', {'speed': 0})
    event(102, 'DECISION', {'governance': {'decision': 'APPROVED'}})
    event(103, 'AUTHORITY', {'event': 'permit_refused', 'reason': 'trajectory_obstacle_clearance'})
    event(104, 'EXECUTION', {'command': {'intent': 'MOVE_TO'}, 'result': {'ok': False, 'rejected': True}, 'verified': False})
    db.commit()
    return event


def test_milestones_survive_activity_window_and_keep_latest_refusal(db):
    seed(db)
    result = run_presentation(db, 'presentation-run')
    assert result['plan']['id'] == 'presentation-0'
    assert result['first_admission']['id'] == 'presentation-1'
    assert result['authority']['payload']['reason'] == 'trajectory_obstacle_clearance'
    assert result['execution']['payload']['result']['ok'] is False


def test_newest_fallback_hold_replaces_old_model_plan(db):
    event = seed(db)
    event(105, 'PLAN', {'source': 'fallback', 'plan': {'waypoints': []}})
    db.commit()
    assert run_presentation(db, 'presentation-run')['plan']['payload']['plan']['waypoints'] == []


def test_endpoint_missing_and_read_only(db):
    seed(db)
    before = db.query(Event).count()
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app, raise_server_exceptions=True) as client:
            assert client.get('/runs/presentation-run/presentation').json()['first_admission']['id'] == 'presentation-1'
            assert client.get('/runs/missing-presentation/presentation').status_code == 404
        assert db.query(Event).count() == before
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous


def test_catalog_reports_current_site_and_active_thresholds(monkeypatch):
    from app.api.routes_governance import list_policies
    active = P.active_params()
    active['GEOFENCE'] = dict(min_x=0, max_x=36, min_y=0, max_y=26)
    active['HUMAN_STOP_RADIUS_M'] = 2.0
    active['REVIEW_RISK_THRESHOLD'] = .6
    monkeypatch.setattr(P, 'active_params', lambda: active)
    policies = {p.policy_id: p.parameters for p in list_policies()}
    assert policies['GEOFENCE_01'] == active['GEOFENCE']
    assert policies['HUMAN_PROXIMITY_02']['stop_radius_m'] == 2.0
    assert policies['HITL_05']['risk_threshold'] == .6
