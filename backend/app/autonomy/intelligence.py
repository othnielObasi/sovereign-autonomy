"""Graph routing, provenance-checked experience memory, canaries and mission scope."""
from __future__ import annotations

import hashlib
import hmac
import math
import threading
import time
from dataclasses import dataclass

import networkx as nx

from .core import Rejected, canonical


class RouteGraph:
    """Waypoint graph. `allowed` is an authoritative restriction that learning never changes;
    `delay` and `risk` are learned weights."""

    def __init__(self):
        self.graph = nx.Graph()

    def add_edge(self, a, b, *, distance: float, predicted_delay: float = 0, risk: float = 0, allowed: bool = True) -> None:
        if any(not math.isfinite(x) or x < 0 for x in (distance, predicted_delay, risk)):
            raise Rejected("invalid_edge_cost")
        self.graph.add_edge(a, b, distance=distance, delay=predicted_delay, risk=risk, allowed=allowed)

    def plan(self, start, goal, *, delay_weight: float = 1, risk_weight: float = 1) -> dict:
        if delay_weight < 0 or risk_weight < 0:
            raise ValueError("negative_weight")
        permitted = nx.subgraph_view(self.graph, filter_edge=lambda u, v: self.graph[u][v]["allowed"])

        def weight(u, v, attrs):
            return attrs["distance"] + delay_weight * attrs["delay"] + risk_weight * attrs["risk"]

        try:
            path = nx.shortest_path(permitted, start, goal, weight=weight)
        except (nx.NetworkXNoPath, nx.NodeNotFound) as exc:
            raise Rejected("no_permitted_route") from exc
        return {"path": path, "cost": sum(weight(a, b, self.graph[a][b]) for a, b in zip(path, path[1:]))}

    def learn_delay(self, a, b, observed: float, *, alpha: float = 0.2) -> None:
        """Move the edge's predicted delay toward an observed value. Never touches `allowed`."""
        if not math.isfinite(observed) or observed < 0 or not 0 < alpha <= 1:
            raise Rejected("invalid_learning_update")
        edge = self.graph[a][b]
        edge["delay"] = (1 - alpha) * edge["delay"] + alpha * observed


@dataclass(frozen=True)
class Experience:
    record_id: str
    mission_id: str
    route: tuple[str, ...]
    duration_s: float
    outcome: str
    source: str
    observed_at: float
    signature: str


class TrustedExperience:
    """Signed experience records. Unsigned or invalid records are quarantined.

    A signature proves which source wrote a record, not that the record is true.
    """

    def __init__(self, secret: bytes):
        if len(secret) < 32:
            raise ValueError("experience_secret_too_short")
        self.secret = secret
        self.records: dict[str, Experience] = {}
        self.quarantine: dict[str, str] = {}
        self._lock = threading.Lock()

    def sign(self, data: dict) -> str:
        return hmac.new(self.secret, canonical(data).encode(), hashlib.sha256).hexdigest()

    def ingest(self, record: Experience) -> None:
        body = {k: v for k, v in vars(record).items() if k != "signature"}
        with self._lock:
            if not isinstance(record.signature, str) or not hmac.compare_digest(self.sign(body), record.signature):
                self.quarantine[record.record_id] = "invalid_signature"
                raise Rejected("untrusted_experience")
            if (not record.route or not math.isfinite(record.duration_s) or record.duration_s < 0
                    or record.observed_at > time.time() + 60):
                self.quarantine[record.record_id] = "invalid_data"
                raise Rejected("invalid_experience")
            if record.record_id in self.records:
                raise Rejected("duplicate_experience")
            self.records[record.record_id] = record

    def relevant(self, start: str, goal: str, limit: int = 5) -> list[Experience]:
        with self._lock:
            matches = [r for r in self.records.values() if r.route[0] == start and r.route[-1] == goal]
        return sorted(matches, key=lambda r: r.observed_at, reverse=True)[:limit]


class CanaryRegistry:
    """Planted markers. Seeing one where it should not be is a signal, not proof of compromise."""

    def __init__(self):
        self.markers: dict[str, str] = {}

    def register(self, marker: str, owner: str) -> None:
        if not marker or marker in self.markers:
            raise ValueError("invalid_or_duplicate_canary")
        self.markers[marker] = owner

    def scan(self, text: str) -> list[dict]:
        return [{"marker": m, "owner": o} for m, o in self.markers.items() if m in text]


class MissionIntegrity:
    """A mission may only issue the action kinds it was created with."""

    def __init__(self, mission_id: str, objective: str, allowed_actions: set[str]):
        self.mission_id, self.objective = mission_id, objective
        self.allowed_actions = frozenset(allowed_actions)

    def require(self, action) -> None:
        if action.mission_id != self.mission_id or action.kind not in self.allowed_actions:
            raise Rejected("mission_integrity_violation")
