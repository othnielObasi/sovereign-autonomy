"""Operational controls around dispatch: budgets, watchdog, corridor reservations,
an evidence log, and the single dispatch path that every command must take."""
from __future__ import annotations

import inspect
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

    def reserve_path(self, robot: str, keys, ttl_s: float = 10) -> None:
        """Hold every key for `robot`, all or nothing, replacing its earlier holds.
        Raises Rejected('corridor_conflict') if another robot holds any of them."""
        keys = set(keys)
        now = time.time()
        with self._lock:
            for k in keys:
                old = self.reservations.get(k)
                if old and old[0] != robot and old[1] > now:
                    raise Rejected("corridor_conflict")
            for k in [k for k, (r, _) in self.reservations.items() if r == robot and k not in keys]:
                del self.reservations[k]
            for k in keys:
                self.reservations[k] = (robot, now + ttl_s)

    def release_robot(self, robot: str) -> None:
        with self._lock:
            for k in [k for k, (r, _) in self.reservations.items() if r == robot]:
                del self.reservations[k]

    def held(self) -> dict:
        """robot -> number of unexpired holds."""
        now = time.time()
        out: dict = {}
        with self._lock:
            for r, exp in self.reservations.values():
                if exp > now:
                    out[r] = out.get(r, 0) + 1
        return out


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
    """Sends one action, with its permit, to the robot controller (which checks the permit again)."""
    def send(self, action: Action, permit: str) -> Any: ...


class SafeDispatcher:
    """The one path a command takes to the controller.

    Order: watchdog, validate permit, budget, mark IN_DOUBT, send. The controller
    redeems the permit immediately before admission, rather than dispatch using it.
    If the controller's answer is lost, the action stays IN_DOUBT and is never
    retried automatically; it must be reconciled first. A controller
    acknowledgement is not proof the robot physically completed the move.
    """

    def __init__(self, permits: PermitStore, checkpoints: CheckpointStore, controller: Controller,
                 budget: Budget, watchdog: Watchdog, evidence: EvidenceLog):
        self.permits, self.checkpoints, self.controller = permits, checkpoints, controller
        self.budget, self.watchdog, self.evidence = budget, watchdog, evidence

    def _prepare(self, token: str, action: Action) -> None:
        self.watchdog.require_healthy()
        self.permits.validate(token, action)
        self.budget.consume()
        self.checkpoints.begin_action(action)
        self.evidence.emit("command_dispatched", action.mission_id, action.action_id)

    def _unknown(self, action: Action, exc: Exception) -> Rejected:
        self.evidence.emit("command_outcome_unknown", action.mission_id, action.action_id, error=type(exc).__name__)
        return Rejected("controller_outcome_unknown_reconcile_before_retry")

    def dispatch(self, token: str, action: Action) -> Any:
        self._prepare(token, action)
        try:
            result = self.controller.send(action, token)
        except Exception as exc:
            raise self._unknown(action, exc) from exc
        self.evidence.emit("controller_acknowledged", action.mission_id, action.action_id)
        return result

    async def dispatch_async(self, token: str, action: Action) -> Any:
        """Same as dispatch, for a controller whose send() is a coroutine."""
        self._prepare(token, action)
        try:
            result = self.controller.send(action, token)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            raise self._unknown(action, exc) from exc
        self.evidence.emit("controller_acknowledged", action.mission_id, action.action_id)
        return result
