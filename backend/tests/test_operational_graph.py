"""Source integrity, context isolation, API permissions and real Bolt projection.

Set MEMGRAPH_TEST_URI to an isolated Memgraph to run the integration cases.
Each case uses a unique namespace and deletes only that namespace afterwards.
"""
import json
import os
import uuid
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.session import Base
from app.db.models import Mission, Run, GovernanceDecisionRecord, Event
from app.services.run_service import RunService
from app.services.operational_graph import OperationalGraph, source_snapshot, planner_history
from app.services.governance_engine import GovernanceEngine
from app.utils import signing
from app.utils.time import utc_now

CONTEXT = dict(site_id='test-site', map_version='map-one', policy_version='policy-one',
               capability_profile_version='carrier-one')


@pytest.fixture
def source(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path/'source.db'), connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        now = utc_now()
        db.add(Mission(id='mission', title='Source mission', goal_json='{}', status='completed', created_at=now))
        db.add(Run(id='run', mission_id='mission', status='completed', started_at=now, ended_at=now))
        db.commit()
        proposal = {'intent': 'MOVE_TO', 'params': {'x': 6, 'y': 4, 'max_speed': .3}, 'rationale': 'test'}
        record = GovernanceDecisionRecord(run_id='run', ts=now, decision='DENIED', policy_state='REPLAN',
            risk_score=.9, policy_hits=json.dumps(['HAZARD_EXCLUSION_08']), reasons='[]',
            proposal_intent='MOVE_TO', proposal_json=json.dumps(proposal),
            telemetry_summary=json.dumps(dict(x=4., y=4., experience_context=CONTEXT, source_robot_id='robot-1')),
            was_executed='false', escalated='false', policy_version='policy-one')
        db.add(record)
        db.flush()
        record.signature, record.signing_key_id = signing.sign(GovernanceEngine.signing_payload(record))
        event = RunService()._append_event(db, 'run', 'DECISION', {'proposal': proposal,
            'governance': {'decision': 'DENIED', 'policy_hits': ['HAZARD_EXCLUSION_08']}})
        record.event_hash = event.hash
        db.commit()
        yield db, record, event, factory
    engine.dispose()


def test_source_contains_signed_evidence_and_exact_context(source):
    db, record, event, _ = source
    snap = source_snapshot(db, 'run')
    assert snap['facts'][0]['event_id'] == event.id
    assert snap['facts'][0]['context'] == CONTEXT
    assert snap['facts'][0]['receipt_id'] == record.id


@pytest.mark.parametrize('change', ['signature', 'unsigned', 'wrong_context', 'wrong_event'])
def test_projection_excludes_untrusted_decisions(source, change):
    db, record, event, _ = source
    if change == 'signature': record.signature = 'forged'
    if change == 'unsigned': record.signature = None
    if change == 'wrong_event': record.event_hash = 'forged'
    if change == 'wrong_context':
        record.telemetry_summary = json.dumps(dict(x=4, y=4, source_robot_id='robot-1', experience_context=CONTEXT))
    db.commit()
    assert source_snapshot(db, 'run')['facts'] == []


def test_bad_original_chain_and_active_runs_are_rejected(source):
    db, _, event, _ = source
    event.payload_json = '{}'; db.commit()
    with pytest.raises(ValueError, match='source_chain_invalid'):
        source_snapshot(db, 'run')
    db.get(Run, 'run').status = 'running'; db.commit()
    with pytest.raises(ValueError, match='run_not_terminal'):
        source_snapshot(db, 'run')


def test_graph_values_cannot_override_source_and_filters_are_rechecked(source, monkeypatch):
    db, _, event, _ = source
    graph = OperationalGraph()
    rows = [{'run_id': 'run', 'event_id': event.id, 'event_hash': event.hash,
             'x': 9999, 'decision': 'APPROVED'}]
    monkeypatch.setattr(graph, 'query', lambda *args, **kwargs: rows)
    result = graph.history(db, context=CONTEXT, x=4, y=4)
    assert result['facts'][0]['decision'] == 'DENIED'
    assert result['facts'][0]['x'] == 4
    assert result['policy_counts'][0]['policy'] == 'HAZARD_EXCLUSION_08'
    assert not graph.history(db, context=dict(CONTEXT, map_version='other'))['facts']
    assert not graph.history(db, x=20, y=20, radius=1)['facts']
    assert not graph.history(db, run_id='different')['facts']
    monkeypatch.setattr(settings, 'experience_ttl_s', .000001)
    assert not graph.history(db)['facts']


