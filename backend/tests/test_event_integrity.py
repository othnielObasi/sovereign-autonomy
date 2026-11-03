"""Regression: repeated/retrograde clock values cannot fork a run's event chain."""
import json
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.db.models import Mission, Run, Event
from app.services.run_service import RunService
from app.services.replay_service import get_run_timeline


@pytest.fixture
def record(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'events.db'))
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
    with session() as db:
        db.add(Mission(id='mission', title='Integrity', goal_json='{}', status='running', created_at=now))
        db.add(Run(id='run', mission_id='mission', status='running', started_at=now))
        db.commit()
    yield session, now, RunService()
    engine.dispose()


@pytest.mark.parametrize('clock_delta', [0, -1])
def test_equal_or_backwards_clock_keeps_reloadable_chain(record, monkeypatch, clock_delta):
    session, now, svc = record
    monkeypatch.setattr('app.services.run_service.utc_now', lambda: now)
    with session() as db:
        svc._append_event(db, 'run', 'PLAN', {'plan': 'initial'})
    monkeypatch.setattr('app.services.run_service.utc_now', lambda: now + timedelta(seconds=clock_delta))
    # Separate sessions exercise SQLite's loss of tzinfo and persisted ordering.
    for i in range(12):
        with session() as db:
            svc._append_event(db, 'run', 'EXECUTION', {'index': i})
    with session() as db:
        timeline = get_run_timeline(db, 'run')
    assert timeline['chain_valid'] is True
    timestamps = [event['ts'] for event in timeline['events']]
    assert len(set(timestamps)) == 13
    assert timestamps == sorted(timestamps)


@pytest.mark.parametrize('change', ['payload', 'timestamp', 'link', 'hash'])
def test_replay_detects_original_event_tampering(record, change):
    session, now, svc = record
    with session() as db:
        first = svc._append_event(db, 'run', 'PLAN', {'goal': [18, 3.5]})
        svc._append_event(db, 'run', 'EXECUTION', {'intent': 'STOP'})
        if change == 'payload': first.payload_json = json.dumps({'goal': [35, 25]})
        if change == 'timestamp': first.ts = now - timedelta(days=1)
        if change == 'link': first.prev_hash = 'invalid'
        if change == 'hash': first.hash = 'invalid'
        db.commit()
        assert get_run_timeline(db, 'run')['chain_valid'] is False


def test_compliance_exports_preserve_original_integrity_result(record):
    from app.api.routes_compliance import get_compliance_report, get_compliance_report_text, export_compliance_report, verify_audit_chain
    session, now, svc = record
    with session() as db:
        event = svc._append_event(db, 'run', 'PLAN', {'goal': [6, 18.5]})
        assert asyncio.run(verify_audit_chain('run', db))['chain_valid'] is True
        event.payload_json = '{}'
        db.commit()
        assert asyncio.run(get_compliance_report('run', 'ISO_42001', db)).chain_valid is False
        text = asyncio.run(get_compliance_report_text('run', 'ISO_42001', db))
        assert 'COMPROMISED' in text.body.decode()
        exported = asyncio.run(export_compliance_report('run', 'ISO_42001', db))
        assert json.loads(exported.body)['chain_valid'] is False
        assert asyncio.run(verify_audit_chain('run', db))['chain_valid'] is False
