"""Durable, operator-controlled CPU skill lab. Navigation permits are not reused.

Single-process worker, one bounded physics operation at a time. The signed event
ledger and independently checkpointed inventory detect edits/deletions/rollback.
Skill grants bind a model, recipient, environment and task, expire quickly and
are consumed before stepping physics. This is a lab controller, not hardware.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
import hashlib
import hmac
import importlib.util
import io
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time

from app.autonomy.permit import canonical
from app.services.memory_ledger import MemoryLedger, MemoryIntegrityError
from . import physics


class SkillConflict(ValueError):
    pass


class SkillLedger(MemoryLedger):
    @staticmethod
    def inventory(conn):
        return {('skill_event', row[0]) for row in conn.execute('SELECT id FROM skill_events')}


class SkillLab:
    def __init__(self, path, secret, *, clock=time.time):
        self.path, self.clock = str(path), clock
        self.key = hmac.new(secret or b'unset', b'cpu-skill-lab-v1', hashlib.sha256).digest()
        self.enabled = len(secret) >= 32
        self.ledger = SkillLedger(self.path + '.anchor.sqlite', self.key)
        self.artifacts = Path(self.path + '.artifacts')
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self.worker = threading.Lock()
        self.busy = False
        self._guard_cached = None
        self._guard_checked = 0.
        with self.db() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS skill_events (id TEXT PRIMARY KEY, payload TEXT NOT NULL, signature TEXT NOT NULL)')
            conn.commit()
            self.ledger.initialize(conn)

    def db(self):
        return sqlite3.connect(self.path, timeout=10)

    def sign(self, value):
        return hmac.new(self.key, canonical(value).encode(), hashlib.sha256).hexdigest()

    @contextmanager
    def transaction(self):
        if not self.enabled:
            raise SkillConflict('skill_signing_not_configured')
        conn = self.db()
        try:
            self.ledger.attach(conn); conn.execute('BEGIN IMMEDIATE'); self.ledger.verify(conn)
            yield conn
            conn.commit()
        except Exception:
            conn.rollback(); raise
        finally:
            conn.close()

    def append(self, conn, action, actor, **values):
        event = dict(id=secrets.token_hex(16), action=action, actor=actor, at=self.clock(), **values)
        conn.execute('INSERT INTO skill_events VALUES (?,?,?)', (event['id'], canonical(event), self.sign(event)))
        self.ledger.append(conn, 'skill_event', event['id'])
        self._guard_cached = None
        return event

    def state(self, conn):
        versions, grants, attempts, installed, stopped, generation = {}, {}, [], {}, False, 0
        for ident, raw, signature in conn.execute('SELECT id,payload,signature FROM skill_events ORDER BY rowid'):
            e = json.loads(raw)
            if e['id'] != ident or not hmac.compare_digest(self.sign(e), signature):
                raise MemoryIntegrityError('skill_event_integrity_failed')
            action = e['action']
            if action == 'trained':
                versions[e['version']] = dict(version=e['version'], digest=e['digest'], policy=e['policy'],
                    status='trained', history=[], created_at=e['at'], demonstration=e.get('demonstration'))
            if 'version' in e and action in ('trained','evaluated','approved','released','withdrawn'):
                version = versions[e['version']]
                version['status'] = action
                version['history'].append({k:e[k] for k in ('action','actor','at')})
                if 'evaluation' in e: version['evaluation'] = e['evaluation']
                if 'expires_at' in e: version['expires_at'] = e['expires_at']
            if action == 'installed': installed[e['robot_id']] = dict(version=e['version'], digest=e['digest'])
            if action == 'grant': grants[e['permit']['nonce']] = dict(permit=e['permit'], used=False)
            if action == 'started': grants[e['nonce']]['used'] = True
            if action in ('started','finished','failed'):
                attempts.append(e)
            if action in ('stop','reset'):
                stopped = action == 'stop'
                generation += 1
        return dict(versions=versions, grants=grants, installed=installed, stopped=stopped,
                    generation=generation, attempts=attempts)

    def snapshot(self):
        with self.transaction() as conn:
            return self.state(conn)

    @contextmanager
    def work(self):
        if not self.worker.acquire(blocking=False):
            raise SkillConflict('skill_worker_busy')
        self.busy = True
        try:
            yield
        finally:
            self.busy = False; self.worker.release()

    def guard(self, started, version=None, *, wall_limit=30., generation=None, fleet_epoch=None):
        if time.perf_counter() - started > wall_limit:
            return 'controller_wall_timeout'
        # One in-process physics worker. Every mutation invalidates this cache;
        # periodic verification also detects out-of-band edits. Do not run a
        # multi-file SQLite checkpoint transaction at every 500 Hz physics step.
        now = time.perf_counter()
        if self._guard_cached is None or now - self._guard_checked >= .1:
            self._guard_cached = self.snapshot()
            self._guard_checked = now
        state = self._guard_cached
        if state['stopped']:
            return 'lab_stop_latched'
        if generation is not None and generation != state['generation']:
            return 'controller_generation_changed'
        if version is not None:
            item = state['versions'][version]
            if item['status'] != 'released' or self.clock() >= item['expires_at']:
                return 'release_withdrawn_or_expired'
        # A fleet stop also stops the lab; no network/model decision is involved.
        from app.services.execution_authority import get_authority
        authority = get_authority()
        if fleet_epoch is not None and authority.kills.epoch != fleet_epoch:
            return 'fleet_authority_changed'
        if any(scope == 'global' for scope, _ in authority.kills.active()):
            return 'fleet_stop_latched'
        return None

    def artifact(self, item):
        import mujoco
        import numpy as np
        policy = item['policy']
        if physics.digest(policy) != item['digest'] or policy['environment_hash'] != physics.environment_hash():
            raise SkillConflict('artifact_or_environment_mismatch')
        if (policy['profile'] != physics.PROFILE or policy['runtime_hash'] != self.runtime_hash()
                or policy['engine_version'] != mujoco.__version__):
            raise SkillConflict('skill_runtime_or_profile_mismatch')
        weights = np.asarray(policy['weights'])
        if weights.shape != (64,5) or not np.isfinite(weights).all():
            raise SkillConflict('invalid_skill_policy')
        data = (self.artifacts / policy['dataset_file']).read_bytes()
        if hashlib.sha256(data).hexdigest() != policy['dataset_sha256']:
            raise SkillConflict('dataset_integrity_failed')
        return policy

    def train(self, actor):
        import numpy as np
        with self.work():
            started = time.perf_counter()
            generation = self.snapshot()['generation']
            if self.guard(started): raise SkillConflict('stop_latched')
            policy = physics.train(guard=lambda: self.guard(started, wall_limit=90., generation=generation))
            dataset = policy.pop('_dataset')
            buffer = io.BytesIO(); np.savez_compressed(buffer, **dataset)
            blob = buffer.getvalue()
            name = secrets.token_hex(16) + '.npz'
            with (self.artifacts / name).open('xb') as f: f.write(blob)
            policy.update(dataset_file=name, dataset_sha256=hashlib.sha256(blob).hexdigest(),
                          source_robot_id='arm-a', skill='pick-place-container', runtime_hash=self.runtime_hash())
            import mujoco
            policy['engine_version'] = mujoco.__version__
            demonstration, _, _ = physics.rollout(*physics.scenario(71), guard=lambda: self.guard(started, wall_limit=90., generation=generation))
            policy['demonstration_hash'] = physics.digest(demonstration)
            digest = physics.digest(policy)
            with self.transaction() as conn:
                version = max(self.state(conn)['versions'], default=0) + 1
                self.append(conn, 'trained', actor, version=version, digest=digest, policy=policy, demonstration=demonstration)
            return dict(version=version, digest=digest, status='trained')

    def transition(self, version, action, expected_digest, actor):
        if action not in ('evaluate','approve','release','withdraw'):
            raise SkillConflict('unknown_skill_action')
        with (nullcontext() if action == 'withdraw' else self.work()):
            state = self.snapshot()
            item = state['versions'].get(version)
            if not item or not hmac.compare_digest(item['digest'], expected_digest):
                raise SkillConflict('skill_version_conflict')
            evaluation = None
            if action == 'evaluate':
                if item['status'] != 'trained': raise SkillConflict('invalid_skill_transition')
                started = time.perf_counter()
                policy = self.artifact(item)
                evaluation = physics.evaluate(policy, guard=lambda: self.guard(started, wall_limit=120., generation=state['generation']))
                # A no-grip ablation must fail: policy outputs have a causal role.
                import numpy as np
                ablated = np.asarray(policy['weights']).copy(); ablated[:, 3:] = 0
                baseline, _, _ = physics.rollout(*physics.scenario(9001, heldout=True), weights=ablated,
                                                trace=False, guard=lambda: self.guard(started, wall_limit=120., generation=state['generation']))
                evaluation['no_grip_ablation_success'] = baseline['success']
                evaluation['passed'] = evaluation['passed'] and not baseline['success']
            with self.transaction() as conn:
                current = self.state(conn)['versions'][version]
                expected = {'evaluate':'trained', 'approve':'evaluated', 'release':'approved'}
                if action != 'withdraw' and current['status'] != expected[action]:
                    raise SkillConflict('invalid_skill_transition')
                if action in ('approve','release') and not current.get('evaluation', {}).get('passed'):
                    raise SkillConflict('evaluation_not_passed')
                if action != 'withdraw': self.artifact(current)
                values = dict(version=version, digest=expected_digest)
                if evaluation is not None: values['evaluation'] = evaluation
                if action == 'release': values['expires_at'] = self.clock() + 3600
                self.append(conn, {'evaluate':'evaluated','approve':'approved','release':'released','withdraw':'withdrawn'}[action], actor, **values)
            return dict(version=version, status={'evaluate':'evaluated','approve':'approved','release':'released','withdraw':'withdrawn'}[action], evaluation=evaluation)

    @staticmethod
    def compatible(robot_id):
        if robot_id not in ('arm-a','arm-b'):
            raise SkillConflict('recipient_capability_profile_mismatch')

    def released(self, state, version, digest):
        item = state['versions'].get(version)
        if not item or item['digest'] != digest: raise SkillConflict('skill_version_conflict')
        if item['status'] != 'released' or self.clock() >= item['expires_at']:
            raise SkillConflict('skill_not_currently_released')
        self.artifact(item)
        return item

    def install(self, version, digest, robot_id, actor):
        self.compatible(robot_id)
        with self.transaction() as conn:
            self.released(self.state(conn), version, digest)
            self.append(conn, 'installed', actor, version=version, digest=digest, robot_id=robot_id)
        return dict(installed=True, movement_authority=False)

    def grant(self, version, digest, robot_id, actor, *, seed=12001):
        self.compatible(robot_id)
        if not 12001 <= seed <= 12100: raise SkillConflict('execution_seed_out_of_bounds')
        with self.transaction() as conn:
            state = self.state(conn)
            self.released(state, version, digest)
            if state['stopped']: raise SkillConflict('lab_stop_latched')
            if state['installed'].get(robot_id) != dict(version=version, digest=digest):
                raise SkillConflict('exact_skill_version_not_installed')
            permit = dict(nonce=secrets.token_hex(16), version=version, digest=digest, robot_id=robot_id,
                profile=physics.PROFILE, environment_hash=physics.environment_hash(), seed=seed,
                generation=state['generation'], fleet_epoch=self.fleet_epoch(),
                expires_at=int(self.clock())+30, max_control_ticks=1200, max_wall_s=30)  # ints survive a browser JSON round trip
            self.append(conn, 'grant', actor, permit=permit)
        return dict(permit=permit, signature=self.sign(permit))

    def execute(self, envelope, actor):
        with self.work():
            permit, signature = envelope['permit'], envelope['signature']
            if not hmac.compare_digest(self.sign(permit), signature): raise SkillConflict('invalid_skill_grant_signature')
            with self.transaction() as conn:
                state = self.state(conn)
                issued = state['grants'].get(permit['nonce'])
                if not issued or issued['permit'] != permit or issued['used']:
                    raise SkillConflict('skill_grant_unknown_or_used')
                if self.clock() >= permit['expires_at']: raise SkillConflict('skill_grant_expired')
                if state['stopped']: raise SkillConflict('lab_stop_latched')
                if state['generation'] != permit['generation'] or self.fleet_epoch() != permit['fleet_epoch']:
                    raise SkillConflict('skill_grant_revoked')
                self.compatible(permit['robot_id'])
                item = self.released(state, permit['version'], permit['digest'])
                if state['installed'].get(permit['robot_id']) != dict(version=permit['version'], digest=permit['digest']):
                    raise SkillConflict('installed_skill_changed')
                self.append(conn, 'started', actor, version=permit['version'], nonce=permit['nonce'], robot_id=permit['robot_id'], digest=permit['digest'])
                policy = item['policy']
            started = time.perf_counter()
            try:
                import numpy as np
                ticks = [0]
                def guard():
                    ticks[0] += 1
                    if ticks[0] > permit['max_control_ticks']: return 'controller_tick_limit'
                    return self.guard(started, permit['version'], wall_limit=permit['max_wall_s'],
                                      generation=permit['generation'], fleet_epoch=permit['fleet_epoch'])
                result, _, _ = physics.rollout(*physics.scenario(permit['seed'], heldout=True),
                                              weights=np.asarray(policy['weights']), guard=guard)
            except Exception as exc:
                with self.transaction() as conn:
                    self.append(conn, 'failed', actor, nonce=permit['nonce'], reason=type(exc).__name__)
                raise
            with self.transaction() as conn:
                self.append(conn, 'finished', actor, nonce=permit['nonce'], robot_id=permit['robot_id'],
                            version=permit['version'], digest=permit['digest'], result=result)
            return dict(nonce=permit['nonce'], version=permit['version'], digest=permit['digest'],
                        robot_id=permit['robot_id'], result=result, result_hash=physics.digest(result))

    def stop(self, actor, *, reset=False):
        # Deliberately does not acquire the physics worker lock: it must interrupt it.
        with self.transaction() as conn:
            self.append(conn, 'reset' if reset else 'stop', actor)
        return dict(stopped=not reset)

    @staticmethod
    def fleet_epoch():
        from app.services.execution_authority import get_authority
        return get_authority().kills.epoch

    @staticmethod
    def runtime_hash():
        return hashlib.sha256(Path(__file__).read_bytes() + Path(physics.__file__).read_bytes()).hexdigest()

    def overview(self):
        state = self.snapshot()
        versions = []
        for item in state['versions'].values():
            policy = item['policy']
            versions.append(dict(version=item['version'], digest=item['digest'], status=item['status'],
                expires_at=item.get('expires_at'), history=item['history'], evaluation=item.get('evaluation'),
                training={k:v for k,v in policy.items() if k not in ('weights','_dataset','demonstrations_summary')}))
            versions[-1]['demonstration'] = item.get('demonstration')
        return dict(enabled=True, available=bool(importlib.util.find_spec('mujoco')), busy=self.busy,
                    versions=versions, installed=state['installed'], stopped=state['stopped'],
                    attempts=state['attempts'][-8:], profile=physics.PROFILE,
                    robots=[dict(id='arm-a', compatible=True),dict(id='arm-b', compatible=True),dict(id='arm-c', compatible=False)],
                    scope='CPU physics lab; fixed phases and measured coordinates; not physical-robot validation')


_lab = None


def get_skill_lab():
    global _lab
    if _lab is None:
        from app.config import settings
        _lab = SkillLab(settings.authority_db_path + '.skills.sqlite', settings.permit_secret.encode())
    return _lab
