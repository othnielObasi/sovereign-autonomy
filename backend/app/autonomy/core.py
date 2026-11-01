"""Execution authority: world-state versions, kill switches, single-use permits,
durable checkpoints and full-path checks.

Everything here fails closed: when a check cannot be completed, the action is
rejected. Simulation and integration use only; not a safety-rated controller or
a certified emergency stop.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Any, Iterator


def canonical(obj: Any) -> str:
    """Stable JSON used for every digest and signature."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


class Rejected(RuntimeError):
    """An action, permit or update was refused. The message is a short reason code."""


@contextmanager
def _sqlite(path: str, *, write: bool = False) -> Iterator[sqlite3.Connection]:
    """Open a connection and always close it.

    write=True takes the database write lock up front (BEGIN IMMEDIATE), so a
    read-then-write sequence cannot interleave with another writer; it commits
    on success and rolls back on error. Closing matters: an open handle keeps
    the file locked on Windows.
    """
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    try:
        conn.execute("PRAGMA busy_timeout=10000")
        if write:
            conn.execute("BEGIN IMMEDIATE")
        yield conn
        if write:
            conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


@dataclass(frozen=True)
class Action:
    """One concrete robot action. The digest binds a permit to exactly these values."""
    robot_id: str
    mission_id: str
    action_id: str
    kind: str
    params: dict
    world_version: int
    policy_version: str

    def digest(self) -> str:
        return hashlib.sha256(canonical(asdict(self)).encode()).hexdigest()


class WorldState:
    """Latest observed state per robot, with a version that only moves forward."""

    def __init__(self, max_age_s: float = 2.0):
        self.max_age_s = max_age_s
        self._states: dict[str, dict] = {}
        self._lock = threading.RLock()

    def update(self, robot_id: str, version: int, state: dict, observed_at: float | None = None) -> None:
        with self._lock:
            old = self._states.get(robot_id)
            if old and version <= old["version"]:
                raise Rejected("non_monotonic_world_version")
            self._states[robot_id] = {
                "version": version,
                "state": state,
                "observed_at": time.time() if observed_at is None else observed_at,
            }

    def current_version(self, robot_id: str) -> int | None:
        with self._lock:
            item = self._states.get(robot_id)
            return item["version"] if item else None

    def require(self, robot_id: str, version: int) -> dict:
        """Return the state only if it is the expected version and still fresh."""
        with self._lock:
            item = self._states.get(robot_id)
            if not item or item["version"] != version:
                raise Rejected("world_version_mismatch")
            now = time.time()
            if now - item["observed_at"] > self.max_age_s or item["observed_at"] > now + 1:
                raise Rejected("stale_world_state")
            return dict(item["state"])


class KillSwitch:
    """Software authority revocation at global, robot, mission or agent scope.

    Every activation or reset bumps the epoch, which voids all outstanding permits.
    A hardware stop must be integrated separately.
    """
    SCOPES = frozenset({"global", "robot", "mission", "agent"})

    def __init__(self):
        self._locked: set[tuple[str, str]] = set()
        self._epoch = 0
        self._lock = threading.RLock()

    @property
    def epoch(self) -> int:
        with self._lock:
            return self._epoch

    def active(self) -> list[tuple[str, str]]:
        with self._lock:
            return sorted(self._locked)

    def activate(self, scope: str, identifier: str = "*") -> None:
        if scope not in self.SCOPES:
            raise ValueError("invalid_scope")
        with self._lock:
            self._locked.add((scope, identifier))
            self._epoch += 1

    def reset(self, scope: str, identifier: str, *, authorized: bool) -> None:
        if not authorized:
            raise Rejected("reset_requires_authorization")
        with self._lock:
            self._locked.discard((scope, identifier))
            self._epoch += 1

    def require_active(self, action: Action, agent_id: str = "") -> None:
        keys = [("global", "*"), ("robot", action.robot_id), ("mission", action.mission_id)]
        if agent_id:
            keys.append(("agent", agent_id))
        with self._lock:
            if any(k in self._locked for k in keys):
                raise Rejected("kill_switch_active")


