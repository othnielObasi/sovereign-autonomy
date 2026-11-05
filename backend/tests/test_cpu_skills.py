"""Actual CPU physics/learning plus authority failures. No model APIs or GPU."""
import copy
import json
from pathlib import Path
import shutil
import sqlite3
import time
from types import SimpleNamespace

import pytest

pytest.importorskip('mujoco')
import numpy as np

from app.skills import physics
from app.skills.service import SkillLab, SkillConflict
from app.services.memory_ledger import MemoryIntegrityError

SECRET = b'cpu-skill-test-secret-0123456789abcdef'


@pytest.fixture(scope='module')
def templates(tmp_path_factory):
    root = tmp_path_factory.mktemp('cpu-skills')
    from app.services import execution_authority
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(execution_authority, 'get_authority', lambda: SimpleNamespace(kills=SimpleNamespace(epoch=0,active=lambda: [])))
        released = root/'released'; released.mkdir()
        lab = SkillLab(released/'lab.sqlite', SECRET)
        built = lab.train('operator-a')
        shutil.copytree(released, root/'trained')
        for action in ('evaluate','approve','release'):
            result = lab.transition(built['version'], action, built['digest'], 'operator-a')
        overview = lab.overview()
        evaluation = overview['versions'][0]['evaluation']
        assert evaluation['passed'] and evaluation['successes'] == 6
        assert evaluation['no_grip_ablation_success'] is False
        assert overview['versions'][0]['training']['samples'] > 1000
        report = Path('data/cpu-skill-validation'); report.mkdir(parents=True, exist_ok=True)
        (report/'evaluation.json').write_text(json.dumps(overview, indent=2), encoding='utf8')
    return root


@pytest.fixture
def lab(templates, tmp_path, monkeypatch):
    from app.services import execution_authority
    monkeypatch.setattr(execution_authority, 'get_authority', lambda: SimpleNamespace(kills=SimpleNamespace(epoch=0,active=lambda: [])))
    shutil.copytree(templates/'released', tmp_path/'lab')
    return SkillLab(tmp_path/'lab'/'lab.sqlite', SECRET)


def version(lab):
    row = lab.overview()['versions'][0]
    return row['version'], row['digest']


def installed_grant(lab):
    v, digest = version(lab)
    assert lab.install(v, digest, 'arm-b', 'alice')['movement_authority'] is False
    return lab.grant(v, digest, 'arm-b', 'alice')


def test_learned_transfer_executes_fresh_physics_and_cannot_replay(lab):
    policy = lab.snapshot()['versions'][1]['policy']
    with np.load(lab.artifacts/policy['dataset_file'], allow_pickle=False) as dataset:
        observations, actions = dataset['observations'], dataset['actions']
        assert physics.digest(dict(x=observations.tolist(), y=actions.tolist())) == policy['dataset_hash']
        assert np.mean((observations @ np.asarray(policy['weights']) - actions)**2) < 1e-8
    envelope = installed_grant(lab)
    assert not lab.overview()['attempts'], 'Installing and granting must not move the robot'
    attempt = lab.execute(envelope, 'alice')
    result = attempt['result']
    assert result['success'] and result['max_object_height_m'] > .12
    assert result['placement_error_m'] < .035 and result['contact_samples'] > 0
    assert len(result['frames']) > 20 and result['physics_steps'] > 100
    assert attempt['digest'] == envelope['permit']['digest']
    assert result['source'] != list(physics.scenario(71)[0])
    assert physics.digest(result) == attempt['result_hash']
    with pytest.raises(SkillConflict, match='unknown_or_used'):
        lab.execute(envelope, 'alice')
    restarted = SkillLab(lab.path, SECRET)
    with pytest.raises(SkillConflict, match='unknown_or_used'):
        restarted.execute(envelope, 'alice')
    Path('data/cpu-skill-validation/transfer.json').write_text(json.dumps(attempt, indent=2), encoding='utf8')


def test_approval_cannot_be_skipped(templates, tmp_path):
    shutil.copytree(templates/'trained', tmp_path/'trained')
    lab = SkillLab(tmp_path/'trained'/'lab.sqlite', SECRET)
    v, digest = version(lab)
    for action in ('approve','release'):
        with pytest.raises(SkillConflict, match='transition'):
            lab.transition(v, action, digest, 'alice')
    with pytest.raises(SkillConflict, match='not_currently_released'):
        lab.install(v, digest, 'arm-b', 'alice')


def test_incompatible_recipient_and_uninstalled_version_are_refused(lab):
    v, digest = version(lab)
    with pytest.raises(SkillConflict, match='capability'):
        lab.install(v, digest, 'arm-c', 'alice')
    with pytest.raises(SkillConflict, match='not_installed'):
        lab.grant(v, digest, 'arm-b', 'alice')
    with pytest.raises(SkillConflict, match='version_conflict'):
        lab.install(v, '0'*64, 'arm-b', 'alice')


