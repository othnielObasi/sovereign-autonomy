"""Learned routing over a NetworkX graph, fed only by signed experience.

The warehouse floor becomes a graph: one node per free 0.5 m grid cell, edges to
its eight neighbours. Two kinds of edge data are kept apart:

- Authoritative restrictions: racking, walls and hazard exclusion zones. An edge
  touching a blocked cell is `allowed=False`, and learning never changes that.
- Learned delays: where past runs were slowed or stopped by the gate, the cells
  carry an expected delay, so the router prefers a slightly longer route that has
  gone smoothly before.

Experience is written by the backend at the end of each run, one signed record per
cell. On load every record is verified; a record that fails (for example one
planted directly in the database to make a dangerous route look fast) is
quarantined and ignored. A signature proves who wrote a record, not that it is true.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.autonomy.intelligence import RouteGraph
from app.autonomy.permit import canonical
from app.autonomy.experience import CONTEXT_FIELDS, context_from_state, context_key
from app.config import settings

logger = logging.getLogger("app.route_learning")

Cell = Tuple[int, int]
# Expected seconds lost when the gate acted in a cell
DELAY_FOR = {"STOP": 4.0, "DENIED": 4.0, "REPLAN": 3.0, "SLOW": 1.5, "NEEDS_REVIEW": 2.0}
DELAY_WEIGHT = 0.6   # route cost per second of expected delay (distance is in metres)


class RouteMemory:
    def __init__(self, db_path: Optional[str] = None, secret: Optional[bytes] = None,
                 *, clock=time.time, ttl_s=None, decay_s=None):
        self.db_path = db_path or settings.authority_db_path
        base = secret if secret is not None else settings.permit_secret.encode()
        # A separate key derived from the permit secret, used only for experience records
        self.key = hmac.new(base or b"unset", b"experience-records-v1", hashlib.sha256).digest()
        self.enabled = bool(base) and len(base) >= 32
        self._lock = threading.Lock()
        self.clock = clock
        self.ttl_s = settings.experience_ttl_s if ttl_s is None else ttl_s
        self.decay_s = settings.experience_decay_s if decay_s is None else decay_s
        if not (math.isfinite(self.ttl_s) and self.ttl_s > 0
                and math.isfinite(self.decay_s) and self.decay_s > 0):
            raise ValueError("invalid_experience_freshness_settings")
        self.last_retrieval: List[Dict[str, Any]] = []
        conn = self._db()
        try:
            with conn:
                conn.execute("CREATE TABLE IF NOT EXISTS experience (id TEXT PRIMARY KEY, run_id TEXT, i INTEGER, "
                             "j INTEGER, delay_s REAL, kind TEXT, observed_at REAL, signature TEXT)")
                # Additive migration keeps legacy rows intact and inspectable.
                conn.execute("CREATE TABLE IF NOT EXISTS experience_context "
                             "(id TEXT PRIMARY KEY, metadata TEXT NOT NULL)")
                conn.execute("CREATE TABLE IF NOT EXISTS experience_invalidations "
                             "(id TEXT PRIMARY KEY, payload TEXT NOT NULL, signature TEXT NOT NULL)")
        finally:
            conn.close()

    def _db(self) -> sqlite3.Connection:
        import os
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def sign(self, body: Dict[str, Any]) -> str:
        return hmac.new(self.key, canonical(body).encode(), hashlib.sha256).hexdigest()

    # --- writing ----------------------------------------------------------------------------

    def record(self, run_id: str, observations: Sequence[Tuple[Cell, float, str]], *,
               context=None, source_robot_id=None, observed_at=None) -> int:
        """Store signed observations (cell, delay seconds, what happened). Idempotent per run+cell+kind."""
        if (not self.enabled or not observations or not self._valid_context(context)
                or not isinstance(source_robot_id, str) or not source_robot_id):
            return 0
        rows = []
        now = float(self.clock())
        observed = now if observed_at is None else float(observed_at)
        if not math.isfinite(observed) or observed > now + 1:
            raise ValueError("invalid_observation_time")
        metadata = {"schema_version": 2, "context": dict(context), "source_robot_id": source_robot_id,
                    "validated_at": now, "experience_type": "historical_congestion"}
        for (i, j), delay, kind in observations:
            if not math.isfinite(delay) or not 0 <= delay <= 60 or kind not in DELAY_FOR:
                raise ValueError("invalid_experience_data")
            body = {"id": f"{run_id}:{i}:{j}:{kind}:{context_key(context)}:{source_robot_id}",
                    "run_id": run_id, "i": int(i), "j": int(j),
                    "delay_s": round(float(delay), 3), "kind": kind, "observed_at": observed}
            rows.append((body["id"], run_id, body["i"], body["j"], body["delay_s"], kind, body["observed_at"],
                         self.sign(dict(body, metadata=metadata))))
        conn = self._db()
        try:
            with conn:
                inserted = 0
                for row in rows:
                    if conn.execute("INSERT OR IGNORE INTO experience VALUES (?,?,?,?,?,?,?,?)", row).rowcount:
                        conn.execute("INSERT INTO experience_context VALUES (?,?)", (row[0], canonical(metadata)))
                        inserted += 1
        finally:
            conn.close()
        return inserted

    def record_run(self, db, run_id: str) -> int:
        """Turn one run's gate decisions into experience: where it was slowed or stopped."""
        from app.db.models import GovernanceDecisionRecord
        from bench.world import GRID_M
        records = db.query(GovernanceDecisionRecord).filter(GovernanceDecisionRecord.run_id == run_id).all()
        from datetime import timezone
        groups = {}
        for r in records:
            kind = r.policy_state if r.policy_state in DELAY_FOR else (r.decision if r.decision in DELAY_FOR else None)
            if not kind:
                continue
            try:
                tel = json.loads(r.telemetry_summary or "{}")
                cell = (int(float(tel["x"]) / GRID_M), int(float(tel["y"]) / GRID_M))
                context = tel.get("experience_context")
                source = tel.get("source_robot_id")
                if not self._valid_context(context) or context["policy_version"] != r.policy_version or not source:
                    continue
                observed = r.ts.replace(tzinfo=timezone.utc).timestamp() if r.ts.tzinfo is None else r.ts.timestamp()
            except (KeyError, TypeError, ValueError):
                continue
            key = (context_key(context), source, cell, kind)
            previous = groups.get(key)
            groups[key] = (context, source, cell, kind, max(observed, previous[-1]) if previous else observed)
        return sum(self.record(run_id, [(cell, DELAY_FOR[kind], kind)], context=context,
                               source_robot_id=source, observed_at=observed)
                   for context, source, cell, kind, observed in groups.values())

    # --- reading ----------------------------------------------------------------------------

    @staticmethod
    def _valid_context(context):
        return (isinstance(context, dict) and set(context) == set(CONTEXT_FIELDS)
                and context_from_state(context, context.get("policy_version")) == context)

    def invalidate(self, event_id: str, scope: dict, reason: str, *, before: float | None = None) -> bool:
        """Persist an idempotent, signed invalidation. Scope is an AND of context fields.

        This invalidates memory reuse only; execution revocation is a separate
        controller protocol and must not be claimed from this event alone.
        """
        if not self.enabled:
            raise ValueError("experience_signing_not_configured")
        if (not event_id or not scope or not set(scope) <= set(CONTEXT_FIELDS) or not reason
                or not all(isinstance(v, str) and v for v in scope.values())):
            raise ValueError("invalid_invalidation")
        payload = {"event_id": event_id, "scope": scope, "reason": reason, "invalidated_at": self.clock()}
        if before is not None:
            if not math.isfinite(before):
                raise ValueError("invalid_invalidation_cutoff")
            payload["before"] = before
        conn = self._db()
        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                old = conn.execute("SELECT payload FROM experience_invalidations WHERE id=?", (event_id,)).fetchone()
                if old:
                    previous = json.loads(old[0])
                    if previous["scope"] != scope or previous["reason"] != reason or previous.get("before") != before:
                        raise ValueError("invalidation_event_conflict")
                    return False
                conn.execute("INSERT INTO experience_invalidations VALUES (?,?,?)",
                             (event_id, canonical(payload), self.sign(payload)))
                return True
        finally:
            conn.close()

    def invalidations(self):
        conn = self._db()
        try:
            rows = conn.execute("SELECT payload,signature FROM experience_invalidations").fetchall()
        finally:
            conn.close()
        events = []
        for raw, signature in rows:
            try:
                event = json.loads(raw)
                if (not isinstance(event, dict) or not hmac.compare_digest(self.sign(event), signature)
                        or not event.get("scope") or not set(event["scope"]) <= set(CONTEXT_FIELDS)):
                    raise ValueError("invalid_invalidation_record")
                events.append(event)
            except (ValueError, TypeError, KeyError) as exc:
                # An unverifiable lifecycle record cannot silently restore reuse.
                raise ValueError("invalid_invalidation_record") from exc
        return events

    def ineligible_reason(self, context, current, observed, *, events=None):
        if not self._valid_context(context):
            return "legacy_context_missing"
        if not self._valid_context(current):
            return "current_context_missing"
        for key in CONTEXT_FIELDS:
            if context[key] != current[key]:
                return f"{key}_mismatch"
        if self.clock() - observed > self.ttl_s:
            return "experience_expired"
        for event in self.invalidations() if events is None else events:
            if (all(context.get(k) == v for k, v in event["scope"].items())
                    and ("before" not in event or observed <= event["before"])):
                return f"invalidated:{event['event_id']}"
        return None

    def load(self, max_age_s: float = 5.0, *, context=None) -> Tuple[Dict[Cell, float], List[Dict[str, Any]]]:
        """Verified, compatible, age-decayed costs and quarantined records.

        max_age_s remains accepted for existing callers, but lifecycle state is
        re-read on every retrieval. Cache lifetime must never extend validity.
        """
        with self._lock:
            conn = self._db()
            try:
                rows = conn.execute("SELECT e.*,c.metadata FROM experience e LEFT JOIN experience_context c ON e.id=c.id").fetchall()
            finally:
                conn.close()
            delays: Dict[Cell, List[float]] = {}
            quarantined: List[Dict[str, Any]] = []
            decisions = []
            events = self.invalidations()
            for rid, run_id, i, j, delay, kind, observed, sig, raw_metadata in rows:
                body = {"id": rid, "run_id": run_id, "i": i, "j": j, "delay_s": delay, "kind": kind, "observed_at": observed}
                try:
                    metadata = json.loads(raw_metadata) if raw_metadata else None
                    signed = dict(body, metadata=metadata) if metadata is not None else body
                    valid = (self.enabled and isinstance(sig, str) and hmac.compare_digest(self.sign(signed), sig)
                         and isinstance(delay, (int, float)) and math.isfinite(delay) and 0 <= delay <= 60
                         and isinstance(observed, (int, float)) and math.isfinite(observed)
                         and observed <= self.clock() + 1 and kind in DELAY_FOR
                         and isinstance(i, int) and isinstance(j, int))
                    if metadata is not None:
                        valid = (valid and isinstance(metadata, dict) and metadata.get("schema_version") == 2
                                 and self._valid_context(metadata.get("context"))
                                 and metadata.get("experience_type") == "historical_congestion"
                                 and bool(metadata.get("source_robot_id")))
                except (ValueError, TypeError):
                    valid = False
                if not valid:
                    quarantined.append({**body, "reason": "invalid_signature_or_data"})
                    continue
                reason = self.ineligible_reason(metadata.get("context") if metadata else None,
                                                 context, observed, events=events)
                decisions.append({"id": rid, "status": "excluded" if reason else "accepted",
                                  "reason": reason, "source_robot_id": (metadata or {}).get("source_robot_id"),
                                  "age_s": max(0, self.clock() - observed),
                                  "context": (metadata or {}).get("context")})
                if reason:
                    continue
                weight = math.exp(-max(0, self.clock() - observed) / self.decay_s)
                delays.setdefault((i, j), []).append(float(delay) * weight)
            mean = {c: sum(v) / len(v) for c, v in delays.items()}
            self.last_retrieval = decisions
            return mean, quarantined

    def status(self, context=None) -> Dict[str, Any]:
        delays, quarantined = self.load(max_age_s=0, context=context)
        return {"enabled": self.enabled, "learned_cells": len(delays), "quarantined": len(quarantined),
                "quarantine": quarantined[-20:], "experience_context": context,
                "decisions": self.last_retrieval[-100:], "records": len(self.last_retrieval) + len(quarantined),
                "excluded": sum(d["status"] == "excluded" for d in self.last_retrieval),
                "ttl_s": self.ttl_s, "decay_s": self.decay_s}


