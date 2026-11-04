"""Versioned, operator-released congestion cautions. Advice never conveys authority.

Notice text is screened and retained as untrusted provenance, never fed as planner
instructions. Only corroborated signed congestion cells produce bounded positive
routing costs. The separate append-only ledger detects edits/deletion/rollback
when its checkpoint is protected independently, just like route memory.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager

from app.autonomy.permit import canonical
from app.services.memory_ledger import MemoryLedger, MemoryIntegrityError
from app.services.site_intel.firewall import screen


class ReleaseConflict(ValueError):
    pass


class ReleaseLedger(MemoryLedger):
    @staticmethod
    def inventory(conn):
        return {('lesson_event', row[0]) for row in conn.execute('SELECT id FROM lesson_events')}


class LearningRelease:
    def __init__(self, path, secret, *, clock=time.time):
        self.path, self.clock = str(path), clock
        self.enabled = bool(secret) and len(secret) >= 32
        self.key = hmac.new(secret or b'unset', b'learning-release-v1', hashlib.sha256).digest()
        self.ledger = ReleaseLedger(self.path + '.anchor.sqlite', self.key)
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with self._db() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS lesson_events (id TEXT PRIMARY KEY, payload TEXT NOT NULL, signature TEXT NOT NULL)')
            conn.commit()
            self.ledger.initialize(conn)

    def _db(self):
        return sqlite3.connect(self.path, timeout=10)

    def _sign(self, payload):
        return hmac.new(self.key, canonical(payload).encode(), hashlib.sha256).hexdigest()

    @contextmanager
    def _transaction(self):
        if not self.enabled:
            raise ReleaseConflict('learning_signing_not_configured')
        conn = self._db()
        try:
            self.ledger.attach(conn)
            conn.execute('BEGIN IMMEDIATE')
            self.ledger.verify(conn)
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _states(self, conn):
        states = {}
        for ident, raw, sig in conn.execute('SELECT id,payload,signature FROM lesson_events ORDER BY rowid'):
            event = json.loads(raw)
            if event.get('id') != ident or not hmac.compare_digest(self._sign(event), sig):
                raise MemoryIntegrityError('learning_event_integrity_failed')
            key = (event['lesson_id'], event['version'])
            if event['action'] == 'candidate':
                states[key] = dict(event['candidate'], status='candidate', history=[])
            if key not in states:
                raise MemoryIntegrityError('learning_version_missing')
            state = states[key]
            if event['action'] != 'candidate':
                state['status'] = event['action']
            if 'evaluation' in event:
                state['evaluation'] = event['evaluation']
            state['history'].append(event)
        return states

    def _append(self, conn, lesson_id, version, action, actor, **extra):
        event = dict(id=uuid.uuid4().hex, lesson_id=lesson_id, version=version,
                     action=action, actor=actor, at=self.clock(), **extra)
        conn.execute('INSERT INTO lesson_events VALUES (?,?,?)', (event['id'], canonical(event), self._sign(event)))
        self.ledger.append(conn, 'lesson_event', event['id'])

    def list(self):
        with self._transaction() as conn:
            return list(self._states(conn).values())

    @staticmethod
    def _evidence(candidate, memory, context):
        if candidate['context'] != context:
            raise ReleaseConflict('current_context_mismatch')
        rows = {r['id']: r for r in memory.release_evidence(context)}
        selected = []
        for ident in candidate['evidence_ids']:
            if ident not in rows:
                raise ReleaseConflict('evidence_expired_invalidated_or_unavailable')
            selected.append(rows[ident])
        groups = {}
        for row in selected:
            sources = groups.setdefault((row['i'], row['j']), {})
            sources[row['source_robot_id']] = max(sources.get(row['source_robot_id'], 0), row['delay_s'])
        if not groups or any(len(sources) < 2 for sources in groups.values()):
            raise ReleaseConflict('two_independent_robot_sources_required_per_cell')
        if not any(r['source_robot_id'] == candidate['origin_robot_id'] for r in selected):
            raise ReleaseConflict('origin_has_no_verified_observation')
        return selected, groups

    def propose(self, *, actor, context, origin_robot_id, title, notice, source_url,
                evidence_ids, ttl_s=3600, lesson_id=None, expected_digest=None):
        if not actor or not title.strip() or len(title) > 120 or len(notice) > 700:
            raise ReleaseConflict('invalid_candidate')
        from app.services.route_learning import RouteMemory
        if not RouteMemory._valid_context(context) or not origin_robot_id:
            raise ReleaseConflict('current_context_required')
        if not 60 <= ttl_s <= 86400 or not math.isfinite(ttl_s):
            raise ReleaseConflict('invalid_expiry')
        ids = sorted(set(evidence_ids))
        if not 1 <= len(ids) <= 100 or any(not isinstance(i, str) or len(i) > 1024 for i in ids):
            raise ReleaseConflict('invalid_evidence_ids')
        with self._transaction() as conn:
            states = self._states(conn)
            previous = [s for (ident, _), s in states.items() if ident == lesson_id]
            if lesson_id and not previous:
                raise ReleaseConflict('lesson_not_found')
            version = 1
            if previous:
                current = max(previous, key=lambda s: s['version'])
                if current['digest'] != expected_digest:
                    raise ReleaseConflict('version_conflict')
                version = current['version'] + 1
                self._append(conn, lesson_id, current['version'], 'withdrawn', actor, reason='superseded_by_revision')
            ident = lesson_id or uuid.uuid4().hex
            candidate = dict(lesson_id=ident, version=version, kind='congestion_caution',
                             title=title.strip(), notice=notice, source_url=source_url,
                             context=dict(context), origin_robot_id=origin_robot_id,
                             evidence_ids=ids, created_at=self.clock(), expires_at=self.clock() + ttl_s)
            candidate['digest'] = hashlib.sha256(canonical(candidate).encode()).hexdigest()
            self._append(conn, ident, version, 'candidate', actor, candidate=candidate)
            return self._states(conn)[(ident, version)]

    def transition(self, ident, version, action, digest, actor, *, context, memory, world):
        with self._transaction() as conn:
            states = self._states(conn)
            state = states.get((ident, version))
            if state is None:
                raise ReleaseConflict('lesson_not_found')
            if state['digest'] != digest or version != max(v for i, v in states if i == ident):
                raise ReleaseConflict('version_conflict')
            if action == 'withdraw':
                if state['status'] != 'withdrawn':
                    self._append(conn, ident, version, 'withdrawn', actor)
                return self._states(conn)[(ident, version)]
            expected = {'evaluate': 'candidate', 'approve': 'evaluated', 'release': 'approved'}
            if action not in expected or state['status'] != expected[action]:
                raise ReleaseConflict('invalid_lifecycle_transition')
            if self.clock() >= state['expires_at']:
                raise ReleaseConflict('lesson_expired')
            error = None
            try:
                selected, groups = self._evidence(state, memory, context)
                screening = screen(state['notice'], source='operator-supplied context', url=state['source_url'], title=state['title'])
                if screening.verdict != 'accepted':
                    raise ReleaseConflict('untrusted_context_quarantined')
                from app.services.site_router import _layout
                layout = _layout(world)
                if layout is None:
                    raise ReleaseConflict('layout_unavailable')
                for i, j in groups:
                    if not (0 <= i < layout.nx and 0 <= j < layout.ny) or layout._blocked[i][j]:
                        raise ReleaseConflict('evidence_cell_not_navigable')
            except ReleaseConflict as exc:
                error = str(exc)
            if action == 'evaluate':
                evaluation = dict(passed=error is None, reason=error, digest=digest,
                                  scope='Bounded congestion/source checks; not physical safety certification',
                                  at=self.clock())
                self._append(conn, ident, version, 'rejected' if error else 'evaluated', actor, evaluation=evaluation)
            elif error:
                raise ReleaseConflict(error)
            else:
                self._append(conn, ident, version, 'approved' if action == 'approve' else 'released', actor, digest=digest)
            return self._states(conn)[(ident, version)]

    def retrieve(self, context, robot_id, memory):
        """Always re-read release state and evidence. No recipient or release cache."""
        accepted, excluded, penalties = [], [], {}
        for state in self.list():
            reason = None
            if state['status'] != 'released':
                reason = 'not_released:' + state['status']
            elif not robot_id:
                reason = 'recipient_identity_required'
            elif self.clock() >= state['expires_at']:
                reason = 'lesson_expired'
            else:
                try:
                    selected, groups = self._evidence(state, memory, context)
                    # Positive advisory margin only; never relax geometry or a policy.
                    for cell, sources in groups.items():
                        age = max(0, self.clock() - min(r['observed_at'] for r in selected if (r['i'], r['j']) == cell))
                        penalty = min(2.0, sorted(sources.values(), reverse=True)[1] * .25) * math.exp(-age / memory.decay_s)
                        penalties[cell] = max(penalties.get(cell, 0), penalty)
                except ReleaseConflict as exc:
                    reason = str(exc)
            summary = dict(lesson_id=state['lesson_id'], version=state['version'], digest=state['digest'],
                           recipient_robot_id=robot_id, reason=reason)
            (excluded if reason else accepted).append(summary)
        return dict(accepted=accepted, excluded=excluded, penalties=penalties,
                    movement_authority='unchanged; fresh policy checks and controller permit required')


_release = None


def get_learning_release():
    global _release
    if _release is None:
        from app.config import settings
        _release = LearningRelease(settings.authority_db_path + '.learning.sqlite', settings.permit_secret.encode())
    return _release
