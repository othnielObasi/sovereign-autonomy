"""Append-only memory inventory with an independently stored signed checkpoint.

SQLite attached rollback-journal transactions commit the inventory and checkpoint
atomically. Protect the checkpoint file separately to detect database rollback;
an administrator controlling both files or the signing key remains out of scope.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3

from app.autonomy.permit import canonical


class MemoryIntegrityError(ValueError):
    pass


class MemoryLedger:
    def __init__(self, path, key):
        self.path, self.key = os.path.abspath(path), key

    def attach(self, conn):
        try:
            self._attach(conn)
        except sqlite3.DatabaseError as exc:
            raise MemoryIntegrityError('memory_storage_unreadable') from exc

    def _attach(self, conn):
        main_path = conn.execute('PRAGMA database_list').fetchone()[2]
        if os.path.normcase(os.path.realpath(main_path)) == os.path.normcase(os.path.realpath(self.path)):
            raise MemoryIntegrityError('memory_checkpoint_requires_separate_file')
        if conn.execute('PRAGMA main.journal_mode').fetchone()[0] not in ('delete', 'truncate', 'persist'):
            raise MemoryIntegrityError('memory_requires_rollback_journal')
        if 'memory_anchor' not in {r[1] for r in conn.execute('PRAGMA database_list')}:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            conn.execute('ATTACH DATABASE ? AS memory_anchor', (self.path,))
        if conn.execute('PRAGMA memory_anchor.journal_mode').fetchone()[0] not in ('delete', 'truncate', 'persist'):
            raise MemoryIntegrityError('memory_requires_rollback_journal')

    def sign(self, value):
        return hmac.new(self.key, ('memory-ledger-v1:' + canonical(value)).encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def inventory(conn):
        inventory = {('experience', r[0]) for r in conn.execute('SELECT id FROM experience')}
        inventory.update(('invalidation', r[0]) for r in conn.execute('SELECT id FROM experience_invalidations'))
        inventory.update(('source', r[0]) for r in conn.execute('SELECT id FROM experience_sources'))
        return inventory

    def initialize(self, conn):
        self.attach(conn)
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('CREATE TABLE IF NOT EXISTS memory_ledger (seq INTEGER PRIMARY KEY, payload TEXT NOT NULL, digest TEXT NOT NULL)')
            conn.execute('CREATE TABLE IF NOT EXISTS memory_ledger_initialized (id INTEGER PRIMARY KEY)')
            conn.execute('CREATE TABLE IF NOT EXISTS memory_anchor.checkpoint (id INTEGER PRIMARY KEY, payload TEXT NOT NULL, signature TEXT NOT NULL)')
            if not conn.execute('SELECT 1 FROM memory_ledger_initialized').fetchone():
                if conn.execute('SELECT 1 FROM memory_anchor.checkpoint').fetchone():
                    raise MemoryIntegrityError('memory_database_rollback_or_replacement')
                conn.execute('INSERT INTO memory_ledger_initialized VALUES (1)')
                self._checkpoint(conn, 0, '0' * 64)
                # Additive migration anchors inventory as found; row signatures
                # are still checked separately. No historical truth is inferred.
                for kind, ident in sorted(self.inventory(conn)):
                    self.append(conn, kind, ident)
            self.verify(conn)

    def _checkpoint(self, conn, seq, digest):
        payload = {'seq': seq, 'digest': digest}
        conn.execute('INSERT OR REPLACE INTO memory_anchor.checkpoint VALUES (1,?,?)',
                     (canonical(payload), self.sign(payload)))

    def verify(self, conn):
        self.attach(conn)
        try:
            previous, seq, expected = '0' * 64, 0, set()
            for number, raw, digest in conn.execute('SELECT seq,payload,digest FROM memory_ledger ORDER BY seq'):
                payload = json.loads(raw)
                if number != seq + 1 or payload['previous'] != previous or not hmac.compare_digest(self.sign(payload), digest):
                    raise MemoryIntegrityError('memory_ledger_corrupt')
                expected.add((payload['kind'], payload['id']))
                previous, seq = digest, number
            checkpoint = conn.execute('SELECT payload,signature FROM memory_anchor.checkpoint WHERE id=1').fetchone()
            if not checkpoint:
                raise MemoryIntegrityError('memory_checkpoint_missing')
            body = json.loads(checkpoint[0])
            if not hmac.compare_digest(self.sign(body), checkpoint[1]) or body != {'seq': seq, 'digest': previous}:
                raise MemoryIntegrityError('memory_checkpoint_mismatch')
            if not expected <= self.inventory(conn):
                raise MemoryIntegrityError('memory_record_deleted')
            return expected
        except (TypeError, KeyError, json.JSONDecodeError, sqlite3.DatabaseError) as exc:
            raise MemoryIntegrityError('memory_ledger_corrupt') from exc

    def append(self, conn, kind, ident):
        last = conn.execute('SELECT seq,digest FROM memory_ledger ORDER BY seq DESC LIMIT 1').fetchone()
        seq, previous = (last[0] + 1, last[1]) if last else (1, '0' * 64)
        payload = {'seq': seq, 'previous': previous, 'kind': kind, 'id': ident}
        digest = self.sign(payload)
        conn.execute('INSERT INTO memory_ledger VALUES (?,?,?)', (seq, canonical(payload), digest))
        self._checkpoint(conn, seq, digest)
