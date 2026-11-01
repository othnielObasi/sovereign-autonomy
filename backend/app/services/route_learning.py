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
from app.config import settings

logger = logging.getLogger("app.route_learning")

Cell = Tuple[int, int]
# Expected seconds lost when the gate acted in a cell
DELAY_FOR = {"STOP": 4.0, "DENIED": 4.0, "REPLAN": 3.0, "SLOW": 1.5, "NEEDS_REVIEW": 2.0}
DELAY_WEIGHT = 0.6   # route cost per second of expected delay (distance is in metres)


class RouteMemory:
    def __init__(self, db_path: Optional[str] = None, secret: Optional[bytes] = None):
        self.db_path = db_path or settings.authority_db_path
        base = secret if secret is not None else settings.permit_secret.encode()
        # A separate key derived from the permit secret, used only for experience records
        self.key = hmac.new(base or b"unset", b"experience-records-v1", hashlib.sha256).digest()
        self.enabled = bool(base) and len(base) >= 32
        self._lock = threading.Lock()
        self._cache: Optional[Tuple[float, Dict[Cell, float], List[Dict[str, Any]]]] = None
        conn = self._db()
        try:
            with conn:
                conn.execute("CREATE TABLE IF NOT EXISTS experience (id TEXT PRIMARY KEY, run_id TEXT, i INTEGER, "
                             "j INTEGER, delay_s REAL, kind TEXT, observed_at REAL, signature TEXT)")
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

    def record(self, run_id: str, observations: Sequence[Tuple[Cell, float, str]]) -> int:
        """Store signed observations (cell, delay seconds, what happened). Idempotent per run+cell+kind."""
        if not self.enabled or not observations:
            return 0
        rows = []
        now = time.time()
        for (i, j), delay, kind in observations:
            body = {"id": f"{run_id}:{i}:{j}:{kind}", "run_id": run_id, "i": int(i), "j": int(j),
                    "delay_s": round(float(delay), 3), "kind": kind, "observed_at": round(now, 3)}
            rows.append((body["id"], run_id, body["i"], body["j"], body["delay_s"], kind, body["observed_at"],
                         self.sign(body)))
        conn = self._db()
        try:
            with conn:
                conn.executemany("INSERT OR IGNORE INTO experience VALUES (?,?,?,?,?,?,?,?)", rows)
        finally:
            conn.close()
        self._cache = None
        return len(rows)

    def record_run(self, db, run_id: str) -> int:
        """Turn one run's gate decisions into experience: where it was slowed or stopped."""
        from app.db.models import GovernanceDecisionRecord
        from bench.world import GRID_M
        records = db.query(GovernanceDecisionRecord).filter(GovernanceDecisionRecord.run_id == run_id).all()
        worst: Dict[Tuple[Cell, str], float] = {}
        for r in records:
            kind = r.policy_state if r.policy_state in DELAY_FOR else (r.decision if r.decision in DELAY_FOR else None)
            if not kind:
                continue
            try:
                tel = json.loads(r.telemetry_summary or "{}")
                cell = (int(float(tel["x"]) / GRID_M), int(float(tel["y"]) / GRID_M))
            except (KeyError, TypeError, ValueError):
                continue
            worst[(cell, kind)] = max(worst.get((cell, kind), 0.0), DELAY_FOR[kind])
        return self.record(run_id, [(cell, d, kind) for (cell, kind), d in worst.items()])

    # --- reading ----------------------------------------------------------------------------

    def load(self, max_age_s: float = 5.0) -> Tuple[Dict[Cell, float], List[Dict[str, Any]]]:
        """(verified delay per cell, quarantined records). Cached briefly."""
        with self._lock:
            if self._cache and time.time() - self._cache[0] < max_age_s:
                return self._cache[1], self._cache[2]
            conn = self._db()
            try:
                rows = conn.execute("SELECT id, run_id, i, j, delay_s, kind, observed_at, signature FROM experience").fetchall()
            finally:
                conn.close()
            delays: Dict[Cell, List[float]] = {}
            quarantined: List[Dict[str, Any]] = []
            for rid, run_id, i, j, delay, kind, observed, sig in rows:
                body = {"id": rid, "run_id": run_id, "i": i, "j": j, "delay_s": delay, "kind": kind, "observed_at": observed}
                valid = (self.enabled and isinstance(sig, str) and hmac.compare_digest(self.sign(body), sig)
                         and isinstance(delay, (int, float)) and math.isfinite(delay) and 0 <= delay <= 60
                         and observed <= time.time() + 60)
                if not valid:
                    quarantined.append({**body, "reason": "invalid_signature_or_data"})
                    continue
                delays.setdefault((int(i), int(j)), []).append(float(delay))
            mean = {c: sum(v) / len(v) for c, v in delays.items()}
            self._cache = (time.time(), mean, quarantined)
            return mean, quarantined

    def status(self) -> Dict[str, Any]:
        delays, quarantined = self.load(max_age_s=0)
        return {"enabled": self.enabled, "learned_cells": len(delays), "quarantined": len(quarantined),
                "quarantine": quarantined[-20:]}


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
