"""Durable controller admission evidence; no backend dependencies.

ACCEPTED means a command was admitted, not that a waypoint was reached. Writing
before assigning the target deliberately prefers a lost move over repeating one
after a crash between the journal write and the target assignment.
"""
import os
import sqlite3
import time
import json
import uuid
import hashlib
from contextlib import contextmanager

from .permit import action_digest, canonical


class ControllerJournal:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with self._db() as c:
            c.execute("CREATE TABLE IF NOT EXISTS admissions (action_id TEXT PRIMARY KEY, permit_id TEXT UNIQUE, "
                      "robot_id TEXT, digest TEXT, accepted_at REAL)")
            c.execute("CREATE TABLE IF NOT EXISTS stops (robot_id TEXT PRIMARY KEY, reason TEXT, since REAL)")
            c.execute("CREATE TABLE IF NOT EXISTS releases (id TEXT PRIMARY KEY)")
            c.execute("CREATE TABLE IF NOT EXISTS environments (site_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            c.execute("CREATE TABLE IF NOT EXISTS environment_changes (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")

    def environment(self, base: dict, reason: str | None = None) -> dict:
        """Durable operational map generation; ordinary actor motion never changes it."""
        with self._db() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT payload FROM environments WHERE site_id=?", (base["site_id"],)).fetchone()
            old = json.loads(row[0]) if row else None
            changed = old and any(old["base"].get(k) != v for k, v in base.items())
            if old and (reason or changed):
                event_id = uuid.uuid4().hex
                current = dict(base, map_version=hashlib.sha256(canonical([base, event_id]).encode()).hexdigest())
                event = {"id": event_id, "reason": reason or "layout_or_capabilities_changed", "at": time.time(),
                         "previous": old["current"], "current": current}
                c.execute("INSERT INTO environment_changes VALUES (?,?)", (event_id, canonical(event)))
            elif old:
                return old["current"]
            else:
                current = dict(base)
            c.execute("INSERT OR REPLACE INTO environments VALUES (?,?)",
                      (base["site_id"], canonical({"base": base, "current": current})))
            return current

    def environment_changes(self) -> list[dict]:
        with self._db() as c:
            return [json.loads(r[0]) for r in c.execute("SELECT payload FROM environment_changes ORDER BY rowid DESC LIMIT 50")]

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(self.path, timeout=5)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def seen(self, permit_id: str) -> bool:
        with self._db() as c:
            return c.execute("SELECT 1 FROM admissions WHERE permit_id=?", (permit_id,)).fetchone() is not None

    def accept(self, action: dict, permit_id: str) -> None:
        with self._db() as c:
            c.execute("INSERT INTO admissions VALUES (?,?,?,?,?)",
                      (action["action_id"], permit_id, action["robot_id"], action_digest(action), time.time()))

    def accepted(self, robot_id: str) -> list[str]:
        with self._db() as c:
            return [r[0] for r in c.execute("SELECT action_id FROM admissions WHERE robot_id=? "
                                           "ORDER BY accepted_at DESC LIMIT 200", (robot_id,))]

    def stops(self) -> dict:
        with self._db() as c:
            return {rid: {"reason": reason, "since": since} for rid, reason, since in
                    c.execute("SELECT robot_id,reason,since FROM stops")}

    def stop(self, robot_id: str, reason: str) -> None:
        with self._db() as c:
            c.execute("INSERT OR IGNORE INTO stops VALUES (?,?,?)", (robot_id, reason, time.time()))

    def release(self, robot_id: str, token_id: str) -> None:
        with self._db() as c:
            c.execute("INSERT INTO releases VALUES (?)", (token_id,))
            c.execute("DELETE FROM stops WHERE robot_id=?", (robot_id,))