class PermitStore:
    """Signed, short-lived, single-use permits bound to one exact action.

    Issue permits only from inside the governance boundary (after the gate has
    approved the action); never expose `issue` to callers outside it.
    Uses local SQLite; a multi-replica gateway needs a shared transactional store.
    """

    def __init__(self, path: str, secret: bytes, kills: KillSwitch, world: WorldState):
        if len(secret) < 32:
            raise ValueError("permit_secret_too_short")
        self.path, self.secret, self.kills, self.world = path, secret, kills, world
        self._lock = threading.RLock()
        with _sqlite(self.path, write=True) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS permits ("
                "id TEXT PRIMARY KEY, payload TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0)"
            )

    def _sign(self, raw: str) -> str:
        return hmac.new(self.secret, raw.encode(), hashlib.sha256).hexdigest()

    def issue(self, action: Action, *, approved: bool, ttl_s: float = 5.0, agent_id: str = "") -> str:
        if not approved:
            raise Rejected("governance_denied")
        self.kills.require_active(action, agent_id)
        self.world.require(action.robot_id, action.world_version)
        if not (0 < ttl_s <= 60):
            raise ValueError("invalid_ttl")
        payload = {
            "id": str(uuid.uuid4()),
            "digest": action.digest(),
            "robot": action.robot_id,
            "mission": action.mission_id,
            "world_version": action.world_version,
            "agent": agent_id,
            "epoch": self.kills.epoch,
            "expires": time.time() + ttl_s,
        }
        raw = canonical(payload)
        with _sqlite(self.path, write=True) as c:
            c.execute("INSERT INTO permits(id,payload) VALUES (?,?)", (payload["id"], raw))
        return canonical({"payload": payload, "signature": self._sign(raw)})

    def consume(self, token: str, action: Action) -> None:
        """Verify and atomically use up a permit. Raises Rejected on any failure."""
        try:
            envelope = json.loads(token)
            payload, signature = envelope["payload"], envelope["signature"]
            raw = canonical(payload)
        except (ValueError, KeyError, TypeError) as exc:
            raise Rejected("malformed_permit") from exc
        if not isinstance(signature, str) or not hmac.compare_digest(signature, self._sign(raw)):
            raise Rejected("invalid_signature")
        if (payload["digest"] != action.digest() or payload["robot"] != action.robot_id
                or payload["mission"] != action.mission_id):
            raise Rejected("action_mismatch")
        with self._lock:
            self.kills.require_active(action, payload["agent"])
            if payload["epoch"] != self.kills.epoch:
                raise Rejected("authority_epoch_changed")
            self.world.require(action.robot_id, action.world_version)
            if time.time() >= payload["expires"]:
                raise Rejected("permit_expired")
            with _sqlite(self.path, write=True) as c:
                row = c.execute("SELECT payload,used FROM permits WHERE id=?", (payload["id"],)).fetchone()
                if not row or row[0] != raw or row[1]:
                    raise Rejected("unknown_or_replayed_permit")
                c.execute("UPDATE permits SET used=1 WHERE id=?", (payload["id"],))


