"""Optional Memgraph projection of verified mission evidence.

The graph locates evidence; SQL hash chains and signed decisions remain the
source of truth. Fixed queries only. No graph fact can issue a permit or alter
NetworkX costs. Reads reconstruct facts from source, never trust graph values.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
import math
import threading

from app.config import settings
from app.db.models import Run, GovernanceDecisionRecord, Event
from app.services.replay_service import get_run_timeline
from app.services.experience_policy import verified_decision
from app.autonomy.experience import CONTEXT_FIELDS
from app.utils.hashing import sha256_canonical
from app.utils.signing import canonical_ts

TERMINAL = ('completed', 'stopped', 'failed', 'failed_safety')


class GraphUnavailable(RuntimeError):
    pass


def source_snapshot(db, run_id):
    """Verify source on every use, including after a graph has been populated."""
    run = db.get(Run, run_id)
    if not run or run.status not in TERMINAL:
        raise ValueError('run_not_terminal')
    if db.query(Event).filter_by(run_id=run_id).count() > 10000:
        raise ValueError('run_exceeds_projection_limit')
    timeline = get_run_timeline(db, run_id)
    if not timeline.get('chain_valid'):
        raise ValueError('source_chain_invalid')
    signed = {r.event_hash: r for r in db.query(GovernanceDecisionRecord).filter_by(run_id=run_id).all()
              if verified_decision(r)}
    facts = []
    for event in timeline['events']:
        record = signed.get(event['hash'])
        if event['type'] != 'DECISION' or record is None:
            continue
        payload = event['payload']
        tel = json.loads(record.telemetry_summary or '{}')
        context = tel.get('experience_context') or {}
        robot = tel.get('source_robot_id')
        if not robot or any(not isinstance(context.get(k), str) or not context[k] for k in CONTEXT_FIELDS):
            continue
        if context['policy_version'] != record.policy_version:
            continue
        # Bind the graph's source event to exactly the signed decision fields.
        gov = payload.get('governance') or {}
        if (gov.get('decision') != record.decision or
                gov.get('policy_hits', []) != json.loads(record.policy_hits or '[]') or
                payload.get('proposal') != json.loads(record.proposal_json or '{}')):
            continue
        x, y = float(tel.get('x', math.nan)), float(tel.get('y', math.nan))
        if not all(math.isfinite(v) for v in (x, y)):
            continue
        facts.append(dict(event_id=event['id'], event_hash=event['hash'], run_id=run_id,
            mission_id=run.mission_id, robot_id=robot, ts=canonical_ts(record.ts), context=dict(context),
            context_id=sha256_canonical(context), x=x, y=y,
            cell_id=f"{sha256_canonical(context)}:{math.floor(x / .5)}:{math.floor(y / .5)}",
            decision=record.decision, policy_state=record.policy_state,
            policy_hits=json.loads(record.policy_hits or '[]'), receipt_id=record.id))
    return dict(run_id=run_id, mission_id=run.mission_id, status=run.status,
                event_count=len(timeline['events']), facts=facts,
                fingerprint=sha256_canonical({'events': [e['hash'] for e in timeline['events']],
                                             'status': run.status, 'facts': facts}))


RUN_UPSERT = """
MERGE (m:SA_Mission {ns:$ns, id:$mission_id})
MERGE (r:SA_Run {ns:$ns, id:$run_id})
SET r.status=$status, r.fingerprint=$fingerprint, r.event_count=$event_count,
    r.projected_at=$projected_at
MERGE (m)-[:HAS_RUN]->(r)
"""
FACT_UPSERT = """
UNWIND $facts AS f
MATCH (r:SA_Run {ns:$ns, id:f.run_id})
MERGE (b:SA_Robot {ns:$ns, id:f.robot_id})
MERGE (b)-[:PERFORMED]->(r)
MERGE (c:SA_Context {ns:$ns, id:f.context_id})
SET c.site_id=f.context.site_id, c.map_version=f.context.map_version,
    c.policy_version=f.context.policy_version,
    c.capability_profile_version=f.context.capability_profile_version
