"""Repeatable attacks on real learning stores, isolated from mission memory."""
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from app.services.route_learning import RouteMemory


def run_poisoning_drill():
    context = dict(site_id='poisoning-drill', map_version='v1', policy_version='v1', capability_profile_version='sim-v1')
    checks = []
    with tempfile.TemporaryDirectory(prefix='poisoning-drill-') as directory:
        memory = RouteMemory(str(Path(directory) / 'experience.db'), b'isolated-drill-secret-0123456789abcdef', clock=lambda: 1000.0)
        def add(run, source, delay=4.0, cell=(1, 1)):
            memory.record(run, [(cell, delay, 'STOP' if delay >= 4 else 'SLOW')], context=context, source_robot_id=source)
        add('solo', 'A')
        checks.append({'check': 'single_source_advisory', 'passed': memory.load(context=context)[0] == {}})
        add('peer', 'B')
        before = memory.load(context=context)[0][(1, 1)]
        for i in range(20):
            add(f'flood-{i}', 'A', 1.5)
        checks.append({'check': 'mild_flood_cannot_dilute_stop', 'passed': memory.load(context=context)[0][(1, 1)] == before})
        with closing(sqlite3.connect(memory.db_path)) as conn, conn:
            conn.execute("INSERT INTO experience VALUES ('forged','attack',9,9,0,'SLOW',1000,'forged')")
        costs, quarantine = memory.load(context=context)
        checks.append({'check': 'forged_record_quarantined', 'passed': any(r['id'] == 'forged' for r in quarantine) and (9, 9) not in costs})
        for i in range(3):
            for source, delay in [('A', 1.5), ('B', 1.5), ('rogue', 60.0)]:
                add(f'outlier-{source}-{i}', source, delay, (10, i))
        memory.load(context=context)
        checks.append({'check': 'repeated_outlier_quarantined', 'passed': any(s['source_robot_id'] == 'rogue' for s in memory.source_quarantine)})
        checks.append({'check': 'source_share_bounded', 'passed': all(c['max_source_share'] <= 0.5 for c in memory.cell_support)})
        from app.services.governance_engine import GovernanceEngine
        from app.schemas.governance import ActionProposal
        verdict = GovernanceEngine().evaluate({'x': 3, 'y': 3.5, 'zone': 'aisle', 'speed': 0,
                                               'nearest_obstacle_m': 5, 'human_detected': False},
                                              ActionProposal(intent='MOVE_TO', params={'x': -1000, 'y': -1000, 'max_speed': 0.2}, rationale='poisoned shortcut'))
        checks.append({'check': 'gate_refuses_out_of_bounds_shortcut', 'passed': verdict.decision == 'DENIED'})
        with closing(sqlite3.connect(memory.db_path)) as conn, conn:
            conn.execute("DELETE FROM experience WHERE run_id='solo'")
        costs, _ = memory.load(context=context)
        checks.append({'check': 'deletion_disables_reuse', 'passed': costs == {} and memory.integrity_error == 'memory_record_deleted'})
    return {'drill': 'poisoning', 'passed': all(c['passed'] for c in checks),
            'detail': 'Isolated real-store attacks; no live mission memory or robot movement is modified.',
            'checks': checks, 'scope': 'learning integrity and deterministic gate; no sensor-truth or hardware claim'}