_memory: Optional[RouteMemory] = None


def get_memory() -> RouteMemory:
    global _memory
    if _memory is None:
        _memory = RouteMemory()
    return _memory


# --- routing ----------------------------------------------------------------------------------

def build_graph(layout, extra=(), delays: Optional[Dict[Cell, float]] = None) -> Tuple[RouteGraph, Any]:
    """Grid graph of the free floor. Blocked cells (racks, walls, hazard zones) only appear
    as `allowed=False` edges, which no learned weight can open."""
    delays = delays or {}
    extra = list(extra)

    def blocked(i: int, j: int) -> bool:
        return layout._blocked[i][j] or (bool(extra) and layout._cell_blocked(i, j, extra))

    graph = RouteGraph()
    steps = [(1, 0), (0, 1), (1, 1), (1, -1)]
    for i in range(layout.nx):
        for j in range(layout.ny):
            for di, dj in steps:
                ni, nj = i + di, j + dj
                if not (0 <= ni < layout.nx and 0 <= nj < layout.ny):
                    continue
                allowed = not (blocked(i, j) or blocked(ni, nj))
                if allowed and di and dj and (blocked(i + di, j) or blocked(i, j + dj)):
                    allowed = False   # no corner cutting past racking
                delay = (delays.get((i, j), 0.0) + delays.get((ni, nj), 0.0)) / 2
                graph.add_edge((i, j), (ni, nj), distance=math.hypot(di, dj) * 0.5,
                               predicted_delay=delay, allowed=allowed)
    return graph, blocked


