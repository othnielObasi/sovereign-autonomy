"""Adversarial memory tests: real SQLite stores, no models or live robot calls."""
import json
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.services.route_learning import RouteMemory
from app.services.memory_ledger import MemoryIntegrityError

SECRET = b'poisoning-tests-secret-0123456789abcdef'
CONTEXT = dict(site_id='site', map_version='map', policy_version='rules', capability_profile_version='amr')


@pytest.fixture
def memory(tmp_path):
    return RouteMemory(str(tmp_path / 'memory.db'), SECRET, clock=lambda: 1000.0)


def add(memory, source='A', run='run', delay=4.0, cell=(1, 1), context=CONTEXT):
    return memory.record(run, [(cell, delay, 'STOP' if delay >= 4 else 'SLOW')],
                         context=context, source_robot_id=source)


def test_one_source_cannot_self_corroborate_with_many_missions(memory):
    for i in range(20):
        add(memory, run=f'run-{i}', delay=60)
    assert memory.load(context=CONTEXT)[0] == {}
    assert all(r['status'] == 'advisory' for r in memory.last_retrieval)


def test_second_source_enables_clipped_equal_votes(memory):
    add(memory, delay=60)
    add(memory, source='B', delay=4)
    assert memory.load(context=CONTEXT)[0] == {(1, 1): 4}
    assert memory.cell_support[0]['max_source_share'] == 0.5


def test_mild_floods_do_not_dilute_confirmed_stop(memory):
    for source in ['A', 'B']:
        add(memory, source=source)
    for i in range(30):
        add(memory, run=f'flood-{i}', delay=1.5)
    add(memory, source='C', delay=0)
    assert memory.load(context=CONTEXT)[0] == {(1, 1): 4}


@pytest.mark.parametrize('false_delay', [4.0, 60.0])
def test_repeated_false_observations_quarantine_source_durably_in_context(memory, false_delay):
    for cell in [(1, 1), (1, 2), (1, 3)]:
        for source, delay in [('A', 1.5), ('B', 1.5), ('rogue', false_delay)]:
            add(memory, source=source, delay=delay, cell=cell)
    assert set(memory.load(context=CONTEXT)[0].values()) == {1.5}
    assert memory.source_quarantine[0]['source_robot_id'] == 'rogue'
    fresh = RouteMemory(memory.db_path, SECRET, clock=lambda: 1000.0)
    add(fresh, source='rogue', run='new', cell=(7, 7))
    add(fresh, source='A', run='new', cell=(7, 7))
    assert (7, 7) not in fresh.load(context=CONTEXT)[0]
    assert any(r['reason'] == 'source_quarantined' for r in fresh.last_retrieval)
    new_context = dict(CONTEXT, map_version='revalidated')
    for source in ['A', 'rogue']:
        add(fresh, source=source, context=new_context)
    assert fresh.load(context=new_context)[0] == {(1, 1): 4}


def test_one_peer_or_one_cell_is_not_enough_to_quarantine(memory):
    for i in range(3):
        add(memory, source='A', delay=1.5, cell=(1, i))
        add(memory, source='rogue', delay=60, cell=(1, i))
    memory.load(context=CONTEXT)
    assert memory.source_quarantine == []


@pytest.mark.parametrize('operation', ['record', 'ledger_tail', 'ledger_all', 'source_record', 'invalidation'])
def test_deletion_disables_reuse_and_cannot_be_healed_by_writing(memory, operation):
    add(memory)
    add(memory, source='B')
    with sqlite3.connect(memory.db_path) as conn:
        if operation == 'record':
            conn.execute("DELETE FROM experience WHERE run_id='run'")
        elif operation.startswith('ledger'):
            conn.execute('DELETE FROM memory_ledger' + (' WHERE seq=(SELECT MAX(seq) FROM memory_ledger)' if operation == 'ledger_tail' else ''))
        elif operation == 'invalidation':
            pass
        else:
            pass
    if operation in ('source_record', 'invalidation'):
        if operation == 'source_record':
            memory._quarantine_source(CONTEXT, 'rogue', [[1, 1]])
            table = 'experience_sources'
        else:
            memory.invalidate('event', {'site_id': 'site'}, 'maintenance')
            table = 'experience_invalidations'
        with sqlite3.connect(memory.db_path) as conn:
            conn.execute(f'DELETE FROM {table}')
    assert memory.load(context=CONTEXT)[0] == {}
    assert memory.integrity_error
    with pytest.raises(MemoryIntegrityError):
        add(memory, run='after-deletion')