MERGE (s:SA_Site {ns:$ns, id:f.context.site_id})
MERGE (c)-[:AT_SITE]->(s)
MERGE (cell:SA_Cell {ns:$ns, id:f.cell_id})
MERGE (cell)-[:IN_CONTEXT]->(c)
MERGE (d:SA_Decision {ns:$ns, id:f.event_id})
SET d.run_id=f.run_id, d.event_hash=f.event_hash, d.ts=f.ts,
    d.decision=f.decision, d.x=f.x, d.y=f.y
MERGE (r)-[:HAS_DECISION]->(d)
MERGE (d)-[:IN_CONTEXT]->(c)
MERGE (d)-[:AT_CELL]->(cell)
FOREACH (policy IN f.policy_hits |
    MERGE (p:SA_Policy {ns:$ns, id:policy})
    MERGE (d)-[:TRIGGERED]->(p))
"""
HISTORY = """
MATCH (r:SA_Run {ns:$ns})-[:HAS_DECISION]->(d:SA_Decision)-[:IN_CONTEXT]->(c:SA_Context)
WHERE ($run_id='' OR r.id=$run_id)
  AND ($site_id='' OR (c.site_id=$site_id AND c.map_version=$map_version
       AND c.policy_version=$policy_version AND c.capability_profile_version=$capability_profile_version))
  AND ($near=false OR ((d.x-$x)*(d.x-$x)+(d.y-$y)*(d.y-$y) <= $radius*$radius))