def test_stale_or_deleted_source_is_not_reused(source, monkeypatch):
    db, _, event, _ = source
    graph = OperationalGraph()
    monkeypatch.setattr(graph, 'query', lambda *args, **kwargs:
                        [{'run_id': 'run', 'event_id': event.id, 'event_hash': event.hash}])
    event.payload_json = '{}'; db.commit()
    assert graph.history(db)['excluded'] == 1
    db.delete(db.get(Run, 'run')); db.commit()
    assert graph.history(db)['facts'] == []


def test_disabled_and_outage_do_not_supply_planner_facts(monkeypatch):
    graph = OperationalGraph()
    monkeypatch.setattr(settings, 'memgraph_enabled', False)
    assert graph.status()['state'] == 'disabled'
    assert planner_history({}) == {'state': 'disabled', 'facts': []}
    monkeypatch.setattr(settings, 'memgraph_enabled', True)
    monkeypatch.setattr(graph, 'query', lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionError('password=secret')))
    status = graph.status()
    assert status['state'] == 'unavailable' and 'secret' not in json.dumps(status)
    assert planner_history({})['state'] == 'context_unavailable'


def test_graph_api_permissions_bounds_and_no_cypher_endpoint(source, monkeypatch):
    from app.api import routes_knowledge as api
    from app.auth.jwt import create_access_token
    from app.deps import get_db
    db, _, _, factory = source
    app = FastAPI(); app.include_router(api.router)
    def session():
        with factory() as s: yield s
    app.dependency_overrides[get_db] = session
    calls = []
    monkeypatch.setattr(api.graph, 'sync_recent', lambda session: calls.append(True) or {'state': 'complete'})
    monkeypatch.setattr(api.graph, 'status', lambda: {'state': 'disabled'})
    monkeypatch.setattr(settings, 'auth_required', True)
    with TestClient(app) as client:
        viewer = {'Authorization': 'Bearer ' + create_access_token('reader', role='viewer')}
        operator = {'Authorization': 'Bearer ' + create_access_token('operator', role='operator')}
        assert client.get('/knowledge/status').status_code == 401
        assert client.get('/knowledge/status', headers=viewer).status_code == 200
        assert client.post('/knowledge/sync').status_code == 401
        assert client.post('/knowledge/sync', headers=viewer).status_code == 403
        assert not calls
        assert client.post('/knowledge/sync', headers=operator).status_code == 200
        assert client.get('/knowledge/runs/run?limit=1000', headers=viewer).status_code == 422
        assert client.post('/knowledge/history', headers=viewer,
            json={'context': CONTEXT, 'x': 0, 'y': 0, 'radius': 100}).status_code == 422
        assert client.post('/knowledge/query', headers=operator, json={'cypher': 'MATCH (n) DELETE n'}).status_code == 404


@pytest.fixture
def live_graph(monkeypatch):
    uri = os.getenv('MEMGRAPH_TEST_URI')
    if not uri:
        pytest.skip('Set MEMGRAPH_TEST_URI for real Memgraph integration')
    monkeypatch.setattr(settings, 'memgraph_enabled', True)
    monkeypatch.setattr(settings, 'memgraph_uri', uri)
    monkeypatch.setattr(settings, 'memgraph_namespace', 'pytest-' + uuid.uuid4().hex)
    graph = OperationalGraph()
    assert graph.status()['state'] == 'connected'
    yield graph
    graph.query('MATCH (n {ns:$ns}) DETACH DELETE n')
    graph.close()


def test_real_memgraph_projection_is_idempotent_and_queryable(source, live_graph):
    db, record, event, _ = source
    assert live_graph.project_run(db, 'run')['state'] == 'projected'
    assert live_graph.project_run(db, 'run')['state'] == 'unchanged'
    assert live_graph.status()['decisions'] == 1
    assert live_graph.status()['runs'] == 1
    result = live_graph.history(db, context=CONTEXT, x=4, y=4)
    assert result['facts'][0]['event_id'] == event.id
    assert result['facts'][0]['receipt_id'] == record.id
    assert not live_graph.history(db, context=dict(CONTEXT, map_version='different'))['facts']
    assert live_graph.query('MATCH (d:SA_Decision {ns:$ns})-[:TRIGGERED]->(p:SA_Policy) RETURN p.id AS id')[0]['id'] == 'HAZARD_EXCLUSION_08'
    assert live_graph.query('MATCH (b:SA_Robot {ns:$ns})-[:PERFORMED]->(:SA_Run) RETURN b.id AS id')[0]['id'] == 'robot-1'


