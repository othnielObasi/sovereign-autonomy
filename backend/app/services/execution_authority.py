"""Execution authority for the run loop.

The governance gate decides; this service turns an APPROVED decision into a
signed, single-use permit for that exact move and sends it through the one
dispatch path. The simulator checks the permit again before moving, so a
command that skips this service (or replays an old permit) does nothing.

Kill switches live here too. They are stored on disk so a restart cannot lift
one, and global/robot switches also engage a stop inside the simulator that
blocks every move until an authorized reset.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

from app.autonomy import permit as wire
from app.autonomy.core import Action, CheckpointStore, KillSwitch, PermitStore, Rejected, WorldState, check_move
from app.autonomy.operations import Budget, CorridorReservations, EvidenceLog, SafeDispatcher, Watchdog
from app.config import settings
from app.observability import metrics

logger = logging.getLogger("app.execution_authority")

TARGET_MATCH_M = 0.05   # how close the controller's target must be to call a move "accepted"
RESERVE_TTL_S = 10.0    # a robot's path hold lasts this long unless renewed by its next permit
RESERVE_PAD_CELLS = 1   # cells either side of the path (0.5 m grid -> ~0.5 m margin each side)
ROBOT_RADIUS_M = 0.4
PERSON_STOP_M = 1.0     # same stop radius the gate's human-proximity rule uses


def keep_out_circles(state: Dict[str, Any]) -> List[tuple]:
    """Keep-out circles for the robot centre, from the telemetry the permit binds to."""
    circles: List[tuple] = []
    for o in state.get("obstacles") or []:
        try:
            circles.append((float(o["x"]), float(o["y"]), float(o.get("r", 0.4)) + ROBOT_RADIUS_M, "obstacle"))
        except (KeyError, TypeError, ValueError):
            continue
    for p in state.get("walking_humans") or []:
        try:
            circles.append((float(p["x"]), float(p["y"]), PERSON_STOP_M, "person"))
        except (KeyError, TypeError, ValueError):
            continue
    for z in state.get("site_constraints") or []:
        try:
            if float(z.get("radius", 0)) > 0:   # exclusion zones only; slow zones are the gate's job
                circles.append((float(z["x"]), float(z["y"]), float(z["radius"]), "hazard"))
        except (KeyError, TypeError, ValueError):
            continue
    return circles


class SimController:
    """Sends a permitted action to the simulator, which verifies the permit itself."""

    def __init__(self, sim):
        self.sim = sim

    async def send(self, action: Action, permit: str) -> Dict[str, Any]:
        return await self.sim.send_command({
            "intent": action.kind,
            "params": action.params,
            "action": {k: v for k, v in action.as_dict().items() if k not in ("kind", "params")},
            "permit": permit,
        })


class ExecutionAuthority:
    def __init__(self, *, secret: Optional[str] = None, db_path: Optional[str] = None,
                 robot_id: Optional[str] = None, max_age_s: Optional[float] = None):
        raw = settings.permit_secret if secret is None else secret
        self.secret = raw.encode()
        self.enabled = len(self.secret) >= 32
        self.robot_id = robot_id or settings.robot_id
        self.db_path = db_path or settings.authority_db_path
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self.world = WorldState(max_age_s=settings.world_max_age_s if max_age_s is None else max_age_s)
        self.kills = KillSwitch()
        self.checkpoints = CheckpointStore(self.db_path)
        self.permits = PermitStore(self.db_path, self.secret, self.kills, self.world) if self.enabled else None
        self.evidence = EvidenceLog()
        self._version = 0
        self._seq = 0
        self._lock = threading.Lock()
        self._budgets: Dict[str, Budget] = {}
        self._watchdogs: Dict[str, Watchdog] = {}
        self.reservations = CorridorReservations()
        self._mission_robot: Dict[str, str] = {}
        self._init_kill_table()
        if not self.enabled:
            logger.warning("PERMIT_SECRET is not set (32+ characters): no move can be authorized")

    # --- kill-switch persistence -------------------------------------------------------

    def _db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def _init_kill_table(self) -> None:
        conn = self._db()
        try:
            with conn:
                conn.execute("CREATE TABLE IF NOT EXISTS kill_locks (scope TEXT, ident TEXT, reason TEXT, "
                             "actor TEXT, ts REAL, PRIMARY KEY (scope, ident))")
            rows = conn.execute("SELECT scope, ident FROM kill_locks").fetchall()
        finally:
            conn.close()
        for scope, ident in rows:
            self.kills.activate(scope, ident)   # survive restarts: a lock is only lifted by reset

    def kill_locks(self) -> List[Dict[str, Any]]:
        conn = self._db()
        try:
            rows = conn.execute("SELECT scope, ident, reason, actor, ts FROM kill_locks ORDER BY ts").fetchall()
        finally:
            conn.close()
        return [{"scope": s, "id": i, "reason": r, "actor": a, "since": ts} for s, i, r, a, ts in rows]

    # --- world state ---------------------------------------------------------------------

    def observe(self, telemetry: Dict[str, Any], robot_id: Optional[str] = None) -> int:
        """Record fresh telemetry for one robot; returns the new world version."""
        rid = robot_id or telemetry.get("robot_id") or self.robot_id
        with self._lock:
            self._version += 1
            version = self._version
        self.world.update(rid, version, dict(telemetry))
        return version

    def robots(self) -> List[str]:
        return sorted(set([self.robot_id] + self.world.robots() + list(self._mission_robot.values())))

    # --- per-run controls ------------------------------------------------------------------

    def heartbeat(self, run_id: str) -> None:
        self._watchdogs.setdefault(run_id, Watchdog(settings.dispatch_watchdog_s)).heartbeat()

    def end_run(self, run_id: str) -> None:
        self._budgets.pop(run_id, None)
        self._watchdogs.pop(run_id, None)

    # --- authorize and dispatch -------------------------------------------------------------

    def authorize(self, *, run_id: str, mission_id: str, intent: str, params: Dict[str, Any],
                  decision: str, policy_version: str, agent_id: str = "",
                  robot_id: Optional[str] = None) -> tuple[Action, str]:
        """Turn an approved decision into a permit for this exact action. Raises Rejected."""
        if not self.enabled:
            raise Rejected("permit_secret_not_configured")
        if decision != "APPROVED":
            raise Rejected("governance_denied")   # the gate decides first; nothing else can approve
        rid = robot_id or self.robot_id
        version = self.world.current_version(rid)
        if version is None:
            raise Rejected("no_world_state")
        self._mission_robot[mission_id] = rid
        if intent == "MOVE_TO":
            state = self.world.require(rid, version)
            self._check_path(state, params or {})
            self._reserve_path(rid, state, params or {})
        with self._lock:
            self._seq += 1
            seq = self._seq
        action = Action(rid, mission_id, f"{run_id}:{seq}:{int(time.time() * 1000)}",
                        intent, dict(params or {}), version, policy_version or "")
        token = self.permits.issue(action, approved=(decision == "APPROVED"),
                                   ttl_s=settings.permit_ttl_s, agent_id=agent_id)
        metrics.inc("permits_issued_total")
        return action, token

    def authorize_or_count(self, **kw) -> tuple[Action, str]:
        """authorize(), counting refusals by reason for /metrics."""
        try:
            return self.authorize(**kw)
        except Rejected as exc:
            metrics.inc("permits_refused_total", reason=str(exc))
            raise

    @staticmethod
    def _check_path(state: Dict[str, Any], params: Dict[str, Any]) -> None:
        """Second, independent layer behind the gate: sample the whole straight move."""
        try:
            start = (float(state["x"]), float(state["y"]))
            end = (float(params["x"]), float(params["y"]))
        except (KeyError, TypeError, ValueError):
            raise Rejected("trajectory_unknown_positions")
        b = state.get("bounds") or {}
        bounds = None
        if all(k in b for k in ("min_x", "min_y", "max_x", "max_y")):
            bounds = (float(b["min_x"]), float(b["min_y"]), float(b["max_x"]), float(b["max_y"]))
        check_move(start, end, bounds, keep_out_circles(state))

    def _reserve_path(self, robot_id: str, state: Dict[str, Any], params: Dict[str, Any]) -> None:
        """Hold the floor cells along this move (plus a margin) for this robot only, so two
        robots can never be authorized onto overlapping paths. All or nothing."""
        from bench.world import GRID_M
        (x0, y0), (x1, y1) = (float(state["x"]), float(state["y"])), (float(params["x"]), float(params["y"]))
        steps = max(1, math.ceil(math.hypot(x1 - x0, y1 - y0) / (GRID_M / 2)))
        keys = set()
        for k in range(steps + 1):
            ci, cj = int((x0 + (x1 - x0) * k / steps) / GRID_M), int((y0 + (y1 - y0) * k / steps) / GRID_M)
            for di in range(-RESERVE_PAD_CELLS, RESERVE_PAD_CELLS + 1):
                for dj in range(-RESERVE_PAD_CELLS, RESERVE_PAD_CELLS + 1):
                    keys.add(f"{ci + di},{cj + dj}")
        self.reservations.reserve_path(robot_id, keys, ttl_s=RESERVE_TTL_S)

    async def dispatch(self, run_id: str, action: Action, token: str, sim) -> Dict[str, Any]:
        """Send through the single dispatch path, then record what the controller said.

        Raises Rejected if the permit, budget or watchdog refuses, or if the outcome is
        unknown (the action then stays in doubt until reconciled)."""
        budget = self._budgets.setdefault(run_id, Budget(settings.max_actions_per_run))
        watchdog = self._watchdogs.setdefault(run_id, Watchdog(settings.dispatch_watchdog_s))
        dispatcher = SafeDispatcher(self.permits, self.checkpoints, SimController(sim), budget, watchdog, self.evidence)
        try:
            result = await dispatcher.dispatch_async(token, action)
        except Rejected as exc:
            metrics.inc("dispatch_total", outcome="unknown" if "unknown" in str(exc) else "refused")
            raise
        metrics.inc("dispatch_total", outcome="controller_refused" if isinstance(result, dict) and result.get("rejected")
                    else "accepted")
        if isinstance(result, dict) and result.get("rejected"):
            # The controller refused it: verified not executed
            self.checkpoints.reconcile(action.action_id, controller_verified=True, executed=False)
        elif isinstance(result, dict) and (result.get("ok") or result.get("ack")):
            self.checkpoints.reconcile(action.action_id, controller_verified=True, executed=True)
        return result

    def reconcile_in_doubt(self, mission_id: str, telemetry: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Settle actions whose outcome was lost, using the controller's reported target.

        A MOVE_TO counts as accepted only if the controller is now heading to exactly
        that target; nothing is retried here."""
        settled = []
        target = telemetry.get("target") or None
        for action_id in self.checkpoints.in_doubt(mission_id):
            action = self.checkpoints.action(action_id)
            executed = False
            if action and action.kind == "MOVE_TO" and isinstance(target, dict):
                try:
                    executed = math.hypot(float(target["x"]) - float(action.params["x"]),
                                          float(target["y"]) - float(action.params["y"])) <= TARGET_MATCH_M
                except (KeyError, TypeError, ValueError):
                    executed = False
            self.checkpoints.reconcile(action_id, controller_verified=True, executed=executed)
            settled.append({"action_id": action_id, "executed": executed})
        return settled

    # --- kill switches ------------------------------------------------------------------------

    async def kill(self, scope: str, ident: str, *, reason: str, actor: Optional[str], sim) -> Dict[str, Any]:
        """Revoke authority now; stop the robot at the controller and measure the stop."""
        t0 = time.monotonic()
        ident = "*" if scope == "global" else ident
        self.kills.activate(scope, ident)
        conn = self._db()
        try:
            with conn:
                conn.execute("INSERT OR REPLACE INTO kill_locks VALUES (?,?,?,?,?)",
                             (scope, ident, reason, actor or "anonymous", time.time()))
        finally:
            conn.close()
        revoked_ms = (time.monotonic() - t0) * 1000

        controller: Dict[str, Any] = {}
        if scope == "global":
            robots = self.robots()
        elif scope == "robot":
            robots = [ident]
        elif scope == "mission":
            robots = [self._mission_robot.get(ident, self.robot_id)]
        else:   # agent: stop every robot it may have been driving
            robots = self.robots()
        try:
            if scope == "global":
                controller = await sim.estop(engaged=True, reason=reason)
            elif scope == "robot":
                controller = await sim.estop(engaged=True, reason=reason, robot_id=ident)
            else:
                for rid in robots:
                    controller = await sim.send_command({"intent": "STOP", "params": {}, "robot_id": rid})
        except Exception as exc:   # authority is already revoked; report the controller failure
            controller = {"ok": False, "error": type(exc).__name__}
        stop = await self._verify_stopped(sim, robots)
        self.evidence.emit("kill_switch", "*", None, scope=scope, id=ident, reason=reason, actor=actor)
        metrics.inc("kill_switch_total", scope=scope)
        from app.observability import tracing
        tracing.event("kill_switch", {"scope": scope, "id": ident, "reason": reason, "actor": actor or "anonymous"},
                      {"authority_revoked_ms": round(revoked_ms, 2), "controller": controller, **stop})
        metrics.observe("kill_revoke_ms", revoked_ms, scope=scope)
        if stop.get("stop_verified_ms") is not None:
            metrics.observe("kill_stop_verified_ms", stop["stop_verified_ms"], scope=scope)
        return {"scope": scope, "id": ident, "robots": robots, "authority_revoked_ms": round(revoked_ms, 2),
                "controller": controller, **stop}

    async def _verify_stopped(self, sim, robots: Optional[List[str]] = None, timeout_s: float = 5.0) -> Dict[str, Any]:
        """Poll each robot's telemetry until it reports no speed and no target."""
        t0 = time.monotonic()
        pending = list(robots or [self.robot_id])
        while time.monotonic() - t0 < timeout_s:
            still = []
            for rid in pending:
                try:
                    tel = await (sim.get_telemetry(robot_id=rid) if rid != self.robot_id else sim.get_telemetry())
                    if not (abs(float(tel.get("speed", 0.0))) < 0.02 and not tel.get("target")):
                        still.append(rid)
                except Exception:
                    still.append(rid)
            pending = still
            if not pending:
                return {"stop_verified": True, "stop_verified_ms": round((time.monotonic() - t0) * 1000, 1)}
            await asyncio.sleep(0.1)
        return {"stop_verified": False, "stop_verified_ms": None, "not_stopped": pending}

    async def reset(self, scope: str, ident: str, *, actor: str, sim) -> Dict[str, Any]:
        """Lift one lock (caller must be an authenticated operator). Old permits stay void."""
        ident = "*" if scope == "global" else ident
        self.kills.reset(scope, ident, authorized=bool(actor))
        conn = self._db()
        try:
            with conn:
                conn.execute("DELETE FROM kill_locks WHERE scope=? AND ident=?", (scope, ident))
        finally:
            conn.close()
        controller: Dict[str, Any] = {}
        active = self.kills.active()
        if scope == "global":
            still_stopped = False
            release_for = "*"
        elif scope == "robot":
            still_stopped = any(s == "global" for s, _ in active)
            release_for = ident
        else:
            still_stopped = any(s == "global" for s, _ in active)
            release_for = None      # mission/agent locks never engaged a controller e-stop
        if release_for and self.enabled:
            try:
                controller = await sim.estop(engaged=False, robot_id=None if release_for == "*" else release_for,
                                             release_token=wire.release_token(self.secret, release_for))
            except Exception as exc:
                controller = {"ok": False, "error": type(exc).__name__}
        self.evidence.emit("kill_switch_reset", "*", None, scope=scope, id=ident, actor=actor)
        from app.observability import tracing
        tracing.event("kill_switch_reset", {"scope": scope, "id": ident, "actor": actor},
                      {"controller_released": bool(controller.get("ok")), "still_stopped": still_stopped})
        return {"scope": scope, "id": ident, "reset": True, "controller_released": bool(controller.get("ok")),
                "still_stopped": still_stopped}

    def status(self) -> Dict[str, Any]:
        return {"enabled": self.enabled, "robot_id": self.robot_id, "robots": self.robots(), "epoch": self.kills.epoch,
                "kill_locks": self.kill_locks(), "world_version": self.world.current_version(self.robot_id),
                "reservations": self.reservations.held(), "journal_intact": self.checkpoints.verify_chain()}


_authority: Optional[ExecutionAuthority] = None


def get_authority() -> ExecutionAuthority:
    global _authority
    if _authority is None:
        _authority = ExecutionAuthority()
    return _authority
