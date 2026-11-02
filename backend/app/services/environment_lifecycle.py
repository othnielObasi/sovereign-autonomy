"""Durable propagation from authoritative environment snapshots into memory.

Only simulator identity and deterministic constraint geometry enter this path;
planner prose and noticeboard text cannot create lifecycle events.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import hmac

from app.autonomy.experience import context_from_state
from app.autonomy.permit import canonical
from app.config import settings


def constraints_key(state: dict) -> str:
    zones = [{k: z[k] for k in ("id", "x", "y", "radius", "slow_radius", "max_speed") if k in z}
             for z in state.get("site_constraints") or []]
    return hashlib.sha256(canonical(sorted(zones, key=canonical)).encode()).hexdigest()


class EnvironmentLifecycle:
    def __init__(self, memory, *, clock=time.time):
        self.memory, self.clock = memory, clock
        self._lock = threading.RLock()
        conn = self._db()
        try:
            with conn:
                conn.execute("CREATE TABLE IF NOT EXISTS lifecycle_snapshots (robot TEXT PRIMARY KEY, payload TEXT)")
                conn.execute("CREATE TABLE IF NOT EXISTS lifecycle_events (id TEXT PRIMARY KEY, payload TEXT, signature TEXT)")
        finally:
            conn.close()

    def _db(self):
        return sqlite3.connect(self.memory.db_path, timeout=10)

    def _event(self, event_id, previous, current, reason, *, at=None, cutoff=None):
        conn = self._db()
        try:
            row = conn.execute("SELECT payload,signature FROM lifecycle_events WHERE id=?", (event_id,)).fetchone()
            if row:
                payload = json.loads(row[0])
                if (not hmac.compare_digest(self.memory.sign(payload), row[1])
                        or payload["previous"] != previous or payload["current"] != current or payload["reason"] != reason):
                    raise ValueError("invalid_lifecycle_event")
                return None
        finally:
            conn.close()
        # Invalidation commits first. If recording the event is interrupted, the
        # same deterministic ID safely completes it on the next observation.
        scope = {k: previous[k] for k in ("site_id", "map_version")}
        if previous.get("policy_version"):
            scope["policy_version"] = previous["policy_version"]
        if previous.get("capability_profile_version"):
            scope["capability_profile_version"] = previous["capability_profile_version"]
        if cutoff is not None:
            conn = self._db()
            try:
                old = conn.execute("SELECT payload FROM experience_invalidations WHERE id=?", (event_id,)).fetchone()
                if old:
                    cutoff = json.loads(old[0]).get("before")
            finally:
                conn.close()
        self.memory.invalidate(event_id, scope, reason, before=cutoff)
        event = {"id": event_id, "previous": previous, "current": current, "reason": reason,
                 "observed_at": self.clock(), "source_at": at,
                 "propagation_ms": max(0, (self.clock() - at) * 1000) if at is not None else None}
        conn = self._db()
        try:
            with conn:
                inserted = conn.execute("INSERT OR IGNORE INTO lifecycle_events VALUES (?,?,?)",
                                        (event_id, canonical(event), self.memory.sign(event))).rowcount
        finally:
            conn.close()
        return event if inserted else None

    def observe(self, state: dict, policy_version: str) -> list[dict]:
        from app.services.memory_ledger import MemoryIntegrityError
        try:
            return self._observe(state, policy_version)
        except MemoryIntegrityError as exc:
            # Memory corruption disables reuse; it must not hide fresh telemetry
            # from the independent stop/permit/controller checks.
            self.memory.integrity_error = str(exc)
            return []

    def _observe(self, state: dict, policy_version: str) -> list[dict]:
        current = context_from_state(state, policy_version)
        if not current or not self.memory.enabled:
            return []
        emitted = []
        with self._lock:
            for change in reversed(state.get("environment_changes") or []):
                previous, new = change.get("previous"), change.get("current")
                if (not isinstance(previous, dict) or not isinstance(new, dict)
                        or previous.get("site_id") != current["site_id"]
                        or not previous.get("map_version") or not change.get("id")):
                    continue
                event = self._event("sim:" + change["id"], previous, new, change["reason"], at=change.get("at"))
                if event:
                    emitted.append(event)
            robot = state.get("robot_id", "robot-1")
            conn = self._db()
            try:
                row = conn.execute("SELECT payload FROM lifecycle_snapshots WHERE robot=?", (robot,)).fetchone()
                old = json.loads(row[0]) if row else None
                signature = constraints_key(state) if "site_constraints" in state else (old or {}).get("constraints")
                if old and old["context"] != current:
                    # Version changes exclude all records from the old context.
                    # A->B->A must still produce distinct observations, so include
                    # the previous observation's durable transition counter.
                    revision = old.get("revision", 0) + 1
                    event_id = "context:" + hashlib.sha256(canonical([robot, old, current]).encode()).hexdigest()
                    event = self._event(event_id, old["context"], current, "context_changed", cutoff=self.clock())
                    if event:
                        emitted.append(event)
                else:
                    revision = (old or {}).get("revision", 0)
                if old and old.get("constraints") is not None and old["constraints"] != signature:
                    # Constraint-only changes invalidate earlier observations,
                    # while allowing fresh experience under the same structural map.
                    event_id = "constraints:" + hashlib.sha256(canonical([robot, old, signature]).encode()).hexdigest()
                    cutoff = self.clock()
                    event = self._event(event_id, current, current, "constraints_changed", cutoff=cutoff)
                    if event:
                        emitted.append(event)
                    revision += 1
                # Do not change the persisted snapshot for identical polls: event
                # IDs and cutoffs must survive retry after a partial transaction.
                if old is None or old["context"] != current or old.get("constraints") != signature:
                    payload = {"context": current, "constraints": signature, "revision": revision,
                               "observed_at": self.clock()}
                    with conn:
                        conn.execute("INSERT OR REPLACE INTO lifecycle_snapshots VALUES (?,?)", (robot, canonical(payload)))
            finally:
                conn.close()
        return emitted

    def status(self, limit=30):
        conn = self._db()
        try:
            rows = conn.execute("SELECT payload,signature FROM lifecycle_events ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()
        finally:
            conn.close()
        events = []
        for raw, signature in rows:
            payload = json.loads(raw)
            if not hmac.compare_digest(self.memory.sign(payload), signature):
                raise ValueError("invalid_lifecycle_event")
            events.append(payload)
        return {"events": events}


_lifecycle = None


def get_lifecycle():
    global _lifecycle
    from app.services.route_learning import get_memory
    memory = get_memory()
    if _lifecycle is None or _lifecycle.memory is not memory:
        _lifecycle = EnvironmentLifecycle(memory)
    return _lifecycle