def test_real_memgraph_never_launders_modified_source(source, live_graph):
    db, record, event, _ = source
    live_graph.project_run(db, 'run')
    # Graph metadata edits never become source facts.
    live_graph.query('MATCH (d:SA_Decision {ns:$ns}) SET d.decision="APPROVED"')
    assert live_graph.history(db)['facts'][0]['decision'] == 'DENIED'
    record.signature = 'forged'; db.commit()
    assert not live_graph.history(db)['facts']
    assert live_graph.project_run(db, 'run')['decisions'] == 0
    assert live_graph.status()['decisions'] == 0


def test_real_projection_failure_rolls_back_and_namespaces_are_separate(source, live_graph, monkeypatch):
    from app.services import operational_graph as module
    db, _, _, _ = source
    live_graph.project_run(db, 'run')
    db.get(Run, 'run').status = 'stopped'; db.commit()
    with monkeypatch.context() as scoped:
        scoped.setattr(module, 'FACT_UPSERT', 'INVALID CYPHER')
        with pytest.raises(Exception):
            live_graph.project_run(db, 'run')
    assert live_graph.status()['decisions'] == 1
    assert live_graph.query('MATCH (r:SA_Run {ns:$ns}) RETURN r.status AS status')[0]['status'] == 'completed'
    with monkeypatch.context() as scoped:
        scoped.setattr(settings, 'memgraph_namespace', 'separate-' + uuid.uuid4().hex)
        assert live_graph.status()['decisions'] == 0
        assert not live_graph.history(db)['facts']


def test_planner_withholds_unreleased_real_graph_history(source, live_graph, monkeypatch):
    from app.services import operational_graph as module
    import app.db.session as session_module
    from app.policies import versioning
    db, _, event, factory = source
    live_graph.project_run(db, 'run')
    monkeypatch.setattr(module, 'graph', live_graph)
    monkeypatch.setattr(session_module, 'SessionLocal', factory)
    monkeypatch.setattr(versioning, 'policy_version_hash', lambda: 'policy-one')
    tel = dict(CONTEXT, x=4., y=4.)
    assert planner_history(tel)['facts'] == []
    assert live_graph.history(db, context=CONTEXT)['facts'][0]['event_id'] == event.id
    assert not planner_history(dict(tel, capability_profile_version='other'))['facts']


def test_muse_and_agentic_prompts_receive_graph_evidence_without_model_calls(monkeypatch):
    import asyncio
    from app.services import operational_graph
    from app.services.muse_planner import MusePlanner
    from app.services.gemini_planner import GeminiPlanner
    from app.services.agentic_planner import AgenticPlanner
    history = {'state': 'available', 'facts': [{'event_id': 'event-proof', 'decision': 'DENIED'}]}
    monkeypatch.setattr(operational_graph, 'planner_history', lambda tel: history)
    async def no_camera(self): return None
    captured = {}
    async def base_plan(self, *args, **kwargs):
        captured.update(kwargs)
        return {'waypoints': [], 'model_used': 'test-transport'}
    monkeypatch.setattr(MusePlanner, '_camera_frame', no_camera)
    monkeypatch.setattr(GeminiPlanner, 'generate_plan', base_plan)
    plan = asyncio.run(MusePlanner().generate_plan({}, 'test', {}))
    assert 'event-proof' in captured['untrusted_context']
    assert plan['graph_history']['event_ids'] == ['event-proof']
    prompt = AgenticPlanner()._build_system_prompt({}, {}, 'test', operational_history=history)
    assert 'event-proof' in prompt and 'current telemetry and policies take priority' in prompt


def test_real_connection_refusal_returns_no_planner_history(source, monkeypatch):
    from app.services import operational_graph as module
    import app.db.session as session_module
    from app.policies import versioning
    _, _, _, factory = source
    monkeypatch.setattr(settings, 'memgraph_enabled', True)
    monkeypatch.setattr(settings, 'memgraph_uri', 'bolt://127.0.0.1:9')
    monkeypatch.setattr(settings, 'memgraph_timeout_s', .2)
    graph = OperationalGraph()
    monkeypatch.setattr(module, 'graph', graph)
    monkeypatch.setattr(session_module, 'SessionLocal', factory)
    monkeypatch.setattr(versioning, 'policy_version_hash', lambda: 'policy-one')
    # Let the release boundary pass so this case still exercises a real Bolt refusal.
    from app.services import learning_release, route_learning
    monkeypatch.setattr(learning_release, 'released_route_advice', lambda *args:
                        {'accepted': [{'evidence_ids': ['released']} ]})
    monkeypatch.setattr(route_learning.get_memory(), 'release_evidence', lambda context: [])
    try:
        assert planner_history(dict(CONTEXT, x=4., y=4.)) == {'state': 'unavailable', 'facts': []}
    finally:
        graph.close()