class CheckpointStore:
    """Transactional mission state with an append-only, hash-chained event journal.

    Each dispatched action is IN_DOUBT until reconciled against the controller;
    a mission with unreconciled actions must not resume.
    """

    def __init__(self, path: str):
        self.path = path
        with _sqlite(self.path, write=True) as c:
            c.execute("CREATE TABLE IF NOT EXISTS missions (id TEXT PRIMARY KEY, version INTEGER NOT NULL, state TEXT NOT NULL)")
            c.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, mission TEXT, event TEXT, previous_hash TEXT, event_hash TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS actions (id TEXT PRIMARY KEY, mission TEXT, status TEXT)")

    def checkpoint(self, mission: str, state: dict, expected_version: int | None = None) -> int:
        with _sqlite(self.path, write=True) as c:
            row = c.execute("SELECT version FROM missions WHERE id=?", (mission,)).fetchone()
            old = row[0] if row else 0
            if expected_version is not None and old != expected_version:
                raise Rejected("checkpoint_version_conflict")
            new = old + 1
            c.execute(
                "INSERT INTO missions(id,version,state) VALUES (?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET version=excluded.version,state=excluded.state",
                (mission, new, canonical(state)),
            )
            self._event(c, mission, {"kind": "checkpoint", "version": new, "state": state})
            return new

    def load(self, mission: str) -> tuple[int, dict] | None:
        with _sqlite(self.path) as c:
            row = c.execute("SELECT version,state FROM missions WHERE id=?", (mission,)).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    def begin_action(self, action: Action) -> None:
        with _sqlite(self.path, write=True) as c:
            try:
                c.execute("INSERT INTO actions VALUES (?,?,?)", (action.action_id, action.mission_id, "IN_DOUBT"))
            except sqlite3.IntegrityError as exc:
                raise Rejected("duplicate_action_requires_reconciliation") from exc
            self._event(c, action.mission_id, {"kind": "action_dispatched", "action": action.action_id})

    def reconcile(self, action_id: str, *, controller_verified: bool, executed: bool) -> None:
        if not controller_verified:
            raise Rejected("controller_verification_required")
        with _sqlite(self.path, write=True) as c:
            row = c.execute("SELECT mission,status FROM actions WHERE id=?", (action_id,)).fetchone()
            if not row:
                raise Rejected("unknown_action")
            status = "COMPLETED" if executed else "NOT_EXECUTED"
            c.execute("UPDATE actions SET status=? WHERE id=?", (status, action_id))
            self._event(c, row[0], {"kind": "reconciled", "action": action_id, "status": status})

    def in_doubt(self, mission: str) -> list[str]:
        with _sqlite(self.path) as c:
            rows = c.execute("SELECT id FROM actions WHERE mission=? AND status='IN_DOUBT'", (mission,)).fetchall()
        return [r[0] for r in rows]

    def require_reconciled(self, mission: str) -> None:
        if self.in_doubt(mission):
            raise Rejected("unreconciled_actions")

    @staticmethod
    def _event(c: sqlite3.Connection, mission: str, event: dict) -> None:
        row = c.execute("SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        prev = row[0] if row else "0" * 64
        raw = canonical({"mission": mission, "event": event, "previous_hash": prev})
        digest = hashlib.sha256(raw.encode()).hexdigest()
        c.execute(
            "INSERT INTO events(mission,event,previous_hash,event_hash) VALUES (?,?,?,?)",
            (mission, canonical(event), prev, digest),
        )

    def verify_chain(self) -> bool:
        """True if no journal entry was edited, removed or reordered."""
        prev = "0" * 64
        with _sqlite(self.path) as c:
            rows = c.execute("SELECT mission,event,previous_hash,event_hash FROM events ORDER BY seq").fetchall()
        for mission, event, old, digest in rows:
            expected = hashlib.sha256(
                canonical({"mission": mission, "event": json.loads(event), "previous_hash": old}).encode()
            ).hexdigest()
            if old != prev or expected != digest:
                return False
            prev = digest
        return True


class TrajectoryValidator:
    """Samples the whole path, not just its endpoints.

    Point-robot model: no footprint, braking distance or moving obstacles yet.
    """

    def __init__(self, *, clearance: float = 0.5, resolution: float = 0.1):
        self.clearance, self.resolution = clearance, resolution

    def validate(
        self,
        waypoints: list[tuple[float, float]],
        bounds: tuple[float, float, float, float],
        obstacles: list[tuple[float, float, float]],
        restricted: list[tuple[float, float, float, float]] = (),
    ) -> bool:
        if not waypoints:
            raise Rejected("empty_trajectory")
        segments = [(waypoints[0], waypoints[0])] if len(waypoints) == 1 else list(zip(waypoints, waypoints[1:]))
        for (x0, y0), (x1, y1) in segments:
            steps = max(1, math.ceil(math.hypot(x1 - x0, y1 - y0) / self.resolution))
            for i in range(steps + 1):
                t = i / steps
                x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
                if not (bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]):
                    raise Rejected("trajectory_out_of_bounds")
                if any(a <= x <= c and b <= y <= d for a, b, c, d in restricted):
                    raise Rejected("trajectory_restricted_zone")
                if any(math.hypot(x - ox, y - oy) < r + self.clearance for ox, oy, r in obstacles):
                    raise Rejected("trajectory_obstacle_clearance")
        return True