RETURN r.id AS run_id, d.id AS event_id, d.event_hash AS event_hash
ORDER BY d.ts DESC LIMIT $limit
"""


class OperationalGraph:
    def __init__(self, driver=None):
        self._driver = driver
        self._lock = threading.RLock()
        self.state = 'not_checked'
        self.last_sync = None
        self.last_error = None

    def driver(self):
        if not settings.memgraph_enabled:
            raise GraphUnavailable('disabled')
        with self._lock:
            if self._driver is None:
                from neo4j import GraphDatabase
                self._driver = GraphDatabase.driver(settings.memgraph_uri,
                    auth=(settings.memgraph_username, settings.memgraph_password),
                    connection_timeout=settings.memgraph_timeout_s,
                    connection_acquisition_timeout=settings.memgraph_timeout_s,
                    max_transaction_retry_time=0, max_connection_pool_size=4)
        return self._driver

    def query(self, query, **params):
        from neo4j import Query
        with self.driver().session(database='memgraph') as session:
            return session.run(Query(query, timeout=settings.memgraph_timeout_s),
                               ns=settings.memgraph_namespace, **params).data()

    def status(self):
        if not settings.memgraph_enabled:
            return dict(enabled=False, state='disabled', runs=0, decisions=0,
                        authority='original SQL evidence; graph is advisory')
        try:
            rows = self.query('MATCH (r:SA_Run {ns:$ns}) RETURN count(r) AS runs')
            decisions = self.query('MATCH (d:SA_Decision {ns:$ns}) RETURN count(d) AS decisions')
            self.state, self.last_error = 'connected', None
            return dict(enabled=True, state=self.state, runs=rows[0]['runs'],
                        decisions=decisions[0]['decisions'], last_sync=self.last_sync,
                        namespace=settings.memgraph_namespace,
                        authority='original SQL evidence; graph is advisory')
        except Exception as exc:
            self.state, self.last_error = 'unavailable', type(exc).__name__
            return dict(enabled=True, state=self.state, error='graph_unavailable',
                        last_sync=self.last_sync, runs=None, decisions=None)

    def project_run(self, db, run_id):
        snapshot = source_snapshot(db, run_id)
        with self._lock:
            existing = self.query('MATCH (r:SA_Run {ns:$ns, id:$run_id}) RETURN r.fingerprint AS fingerprint', run_id=run_id)
            if existing and existing[0]['fingerprint'] == snapshot['fingerprint']:
                return {'run_id': run_id, 'state': 'unchanged', 'decisions': len(snapshot['facts'])}
            with self.driver().session(database='memgraph') as session:
                with session.begin_transaction(timeout=settings.memgraph_timeout_s) as tx:
                    params = {k: v for k, v in snapshot.items() if k != 'facts'}
                    params.update(ns=settings.memgraph_namespace, projected_at=datetime.now(timezone.utc).isoformat())
                    tx.run(RUN_UPSERT, **params).consume()
                    tx.run('MATCH (r:SA_Run {ns:$ns, id:$run_id})-[:HAS_DECISION]->(d:SA_Decision) DETACH DELETE d',
                           ns=settings.memgraph_namespace, run_id=run_id).consume()
                    if snapshot['facts']:
                        tx.run(FACT_UPSERT, ns=settings.memgraph_namespace, facts=snapshot['facts']).consume()
                    tx.commit()
            self.last_sync = datetime.now(timezone.utc).isoformat()
            return {'run_id': run_id, 'state': 'projected', 'decisions': len(snapshot['facts'])}

    def sync_recent(self, db):
        if not settings.memgraph_enabled:
            return {'state': 'disabled', 'runs': []}
        results = []
        runs = db.query(Run).filter(Run.status.in_(TERMINAL)).order_by(Run.started_at.desc()).limit(20).all()
        for run in runs:
            try:
                results.append(self.project_run(db, run.id))
            except ValueError as exc:
                results.append({'run_id': run.id, 'state': 'rejected', 'reason': str(exc)})
            except Exception:
                self.state = 'unavailable'
                raise GraphUnavailable('graph_unavailable') from None
        # Probe even when there are no runs; configured does not mean connected.
        if self.status()['state'] != 'connected':
            raise GraphUnavailable('graph_unavailable')
        return {'state': 'complete', 'runs': results}

    def history(self, db, *, context=None, run_id='', x=None, y=None, radius=5., limit=30):
        params = {k: (context or {}).get(k, '') for k in CONTEXT_FIELDS}
        rows = self.query(HISTORY, **params, run_id=run_id, near=x is not None and y is not None,
                          x=x or 0., y=y or 0., radius=radius, limit=limit)
        snapshots, facts, excluded = {}, [], 0
        now = datetime.now(timezone.utc)
        seen = set()
        for row in rows:
            rid = row.get('run_id')
            if rid not in snapshots:
                try:
                    snapshot = source_snapshot(db, rid)
                    snapshots[rid] = {f['event_id']: f for f in snapshot['facts']}
                except (ValueError, TypeError):
                    snapshots[rid] = {}
            fact = snapshots[rid].get(row.get('event_id'))
            if fact:
                ts = datetime.fromisoformat(fact['ts']).replace(tzinfo=timezone.utc)
                age = (now - ts).total_seconds()
                valid = (fact['event_hash'] == row.get('event_hash') and 0 <= age <= settings.experience_ttl_s
                         and (not run_id or fact['run_id'] == run_id)
                         and (context is None or fact['context'] == context)
                         and (x is None or y is None or math.hypot(fact['x']-x, fact['y']-y) <= radius))
            else:
                valid = False
            if valid and fact['event_id'] not in seen:
                facts.append(fact)
                seen.add(fact['event_id'])
            else:
                excluded += 1
        policies = Counter(p for f in facts for p in f['policy_hits'])
        return dict(state='available', facts=facts, excluded=excluded,
                    policy_counts=[{'policy': p, 'count': n} for p, n in policies.most_common()],
                    scope='bounded historical sample; reverified from original evidence; advisory only')

    def close(self):
        if self._driver is not None:
            self._driver.close()
            self._driver = None


graph = OperationalGraph()


async def graph_worker():
    """Projection runs outside the control loop; transient failures retry next pass."""
    from app.db.session import SessionLocal
    def sync():
        with SessionLocal() as db:
            graph.sync_recent(db)
    while True:
        try:
            await asyncio.to_thread(sync)
        except Exception:
            graph.state = 'unavailable'
        await asyncio.sleep(settings.memgraph_sync_interval_s)


def planner_history(telemetry):
    if not settings.memgraph_enabled:
        return {'state': 'disabled', 'facts': []}
    from app.autonomy.experience import context_from_state
    from app.policies.versioning import policy_version_hash
    from app.db.session import SessionLocal
    context = context_from_state(telemetry, policy_version_hash())
    if context is None:
        return {'state': 'context_unavailable', 'facts': []}
    try:
        with SessionLocal() as db:
            return graph.history(db, context=context, x=float(telemetry['x']), y=float(telemetry['y']), limit=10)
    except Exception:
        return {'state': 'unavailable', 'facts': []}
