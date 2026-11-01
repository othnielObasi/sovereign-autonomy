"""Operational controls around dispatch: budgets, watchdog, corridor reservations,
an evidence log, and the single dispatch path that every command must take."""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Protocol

from .core import Action, CheckpointStore, PermitStore, Rejected


class Budget:
    """Cap on actions per mission. Exhaustion stops optional work, never a stop command."""

    def __init__(self, max_actions: int):
        self.remaining = max_actions
        self._lock = threading.Lock()

    def consume(self) -> None:
        with self._lock:
            if self.remaining <= 0:
                raise Rejected("action_budget_exhausted")
            self.remaining -= 1


class Watchdog:
    """Blocks dispatch when the control loop has not sent a heartbeat in time."""

    def __init__(self, timeout_s: float):
        self.timeout_s = timeout_s
        self.last_heartbeat = time.monotonic()

    def heartbeat(self) -> None:
        self.last_heartbeat = time.monotonic()

    def require_healthy(self) -> None:
        if time.monotonic() - self.last_heartbeat > self.timeout_s:
            raise Rejected("watchdog_timeout")


class CorridorReservations:
    """Exclusive, expiring corridor holds so two robots never share one."""

    def __init__(self):
        self.reservations: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def reserve(self, corridor: str, robot: str, ttl_s: float = 10) -> None:
        with self._lock:
            old = self.reservations.get(corridor)
            if old and old[0] != robot and old[1] > time.time():
                raise Rejected("corridor_conflict")
            self.reservations[corridor] = (robot, time.time() + ttl_s)

    def release(self, corridor: str, robot: str) -> None:
        with self._lock:
            if self.reservations.get(corridor, ("", 0))[0] == robot:
                self.reservations.pop(corridor, None)


class EvidenceLog:
    """Structured events keyed by mission and action, exportable as JSON lines."""

    def __init__(self):
        self.events: list[dict] = []
        self._lock = threading.Lock()

    def emit(self, kind: str, mission_id: str, action_id: str | None = None, **fields) -> dict:
        event = {"timestamp": time.time(), "kind": kind, "mission_id": mission_id, "action_id": action_id, **fields}
        with self._lock:
            self.events.append(event)
        return event

    def export_jsonl(self) -> str:
        with self._lock:
            return "\n".join(json.dumps(x, sort_keys=True) for x in self.events)


class Controller(Protocol):
    def send(self, action: Action) -> Any: ...


class SafeDispatcher:
    """The one path a command takes to the controller.

    Order: watchdog, use up the permit, budget, mark the action IN_DOUBT, send.
    If the controller's answer is lost, the action stays IN_DOUBT and is never
    retried automatically; it must be reconciled first. A controller
    acknowledgement is not proof the robot physically completed the move.
    """

    def __init__(self, permits: PermitStore, checkpoints: CheckpointStore, controller: Controller,
                 budget: Budget, watchdog: Watchdog, evidence: EvidenceLog):
        self.permits, self.checkpoints, self.controller = permits, checkpoints, controller
        self.budget, self.watchdog, self.evidence = budget, watchdog, evidence

    def dispatch(self, token: str, action: Action) -> Any:
        self.watchdog.require_healthy()
        self.permits.consume(token, action)
        self.budget.consume()
        self.checkpoints.begin_action(action)
        self.evidence.emit("command_dispatched", action.mission_id, action.action_id)
        try:
            result = self.controller.send(action)
        except Exception as exc:
            self.evidence.emit("command_outcome_unknown", action.mission_id, action.action_id, error=type(exc).__name__)
            raise Rejected("controller_outcome_unknown_reconcile_before_retry") from exc
        self.evidence.emit("controller_acknowledged", action.mission_id, action.action_id)
        return result