@pytest.mark.parametrize('change', ['tamper','expiry','withdraw','stop_reset','fleet_epoch'])
def test_old_or_modified_grants_cannot_start(lab, monkeypatch, change):
    envelope = installed_grant(lab)
    if change == 'tamper': envelope['permit']['robot_id'] = 'arm-a'
    elif change == 'expiry': monkeypatch.setattr(lab, 'clock', lambda: envelope['permit']['expires_at']+1)
    elif change == 'withdraw': lab.transition(*version(lab)[:1], 'withdraw', version(lab)[1], 'alice')
    elif change == 'stop_reset': lab.stop('alice'); lab.stop('alice', reset=True)
    else: monkeypatch.setattr(lab, 'fleet_epoch', lambda: 1)
    with pytest.raises(SkillConflict): lab.execute(envelope, 'alice')
    assert not lab.overview()['attempts']


def test_release_and_stop_are_checked_during_physics(lab):
    envelope = installed_grant(lab)
    original = lab.guard
    ticks = [0]
    def interrupt(*args, **kwargs):
        ticks[0] += 1
        if ticks[0] == 15:
            lab.stop('alice')
            lab.stop('alice', reset=True)  # A fast reset must not resurrect this run.
        return original(*args, **kwargs)
    lab.guard = interrupt
    attempt = lab.execute(envelope, 'alice')
    assert not attempt['result']['success']
    assert attempt['result']['reason'] == 'controller_generation_changed'


def test_withdrawal_interrupts_an_active_execution(lab):
    envelope = installed_grant(lab)
    original = lab.guard
    ticks = [0]
    def interrupt(*args, **kwargs):
        ticks[0] += 1
        if ticks[0] == 15:
            v, digest = version(lab)
            lab.transition(v, 'withdraw', digest, 'alice')
        return original(*args, **kwargs)
    lab.guard = interrupt
    result = lab.execute(envelope, 'alice')['result']
    assert not result['success'] and result['reason'] == 'release_withdrawn_or_expired'


@pytest.mark.parametrize('mutation', ['model','dataset','ledger_delete'])
def test_tampered_artifacts_or_evidence_fail_closed(lab, mutation):
    envelope = installed_grant(lab)
    if mutation == 'dataset':
        policy = lab.snapshot()['versions'][1]['policy']
        (lab.artifacts/policy['dataset_file']).write_bytes(b'changed')
    else:
        with sqlite3.connect(lab.path) as conn:
            if mutation == 'model':
                conn.execute("UPDATE skill_events SET payload=replace(payload,'phase-conditioned','forged') WHERE rowid=1")
            else:
                conn.execute('DELETE FROM skill_events WHERE rowid=(SELECT max(rowid) FROM skill_events)')
    with pytest.raises((SkillConflict, MemoryIntegrityError)):
        lab.execute(envelope, 'alice')


def test_no_grip_policy_fails_without_expert_fallback(lab):
    item = lab.snapshot()['versions'][1]
    weights = np.asarray(item['policy']['weights']).copy()
    weights[:,3:] = 0
    result, _, _ = physics.rollout(*physics.scenario(12001), weights=weights, trace=False)
    assert not result['success'] and result['max_object_height_m'] < .12


def test_stop_is_checked_during_final_settling(lab):
    weights = np.asarray(lab.snapshot()['versions'][1]['policy']['weights'])
    source, target = physics.scenario(12001)
    baseline, _, _ = physics.rollout(source, target, weights=weights, trace=False)
    main_ticks = (baseline['physics_steps'] - 150) // 10
    calls = [0]
    def stop_at_settle():
        calls[0] += 1
        return 'operator_stop_during_settle' if calls[0] > main_ticks else None
    stopped, _, _ = physics.rollout(source, target, weights=weights, trace=False, guard=stop_at_settle)
    assert not stopped['success'] and stopped['reason'] == 'operator_stop_during_settle'


def test_operator_authentication_is_required_for_skill_writes(lab, monkeypatch):
    from app.main import app
    from app.config import settings
    from app.auth.jwt import create_access_token
    from app.skills import service
    from fastapi.testclient import TestClient
    monkeypatch.setattr(settings, 'skill_lab_enabled', True)
    monkeypatch.setattr(service, '_lab', lab)
    client = TestClient(app)
    v, digest = version(lab)
    assert client.post('/skills/train').status_code == 401
    viewer = {'Authorization':'Bearer '+create_access_token('viewer', role='viewer')}
    assert client.post('/skills/train',headers=viewer).status_code == 403
    operator = {'Authorization':'Bearer '+create_access_token('alice', role='operator')}
    assert client.post(f'/skills/{v}/install',json=dict(digest=digest,robot_id='arm-b'),headers=operator).status_code == 200
    assert client.post(f'/skills/{v}/install',json=dict(digest=digest,robot_id='arm-c'),headers=operator).status_code == 409
    assert client.get('/skills').json()['versions'][0]['status'] == 'released'
    monkeypatch.setattr(settings, 'skill_lab_enabled', False)
    assert client.get('/skills').json()['enabled'] is False
    assert client.post('/skills/train',headers=operator).status_code == 503