_graphs: Dict[Any, Tuple[RouteGraph, Any]] = {}


def learned_route(layout, start: Tuple[float, float], goal: Tuple[float, float], extra=(),
                  delays: Optional[Dict[Cell, float]] = None) -> Optional[Dict[str, Any]]:
    """Shortest learned-cost route as a pruned polyline, or None."""
    from app.autonomy.core import Rejected
    key = (id(layout), tuple((round(c.x, 2), round(c.y, 2), round(c.r, 2)) for c in extra),
           hash(tuple(sorted((delays or {}).items()))))
    cached = _graphs.get(key)
    if cached is None:
        if len(_graphs) > 16:
            _graphs.clear()
        cached = _graphs[key] = build_graph(layout, extra, delays)
    graph, blocked = cached
    s = layout._nearest_free(layout._to_cell(*start), blocked)
    g = layout._nearest_free(layout._to_cell(*goal), blocked)
    try:
        result = graph.plan(s, g, delay_weight=DELAY_WEIGHT, risk_weight=1.0)
    except Rejected:
        return None
    pts = [layout._cell_center(*c) for c in result["path"]]
    if not pts:
        return None
    pts[0], pts[-1] = start, goal
    learned_delay = sum(graph.graph[a][b]["delay"] for a, b in zip(result["path"], result["path"][1:]))
    return {"points": layout._prune(pts, blocked), "cost": result["cost"], "learned_delay": learned_delay}