def test_database_rollback_detected_by_separate_checkpoint(memory, tmp_path):
    add(memory)
    snapshot = tmp_path / 'old.db'
    shutil.copyfile(memory.db_path, snapshot)
    add(memory, source='B')
    shutil.copyfile(snapshot, memory.db_path)
    assert memory.load(context=CONTEXT)[0] == {}
    assert memory.integrity_error == 'memory_checkpoint_mismatch'
    restarted = RouteMemory(memory.db_path, SECRET, clock=lambda: 1000.0)
    assert restarted.status(context=CONTEXT)['enabled'] is False


def test_missing_external_checkpoint_is_not_reinitialized(memory):
    add(memory)
    with sqlite3.connect(memory.ledger.path) as conn:
        conn.execute('DELETE FROM checkpoint')
    restarted = RouteMemory(memory.db_path, SECRET, clock=lambda: 1000.0)
    assert restarted.load(context=CONTEXT)[0] == {}
    assert restarted.integrity_error == 'memory_checkpoint_missing'


def test_failed_write_rolls_back_inventory_and_checkpoint_together(memory):
    add(memory)
    conn = memory._db()
    memory.ledger.attach(conn)
    with pytest.raises(RuntimeError):
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            memory.ledger.append(conn, 'experience', 'not-committed')
            raise RuntimeError('simulated failure before commit')
    conn.close()
    assert memory.status(context=CONTEXT)['integrity_error'] is None
    assert add(memory, source='B') == 1
    assert memory.load(context=CONTEXT)[0] == {(1, 1): 4}


def test_concurrent_writers_have_one_valid_checkpoint(memory):
    def write(i):
        other = RouteMemory(memory.db_path, SECRET, clock=lambda: 1000.0)
        add(other, source=f'robot-{i}', run=f'run-{i}')
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write, range(8)))
    assert memory.load(context=CONTEXT)[0] == {(1, 1): 4}
    assert memory.integrity_error is None


def test_valid_but_unlogged_record_is_not_reused(memory):
    add(memory)
    with sqlite3.connect(memory.db_path) as conn:
        row = list(conn.execute('SELECT * FROM experience').fetchone())
        metadata = json.loads(conn.execute('SELECT metadata FROM experience_context').fetchone()[0])
        metadata['source_robot_id'] = 'B'
        row[0] = 'unlogged'
        body = dict(zip(('id', 'run_id', 'i', 'j', 'delay_s', 'kind', 'observed_at'), row[:-1]))
        row[-1] = memory.sign(dict(body, metadata=metadata))
        conn.execute('INSERT INTO experience VALUES (?,?,?,?,?,?,?,?)', row)
        conn.execute('INSERT INTO experience_context VALUES (?,?)', (row[0], json.dumps(metadata)))
    assert memory.load(context=CONTEXT)[0] == {}
    assert any(r['reason'] == 'unanchored_record' for r in memory.last_retrieval)


def test_real_store_poisoning_drill_passes():
    from app.services.poisoning_drill import run_poisoning_drill
    result = run_poisoning_drill()
    assert result['passed'], result
    assert len(result['checks']) == 7


def test_corrupt_memory_does_not_hide_fresh_environment_telemetry(memory):
    from app.services.environment_lifecycle import EnvironmentLifecycle
    lifecycle = EnvironmentLifecycle(memory, clock=lambda: 1000.0)
    state = dict(CONTEXT, robot_id='A', site_constraints=[])
    lifecycle.observe(state, CONTEXT['policy_version'])
    add(memory)
    with sqlite3.connect(memory.db_path) as conn:
        conn.execute('DELETE FROM experience')
    changed = dict(state, map_version='new-map')
    assert lifecycle.observe(changed, CONTEXT['policy_version']) == []
    assert memory.integrity_error == 'memory_record_deleted'
    assert memory.load(context=CONTEXT)[0] == {}


def test_wal_journals_are_not_claimed_atomic_across_checkpoint(memory):
    with sqlite3.connect(memory.db_path) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
    assert memory.load(context=CONTEXT)[0] == {}
    assert memory.integrity_error == 'memory_requires_rollback_journal'


def test_corrupt_checkpoint_file_disables_learning_instead_of_crashing(memory):
    from pathlib import Path
    Path(memory.ledger.path).write_bytes(b'not a SQLite database')
    assert memory.load(context=CONTEXT)[0] == {}
    assert memory.integrity_error == 'memory_storage_unreadable'
