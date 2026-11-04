from __future__ import annotations

"""Run lifecycle manager — the runtime core of the Sovereign Autonomy platform.

This module owns the full lifecycle of a "run" (a single execution attempt
of a mission).  Key responsibilities:

1. **Start / stop / pause / resume** — state machine transitions with
   parent-mission synchronisation and operator intervention logging.
2. **The run loop** (`_run_loop`) — an async tick-based control loop that:
   - Reads telemetry from the simulator.
   - Validates telemetry plausibility (anti-spoofing).
   - Asks the agent/planner for the next action proposal.
   - Passes proposals through the governance engine.
   - Executes approved commands on the simulator.
   - Records every decision in a SHA-256 hash-chained event log
     for tamper-evident auditing.
3. **Diagnostics** — stagnation detection, execution verification,
   runtime integrity checks, and replan-on-denial logic.
4. **Post-run analytics** — safety validation, cross-run learning, and
   lesson extraction (fire-and-forget after completion).
"""

import asyncio
import math
import json
import logging
import time
import threading
from datetime import timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.models import Run, Event
from app.schemas.governance import ActionProposal
from app.services.sim_adapter import SimAdapter
from app.services.agent_service import AgentRouter
from app.services.governance_engine import GovernanceEngine
from app.services.telemetry_service import TelemetryService
from app.services.telemetry_validator import TelemetryValidator
from app.services.integrity_monitor import RuntimeIntegrityChecker
from app.services.execution_authority import get_authority
from app.autonomy.core import Rejected


class RobotView:
    """The simulator as seen by one robot: telemetry, commands, camera and reset for
    that robot only. The default robot uses the adapter unchanged."""

    def __init__(self, sim, robot_id: str):
        self._sim, self.robot_id = sim, robot_id

    async def get_telemetry(self):
        return await self._sim.get_telemetry(robot_id=self.robot_id)

    async def send_command(self, command):
        return await self._sim.send_command(dict(command, robot_id=self.robot_id))

    async def get_frame(self, size: int = 512):
        return await self._sim.get_frame(size=size, robot_id=self.robot_id)

    async def reset_robot(self):
        return await self._sim.reset_robot(robot_id=self.robot_id)

    async def estop(self, **kw):
        return await self._sim.estop(**kw)

    def __getattr__(self, name):          # world, scenarios, seeds: shared by all robots
        return getattr(self._sim, name)


def settings_world_age() -> float:
    from app.config import settings as _cfg
    return float(_cfg.world_max_age_s)
from app.world_model import ZONE_SPEED_LIMITS
from app.utils.ids import new_id
from app.utils.time import utc_now
from app.utils.hashing import sha256_canonical

logger = logging.getLogger("app.run_service")


class RunService:
    """Owns run lifecycle and the runtime loop.

    Supports: start, stop, pause, resume for intervention control.
    Records every governance decision to the governance_decisions table.
    """

    def __init__(self):
        # --- Concurrency primitives (keyed by run_id) ---
        self._tasks: Dict[str, asyncio.Task] = {}       # active asyncio loop tasks
        self._stop_flags: Dict[str, asyncio.Event] = {} # set → graceful shutdown
        self._pause_flags: Dict[str, asyncio.Event] = {} # set = paused (loop sleeps)
        self._ws_broadcast = None  # WebSocket broadcast callback, injected by WS manager

        # --- Plan state (keyed by run_id) ---
        self._plans: Dict[str, List[Dict[str, Any]]] = {}  # ordered waypoint queue
        self._plan_contexts: Dict[str, Any] = {}
        self._environment_holds: set[str] = set()
        self._review_proposals: Dict[str, ActionProposal] = {}
        self._operator_locks: Dict[str, asyncio.Lock] = {}
        self._operator_busy: set[str] = set()
        self._tick_idle: Dict[str, asyncio.Event] = {}
        self._plans_lock = asyncio.Lock()  # protects concurrent reads/writes to _plans

        # --- Stagnation detection ---
        self._last_positions: Dict[str, tuple[float, float]] = {}  # last (x, y) per run
        self._stagnant_counts: Dict[str, int] = {}  # consecutive low-movement ticks
        self.STAGNATION_THRESHOLD_M = 0.02  # metres: movement below this = stagnant
        self.STAGNATION_CYCLES = 10         # ticks: emit STAGNATION alert after this many
        self._hazard_holds: Dict[str, str] = {}  # run_id -> why the robot is holding for a hazard

        # --- Replan-on-denial ---
        self._wp_denial_counts: Dict[str, int] = {}  # consecutive governance denials
        # Runs whose slowed move the path check refused: replan instead of waiting for an operator
        self._path_blocked: Dict[str, bool] = {}
        self.REPLAN_DENIAL_THRESHOLD = 5  # trigger LLM re-plan after N consecutive denials
        self.WAYPOINT_REACHED_M = 0.6     # a plan waypoint counts as reached within this distance

        # --- Executed path tracking (for UI visualisation & scoring) ---
        self._executed_paths: Dict[str, List[Dict[str, Any]]] = {}

        # --- Anti-spoofing: per-run telemetry plausibility validators ---
        self._tel_validators: Dict[str, TelemetryValidator] = {}

        # --- Anti-gaming: per-run runtime integrity checkers ---
        self._integrity_checkers: Dict[str, RuntimeIntegrityChecker] = {}

        # --- Execution verification ---
        self.EXEC_VERIFY_TOLERANCE_M = 2.0  # metres: max allowed discrepancy between
                                             # commanded and actual position after exec

        self.sim = SimAdapter()
        self._event_locks: Dict[str, Any] = {}
        self._run_robot: Dict[str, str] = {}   # run id -> robot it drives
        self.agent = AgentRouter()
        self.gov = GovernanceEngine()
        self.tel = TelemetryService()

    def bind_broadcaster(self, broadcaster):
        self._ws_broadcast = broadcaster

    def _append_event(self, db: Session, run_id: str, etype: str, payload: Dict[str, Any]) -> Event:
        """Append an event to the tamper-evident hash chain for a run.

        Each event stores the SHA-256 hash of the previous event, forming a
        linked chain analogous to a blockchain.  Any retrospective modification
        of an event breaks the chain, which is detected by the audit verifier
        (see ``replay_service.verify_chain``).

        Returns the newly created Event ORM row (already committed).
        """
        # The runtime is a single writer process. Serialize its sync handlers as
        # well as loop callbacks; the system clock can repeat a timestamp.
        lock = self._event_locks.setdefault(run_id, threading.RLock())
        with lock:
            return self._append_event_locked(db, run_id, etype, payload)

    def _append_event_locked(self, db: Session, run_id: str, etype: str, payload: Dict[str, Any]) -> Event:
        # Get previous event hash for chain linking
        prev = (
            db.query(Event)
            .filter(Event.run_id == run_id)
            .order_by(Event.ts.desc())
            .first()
        )
        prev_hash = prev.hash if prev else "0" * 64

        ts = utc_now()  # single timestamp for both hash and storage
        if prev is not None:
            previous_ts = prev.ts if prev.ts.tzinfo else prev.ts.replace(tzinfo=timezone.utc)
            if ts <= previous_ts:
                ts = previous_ts + timedelta(microseconds=1)
        evt = {
            "run_id": run_id,
            "ts": ts.isoformat(),
            "type": etype,
            "payload": payload,
            "prev_hash": prev_hash,
        }
        evt_hash = sha256_canonical(evt)
        row = Event(
            id=new_id("evt"),
            run_id=run_id,
            ts=ts,
            type=etype,
            payload_json=json.dumps(payload, ensure_ascii=False),
            hash=evt_hash,
            prev_hash=prev_hash,
        )
        db.add(row)
        # Commit at once (not just flush): an open write transaction holds SQLite's single
        # write lock, and with two robots the other run's synchronous wait for that lock
        # froze the whole event loop. Events are append-only, so committing early loses nothing.
        db.commit()
        return row

    def start_run(self, db: Session, mission_id: str) -> Run:
        # Snapshot policy version at run start (#16)
        from app.policies.versioning import policy_version_hash, policy_version_info
        from app.db.models import PolicyVersion
        import json as _json

        pv_hash = policy_version_hash()
        pv_info = policy_version_info()

        # Upsert policy version record
        existing_pv = db.query(PolicyVersion).filter(PolicyVersion.version_hash == pv_hash).first()
        if not existing_pv:
            pv_row = PolicyVersion(
                version_hash=pv_hash,
                parameters_json=_json.dumps(pv_info["parameters"], sort_keys=True),
                created_at=utc_now(),
                description=f"Auto-snapshot at run start",
            )
            db.add(pv_row)

        run = Run(
            id=new_id("run"),
            mission_id=mission_id,
            status="planning",
            started_at=utc_now(),
            ended_at=None,
            policy_version=pv_hash,
            planning_mode="llm_with_fallback",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        try:
            from app.db.models import Mission as _M
            _m = db.query(_M).filter(_M.id == mission_id).first()
            self._run_robot[run.id] = self.robot_of_goal(json.loads(_m.goal_json) if _m else None)
        except Exception:
            pass
        try:
            from app.db.models import Mission as _M
            from app.observability import tracing
            m = db.query(_M).filter(_M.id == mission_id).first()
            tracing.mission_start(run.id, mission_id, m.title if m else "", json.loads(m.goal_json) if m else {})
        except Exception:
            pass

        # Do NOT launch loop yet — caller must attach a plan first, then
        # call begin_running() to transition from "planning" → "running".
        return run

    @staticmethod
    def robot_of_goal(goal: Optional[Dict[str, Any]]) -> str:
        from app.config import settings as _cfg
        return str((goal or {}).get("robot_id") or _cfg.robot_id)

    def sim_for_robot(self, robot_id: str):
        from app.config import settings as _cfg
        return self.sim if robot_id == _cfg.robot_id else RobotView(self.sim, robot_id)

    def robot_for(self, run_id: str) -> str:
        if run_id not in self._run_robot:
            from app.db.session import SessionLocal as _SL
            from app.db.models import Mission as _M
            db = _SL()
            try:
                run = db.query(Run).filter(Run.id == run_id).first()
                m = db.query(_M).filter(_M.id == run.mission_id).first() if run else None
                if m is None:          # unknown run: answer the default, but don't remember it
                    return self.robot_of_goal(None)
                self._run_robot[run_id] = self.robot_of_goal(json.loads(m.goal_json))
            except Exception:
                return self.robot_of_goal(None)
            finally:
                db.close()
        return self._run_robot[run_id]

    def sim_for(self, run_id: str):
        """The simulator view for the robot this run drives."""
        return self.sim_for_robot(self.robot_for(run_id))

    def begin_running(self, db: Session, run_id: str) -> None:
        """Transition a run from 'planning' to 'running' and launch the loop.

        Must be called only after a plan has been attached via self._plans.
        """
        run = db.query(Run).filter(Run.id == run_id).first()
        if not run or run.status != "planning":
            return
        run.status = "running"
        db.commit()
        self._launch_loop(run_id)
        logger.info("Run %s transitioned planning → running", run_id)

    def _launch_loop(self, run_id: str) -> None:
        """Spawn the asyncio run-loop task for a given run."""
        if run_id in self._tasks and not self._tasks[run_id].done():
            return  # already running
        idle = asyncio.Event()
        idle.set()
        self._tick_idle[run_id] = idle
        stop_event = asyncio.Event()
        self._stop_flags[run_id] = stop_event
        self._tasks[run_id] = asyncio.create_task(self._run_loop(run_id))
        logger.info("Launched run loop task for %s", run_id)

    def rehydrate_plans(self, db: Session) -> None:
        """Load persisted PLAN events from DB for runs and populate in-memory plans.

        Expects a SQLAlchemy `Session` (this allows caller to control transactions).
        """
        try:
            # Find runs that are currently running
            runs = db.query(Run).filter(Run.status == "running").all()
            for r in runs:
                # Find most recent PLAN event for this run
                plan_evt = (
                    db.query(Event)
                    .filter(Event.run_id == r.id)
                    .filter(Event.type == "PLAN")
                    .order_by(Event.ts.desc())
                    .first()
                )
                if plan_evt:
                    try:
                        payload = json.loads(plan_evt.payload_json)
                        plan = payload.get("plan") or {}
                        waypoints = plan.get("waypoints") or []
                        if waypoints:
                            self._plans[r.id] = waypoints.copy()
                            logger.info("Rehydrated plan for run %s (%d waypoints)", r.id, len(waypoints))
                    except (TypeError, ValueError, json.JSONDecodeError) as exc:
                        logger.warning("Failed to parse PLAN event for run %s: %s", r.id, exc)
        except Exception as e:
            logger.warning("rehydrate_plans failed: %s", e)

    async def stop_run(self, db: Session, run_id: str) -> None:
        if run_id in self._stop_flags:
            self._stop_flags[run_id].set()

        # Halt the robot first: an operator stop must not wait on the database.
        try:
            await self.sim_for(run_id).send_command({"intent": "STOP", "params": {}})
        except Exception as e:
            logger.warning("Run %s: STOP command to robot failed: %s", run_id, e)

        # Record the stop. SQLite allows one writer, so if another write is in
        # progress, retry instead of failing the operator's request.
        from sqlalchemy.exc import OperationalError
        from app.db.models import Mission
        for attempt in range(5):
            try:
                run = db.query(Run).filter(Run.id == run_id).first()
                if run and run.status in ("running", "paused", "planning"):
                    run.status = "stopped"
                    run.ended_at = utc_now()
                    mission = db.query(Mission).filter(Mission.id == run.mission_id).first()
                    if mission and mission.status == "executing":
                        mission.status = "paused"
                self._append_event(db, run_id, "INTERVENTION", {
                    "type": "STOP",
                    "actor": "operator",
                    "reason": "Manual stop requested",
                })
                db.commit()
                break
            except OperationalError as e:
                db.rollback()
                if attempt == 4:
                    raise
                logger.warning("Run %s: database busy recording stop (%s); retrying", run_id, e)
                await asyncio.sleep(1.0 + attempt)

        if self._ws_broadcast:
            await self._ws_broadcast(run_id, {"kind": "status", "data": {"status": "stopped"}})

        # Return robot to parking station on manual stop
        try:
            await self.sim_for(run_id).reset_robot()
            logger.info("Run %s: robot returned to parking after manual stop", run_id)
        except Exception:
            pass

    async def pause_run(self, db: Session, run_id: str) -> None:
        """Pause a running run — loop continues but stops executing actions."""
        run = db.query(Run).filter(Run.id == run_id).first()
        if not run or run.status != "running":
            return

        if run_id not in self._pause_flags:
            self._pause_flags[run_id] = asyncio.Event()
        self._pause_flags[run_id].set()  # set = paused

        run.status = "paused"
        # Sync parent mission status
        from app.db.models import Mission
        mission = db.query(Mission).filter(Mission.id == run.mission_id).first()
        if mission and mission.status == "executing":
            mission.status = "paused"
        db.commit()

        # Send STOP to simulator
        try:
            await self.sim_for(run_id).send_command({"intent": "STOP", "params": {}})
        except Exception:
            pass

        self._append_event(db, run_id, "INTERVENTION", {
            "type": "PAUSE",
            "actor": "operator",
            "reason": "Run paused by operator",
        })
        db.commit()

        if self._ws_broadcast:
            await self._ws_broadcast(run_id, {"kind": "status", "data": {"status": "paused"}})

    def _restore_plan(self, db: Session, run_id: str) -> int:
        """Rebuild the remaining plan from the hash-chained events: the latest PLAN, minus
        every waypoint before the last one actually sent and acknowledged. Returns how many remain."""
        events = db.query(Event).filter(Event.run_id == run_id).order_by(Event.ts.asc()).all()
        waypoints: List[Dict[str, Any]] = []
        last_target = None
        for e in events:
            try:
                payload = json.loads(e.payload_json)
            except (TypeError, ValueError):
                continue
            if e.type == "PLAN":
                waypoints = list((payload.get("plan") or {}).get("waypoints") or [])
                last_target = None
            elif e.type == "EXECUTION":
                cmd = payload.get("command") or {}
                res = payload.get("result") or {}
                if cmd.get("intent") == "MOVE_TO" and (res.get("ok") or res.get("ack")) and not res.get("rejected"):
                    last_target = cmd.get("params") or None
        if last_target and waypoints:
            for i, wp in enumerate(waypoints):
                if math.hypot(float(wp["x"]) - float(last_target.get("x", 1e9)),
                              float(wp["y"]) - float(last_target.get("y", 1e9))) < 0.05:
                    waypoints = waypoints[i:]   # resume toward the waypoint it was heading to
                    break
        if waypoints:
            self._plans[run_id] = waypoints
        return len(waypoints)

    async def resume_run(self, db: Session, run_id: str, *, operator_control=False) -> Optional[Dict[str, Any]]:
        """Resume a paused run, after the same checks a restart needs.

        Raises Rejected if a kill switch covers this robot or mission. Moves whose
        outcome was lost are settled with the controller first; nothing is replayed."""
        run = db.query(Run).filter(Run.id == run_id).first()
        if not run or run.status != "paused":
            return None
        if run_id in self._operator_busy and not operator_control:
            raise Rejected('operator_action_in_progress')
        task = self._tasks.get(run_id)
        idle = self._tick_idle.get(run_id)
        if (task and not task.done() and idle is not None and not idle.is_set()
                and self._pause_flags.get(run_id) and self._pause_flags[run_id].is_set()):
            raise Rejected('operator_tick_not_settled')
        authority = get_authority()
        from app.config import settings as _resume_settings
        locks = [(s, i) for s, i in authority.kills.active()
                 if s == "global" or (s == "robot" and i == self.robot_for(run_id))
                 or (s == "mission" and i == run.mission_id)
                 or (s == "agent" and i == f"planner:{_resume_settings.planner_provider}")]
        if locks:
            raise Rejected("kill_switch_active")
        settled: List[Dict[str, Any]] = []
        try:
            tel = await self.sim_for(run_id).get_telemetry()
            settled = authority.reconcile_in_doubt(run.mission_id, tel)
        except Rejected:
            raise
        except Exception as exc:
            if authority.checkpoints.in_doubt(run.mission_id):
                raise Rejected("controller_unreachable_cannot_reconcile") from exc
        for s in settled:
            self._append_event(db, run_id, "AUTHORITY", {"event": "reconciled", "on": "resume", **s})
        remaining = len(self._plans[run_id]) if run_id in self._plans else self._restore_plan(db, run_id)
        if remaining:
            self._append_event(db, run_id, "AUTHORITY", {"event": "plan_restored", "waypoints_remaining": remaining})

        run.status = "running"
        # Sync parent mission status
        from app.db.models import Mission
        mission = db.query(Mission).filter(Mission.id == run.mission_id).first()
        if mission and mission.status in ("paused", "draft"):
            mission.status = "executing"
        db.commit()

        # Clear pause flag
        if run_id in self._pause_flags:
            self._pause_flags[run_id].clear()

        # Re-launch loop if needed
        self._launch_loop(run_id)

        self._append_event(db, run_id, "INTERVENTION", {
            "type": "RESUME",
            "actor": "operator",
            "reason": "Run resumed by operator",
        })
        db.commit()

        if self._ws_broadcast:
            await self._ws_broadcast(run_id, {"kind": "status", "data": {"status": "running"}})
        return {"reconciled": settled, "waypoints_remaining": remaining}

    async def _post_run_analytics(self, run_id: str) -> None:
        """Run heavy post-completion analytics in a background task.

        This is fire-and-forget — the run is already committed as 'completed'.
        Failures here are logged but never affect the run status.
        """
        from app.db.session import SessionLocal
        db = SessionLocal()
        try:
            # Safety validation (#14)
            try:
                from app.services.safety_validator import validate_run_safety
                safety = validate_run_safety(db, run_id)
                if safety and safety.get("verdict") in ("FAILED", "FAILED_SAFETY"):
                    run = db.query(Run).filter(Run.id == run_id).first()
                    if run:
                        run.status = "failed_safety"
                        db.commit()
                        logger.warning("Run %s failed safety validation: %s", run_id, safety.get("violations"))
            except Exception as sv_err:
                logger.warning("Post-run safety validation error for %s: %s", run_id, sv_err)

            # Cross-run learning (#18) — limit to 5 recent runs to avoid DB overload
            try:
                from app.services.cross_run_learning import aggregate_cross_run_lessons
                aggregate_cross_run_lessons(db, limit=5)
            except Exception as crl_err:
                logger.warning("Post-run cross-run learning error for %s: %s", run_id, crl_err)

            # Extract lessons (#18)
            try:
                from app.services.persistent_memory import PersistentMemory
                pmem = PersistentMemory()
                pmem.extract_lessons_from_run(db, run_id)
            except Exception as les_err:
                logger.warning("Post-run lesson extraction error for %s: %s", run_id, les_err)
        except Exception as e:
            logger.warning("Post-run analytics failed for %s: %s", run_id, e)
        finally:
            db.close()

    MAX_CONSECUTIVE_TICK_ERRORS = 5
    AGENT_PROPOSAL_TIMEOUT = 15  # seconds

    async def _refresh_environment_plan(self, db, run_id, telemetry, goal, *, force=False):
        """Stop and replace an obsolete plan before evaluating any new move."""
        from app.autonomy.experience import context_from_state, context_from_world
        from app.policies.versioning import policy_version_hash
        from app.services.environment_lifecycle import constraints_key, get_lifecycle
        from app.services.site_router import route_plan, last_route_info
        context = context_from_state(telemetry, policy_version_hash())
        if context is None:
            return False
        changes = get_lifecycle().observe(telemetry, policy_version_hash())
        signature = {"context": context, "constraints": constraints_key(telemetry)}
        previous = self._plan_contexts.get(run_id)
        if not force and previous == signature and run_id not in self._environment_holds:
            return False
        await self.sim_for(run_id).send_command({"intent": "STOP", "params": {}})
        world = await self.sim_for(run_id).get_world()
        world_context = context_from_world(world, policy_version_hash())
        # /world describes shared geometry; capability identity belongs to the selected robot.
        if not world_context or any(world_context[k] != context[k] for k in ('site_id', 'map_version')):
            raise Rejected("environment_changed_during_replan")
        if force:
            controlled = db.get(Run, run_id)
            db.refresh(controlled)
            if controlled.status != 'paused':
                raise Rejected('operator_run_changed')
        waypoints = route_plan(world, telemetry, goal, ZONE_SPEED_LIMITS, hazards=telemetry.get("site_constraints"))
        was_holding = run_id in self._environment_holds
        self._plans[run_id] = waypoints or []
        self._plan_contexts[run_id] = signature
        if waypoints:
            self._environment_holds.discard(run_id)
        else:
            self._environment_holds.add(run_id)
        if force or previous != signature or (was_holding and waypoints):
            self._append_event(db, run_id, "ENVIRONMENT_CHANGE", {
                "previous": previous, "current": signature,
                "action": "replanned" if waypoints else "holding_no_route", "waypoints": len(waypoints or []),
                "changes": [c["id"] for c in changes], "reason": "Environment assumptions changed; old plan discarded",
            })
            self._append_event(db, run_id, "EXPERIENCE_RETRIEVAL", dict(last_route_info))
            if force:
                self._append_event(db, run_id, 'PLAN', {
                    'plan': {'waypoints': waypoints or [], 'model_used': 'site_router'},
                    'source': 'operator_replan', 'map_version': context['map_version'],
                    'context': context, 'holding': not bool(waypoints),
                })
        return True

    async def _execute_permitted(self, db: Session, run_id: str, mission_id: str,
                                 intent: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Send an APPROVED command. A MOVE_TO only goes out with a single-use permit
        for exactly these parameters, through the one dispatch path; the simulator
        checks the permit again. STOP and WAIT need no permit (stopping is always allowed).

        Returns the simulator's answer, or {"ok": False, "rejected": True, ...} when
        authority refused the move (the robot is then told to stop)."""
        sim = self.sim_for(run_id)
        robot_id = self.robot_for(run_id)
        if intent != "MOVE_TO":
            return await sim.send_command({"intent": intent, "params": params})
        if self._pause_flags.get(run_id) and self._pause_flags[run_id].is_set():
            return {'ok':False,'rejected':True,'reason':'run_paused'}
        authority = get_authority()
        from app.config import settings as _cfg
        from app.policies.params import active_params, params_hash
        try:
            action, token = authority.authorize_or_count(
                run_id=run_id, mission_id=mission_id, intent=intent, params=params,
                decision="APPROVED", policy_version=params_hash(active_params()),
                agent_id=f"planner:{_cfg.planner_provider}", robot_id=robot_id,
            )
            result = await authority.dispatch(run_id, action, token, sim)
        except Rejected as exc:
            reason = str(exc)
            unknown = reason.startswith("controller_outcome_unknown")
            self._append_event(db, run_id, "ALERT" if unknown else "AUTHORITY", {
                "event": "command_outcome_unknown" if unknown else "permit_refused",
                "reason": reason, "intent": intent, "params": params,
            })
            try:   # contain it: an uncertain or refused move ends with the robot stopped
                await self.sim_for(run_id).send_command({"intent": "STOP", "params": {}})
            except Exception:
                pass
            if reason.startswith("trajectory_"):
                # The path check refused it: count it like a gate denial so the loop replans
                self._wp_denial_counts[run_id] = self._wp_denial_counts.get(run_id, 0) + 1
            from app.observability import tracing
            tracing.mission_event(run_id, "permit", inputs={"intent": intent, "params": params},
                                  outputs={"permit": "outcome unknown" if unknown else "refused", "reason": reason},
                                  error=reason if unknown else None)
            return {"ok": False, "rejected": not unknown, "reason": reason}
        self._append_event(db, run_id, "AUTHORITY", {
            "event": "permit_used" if not result.get("rejected") else "controller_refused",
            "action_id": action.action_id, "world_version": action.world_version,
            "policy_version": action.policy_version, "reason": result.get("reason"),
        })
        from app.observability import tracing
        tracing.mission_event(run_id, "permit", inputs={"intent": intent, "params": params},
                              outputs={"permit": "used" if not result.get("rejected") else "refused by controller",
                                       "action_id": action.action_id, "world_version": action.world_version,
                                       "controller": result})
        return result

    async def _run_loop(self, run_id: str) -> None:
        """Core tick-based control loop for a single run.

        Each tick:
          1. Read telemetry from the simulator.
          2. Validate telemetry plausibility (anti-spoofing).
          3. Detect stagnation (robot not moving).
          4. Obtain an action proposal — either the next planned waypoint
             or a live agent/LLM proposal.
          5. Evaluate the proposal through the governance engine.
          6. If approved, execute the command on the simulator.
          7. If denied repeatedly, trigger autonomous re-planning.
          8. Record every decision in the hash-chained event log.
          9. Broadcast state to the frontend via WebSocket.

        The loop exits when the robot reaches the goal (STOP approved),
        the operator stops/pauses, or too many consecutive errors occur.
        """
        # IMPORTANT: DB sessions are not thread-safe; create per tick iteration.
        from app.db.session import SessionLocal
        from app.db.models import Mission

        last_governance: Optional[Dict[str, Any]] = None
        consecutive_errors = 0

        logger.info("Run loop started: %s", run_id)
        try:
            while True:
                # stop?
                if self._stop_flags.get(run_id) and self._stop_flags[run_id].is_set():
                    break

                # paused? — sleep and re-check
                if self._pause_flags.get(run_id) and self._pause_flags[run_id].is_set():
                    await asyncio.sleep(0.5)
                    continue

                idle = self._tick_idle.setdefault(run_id, asyncio.Event())
                idle.clear()
                db = SessionLocal()
                try:
                    run = db.query(Run).filter(Run.id == run_id).first()
                    if not run or run.status not in ("running",):
                        break

                    # Public demo: missions stop on their own so the shared robot frees up
                    from app.config import settings as _cfg
                    if _cfg.public_demo and run.started_at is not None:
                        started = run.started_at.replace(tzinfo=None)
                        if (utc_now().replace(tzinfo=None) - started).total_seconds() > _cfg.demo_max_run_s:
                            try:
                                await self.sim_for(run_id).send_command({"intent": "STOP", "params": {}})
                            except Exception:
                                pass
                            run.status = "stopped"
                            run.ended_at = utc_now()
                            if mission_row := db.query(Mission).filter(Mission.id == run.mission_id).first():
                                if mission_row.status == "executing":
                                    mission_row.status = "paused"
                            self._append_event(db, run_id, "INTERVENTION", {
                                "type": "STOP", "actor": "system",
                                "reason": f"Public demo time limit ({int(_cfg.demo_max_run_s)} s)",
                            })
                            db.commit()
                            if self._ws_broadcast:
                                await self._ws_broadcast(run_id, {"kind": "status", "data": {"status": "stopped",
                                                         "reason": "Public demo time limit"}})
                            break
                    mission = db.query(Mission).filter(Mission.id == run.mission_id).first()
                    goal = json.loads(mission.goal_json) if mission else {"x": 0, "y": 0}

                    telemetry = await self.sim_for(run_id).get_telemetry()
                    tel_fetched_at = time.monotonic()
                    authority = get_authority()
                    authority.heartbeat(run_id)
                    if mission is not None:
                        for settled in authority.reconcile_in_doubt(mission.id, telemetry):
                            self._append_event(db, run_id, "AUTHORITY", {"event": "reconciled", **settled})

                    # Site intelligence: hazard zones (Tavily-informed, firewall-screened)
                    # join the telemetry the gate sees; their audit events join this run's chain.
                    try:
                        from app.services.site_intel.service import site_intel
                        telemetry = site_intel.observe(telemetry)
                        for etype, epayload in site_intel.drain_events():
                            self._append_event(db, run_id, etype, epayload)
                    except Exception as si_err:
                        logger.warning("Run %s: site intel failed: %s", run_id, si_err)

                    # Vision: Meta SAM 3.1 reads the robot camera in the background.
                    # Results are cross-checked with the sensors and recorded here; an
                    # unconfirmed sighting only adds a short slow zone (never less caution).
                    try:
                        from app.services.perception import perception, audit_summary
                        for res in perception.drain_results(run_id):
                            self._append_event(db, run_id, "PERCEPTION", audit_summary(res))
                            if self._ws_broadcast:
                                await self._ws_broadcast(run_id, {"kind": "perception", "data": res})
                        if perception.due(run_id):
                            asyncio.create_task(perception.run_check(self.sim_for(run_id), dict(telemetry), run_id))
                        telemetry = perception.apply(telemetry)
                    except Exception as vis_err:
                        logger.warning("Run %s: vision step failed: %s", run_id, vis_err)

                    # --- Anti-spoofing: validate telemetry plausibility ---
                    if await self._refresh_environment_plan(db, run_id, telemetry, goal):
                        await asyncio.sleep(0.2)
                        continue
                    if run_id not in self._tel_validators:
                        self._tel_validators[run_id] = TelemetryValidator(run_id)
                    tv_result = self._tel_validators[run_id].validate(telemetry)
                    if tv_result.hard_anomaly:
                        # Hard anomaly = untrusted telemetry → emergency stop
                        anomaly_detail = "; ".join(a.detail for a in tv_result.anomalies if a.severity == "hard")
                        logger.error(
                            "Run %s: HARD telemetry anomaly — forcing stop: %s",
                            run_id, anomaly_detail,
                        )
                        self._append_event(db, run_id, "ALERT", {
                            "event": "telemetry_anomaly",
                            "severity": "hard",
                            "detail": anomaly_detail,
                            "anomalies": [{"type": a.type, "detail": a.detail, "field": a.field} for a in tv_result.anomalies],
                        })
                        # Send STOP to sim and abort tick
                        try:
                            await self.sim_for(run_id).send_command({"intent": "STOP", "params": {}})
                        except Exception:
                            pass
                        db.commit()
                        if self._ws_broadcast:
                            await self._ws_broadcast(run_id, {
                                "kind": "alert",
                                "data": {"event": "TELEMETRY_ANOMALY", "severity": "hard", "detail": anomaly_detail},
                            })
                        await asyncio.sleep(1)
                        continue
                    elif tv_result.anomalies:
                        # Soft anomalies — log but continue
                        self._append_event(db, run_id, "ALERT", {
                            "event": "telemetry_anomaly",
                            "severity": "soft",
                            "anomalies": [{"type": a.type, "detail": a.detail, "field": a.field} for a in tv_result.anomalies],
                        })

                    # Store telemetry sample
                    self.tel.add_sample(db, run_id, telemetry)

                    # --- Diagnostics: distance to goal & stagnation detection ---
                    try:
                        tx, ty = float(telemetry.get("x", 0.0)), float(telemetry.get("y", 0.0))
                        gx, gy = float(goal.get("x", 0.0)), float(goal.get("y", 0.0))
                        distance_to_goal = ((tx - gx) ** 2 + (ty - gy) ** 2) ** 0.5
                    except Exception:
                        distance_to_goal = None

                    prev = self._last_positions.get(run_id)
                    moved = None
                    if prev:
                        try:
                            moved = ((tx - prev[0]) ** 2 + (ty - prev[1]) ** 2) ** 0.5
                        except Exception:
                            moved = None

                    # Update stagnant counters
                    if moved is None or moved < self.STAGNATION_THRESHOLD_M:
                        self._stagnant_counts[run_id] = self._stagnant_counts.get(run_id, 0) + 1
                    else:
                        self._stagnant_counts[run_id] = 0
                    self._last_positions[run_id] = (tx, ty)

                    stagnant_cycles = self._stagnant_counts.get(run_id, 0)
                    # Emit a STAGNATION event if we've been stagnant for too long
                    if stagnant_cycles >= self.STAGNATION_CYCLES:
                        try:
                            st_payload = {
                                "reason": "Robot movement below threshold",
                                "stagnant_cycles": stagnant_cycles,
                                "distance_to_goal": distance_to_goal,
                            }
                            self._append_event(db, run_id, "STAGNATION", st_payload)
                            if self._ws_broadcast:
                                await self._ws_broadcast(run_id, {"kind": "alert", "data": {"event": "STAGNATION", "payload": st_payload}})
                        except Exception:
                            pass

                    # Stream telemetry
                    if self._ws_broadcast:
                        await self._ws_broadcast(run_id, {"kind": "telemetry", "data": telemetry})

                    # Simple alerting (MVP): forward simulator events
                    sim_events = telemetry.get("events") or []
                    for e in sim_events:
                        if self._ws_broadcast:
                            await self._ws_broadcast(run_id, {"kind": "alert", "data": {"event": e}})

                    # If an explicit plan exists for this run, follow it waypoint-by-waypoint.
                    proposal: ActionProposal
                    nl_task = mission.title if mission else "Navigate to goal"

                    # Snapshot plan under lock to avoid races with LLM plan upgrades.
                    # A waypoint is done when the robot reaches it, not when it is commanded:
                    # skipping ahead let the robot cut corners straight through racking.
                    async with self._plans_lock:
                        plan_wps = self._plans.get(run_id)
                        tx_, ty_ = float(telemetry.get("x", 0)), float(telemetry.get("y", 0))
                        while plan_wps and len(plan_wps) > 1 and math.hypot(
                                float(plan_wps[0].get("x", 0)) - tx_, float(plan_wps[0].get("y", 0)) - ty_) < self.WAYPOINT_REACHED_M:
                            plan_wps.pop(0)
                        wp = plan_wps[0] if plan_wps else None
                    if not wp and goal and math.hypot(float(telemetry.get("x", 0)) - float(goal.get("x", 0)),
                                                      float(telemetry.get("y", 0)) - float(goal.get("y", 0))) > 0.5:
                        # Plan used up before the goal: route the rest along the aisles rather than straight at it
                        try:
                            from app.services.site_router import route_plan
                            routed = route_plan(await self.sim_for(run_id).get_world(), telemetry, goal, ZONE_SPEED_LIMITS,
                                                hazards=telemetry.get("site_constraints"))
                        except Exception as route_err:
                            routed = None
                            logger.warning("Run %s: aisle routing failed: %s", run_id, route_err)
                        if routed:
                            async with self._plans_lock:
                                self._plans[run_id] = routed
                            wp = routed[0]
                    # Hazard zones: back out if inside one; route round one; hold if no route
                    hazard_proposal = None
                    hold_reason = None
                    zones = telemetry.get("site_constraints") or []
                    if zones:
                        from app.services.site_router import crosses_hazard, hazard_exit_point
                        rx_, ry_ = float(telemetry.get("x", 0)), float(telemetry.get("y", 0))
                        inside_z = next((z for z in zones if math.hypot(rx_ - float(z["x"]), ry_ - float(z["y"])) < float(z["radius"])), None)
                        if inside_z:
                            site_w = await self.sim_for(run_id).get_world()
                            exit_pt = hazard_exit_point(site_w, rx_, ry_, inside_z)
                            if exit_pt:
                                hazard_proposal = ActionProposal(
                                    intent="MOVE_TO",
                                    params={"x": exit_pt[0], "y": exit_pt[1], "max_speed": min(float(inside_z["max_speed"]), 0.2)},
                                    rationale=f"Backing slowly out of the {inside_z.get('label', 'hazard')} zone",
                                )
                            else:
                                hold_reason = f"Inside the {inside_z.get('label', 'hazard')} zone with no clear way out — holding for the operator"
                        elif wp and crosses_hazard(telemetry, [wp], zones):
                            from app.services.site_router import route_plan as _rp
                            around = _rp(await self.sim_for(run_id).get_world(), telemetry, goal, ZONE_SPEED_LIMITS, hazards=zones)
                            if around:
                                async with self._plans_lock:
                                    self._plans[run_id] = around
                                wp = around[0]
                            else:
                                blocking = next((z for z in zones if crosses_hazard(telemetry, [wp], [z])), zones[0])
                                hold_reason = (f"Every route to the goal passes through the {blocking.get('label', 'hazard')} zone — "
                                               "holding until it is cleared")
                    if hold_reason:
                        hazard_proposal = ActionProposal(intent="WAIT", params={"seconds": 1}, rationale=hold_reason)
                        self._stagnant_counts[run_id] = 0      # holding on purpose, not stalled
                        if self._hazard_holds.get(run_id) != hold_reason:
                            self._hazard_holds[run_id] = hold_reason
                            self._append_event(db, run_id, "ALERT", {"event": "HAZARD_HOLD", "reason": hold_reason})
                            if self._ws_broadcast:
                                await self._ws_broadcast(run_id, {"kind": "alert", "data": {"event": "HAZARD_HOLD", "reason": hold_reason}})
                    elif self._hazard_holds.pop(run_id, None):
                        self._append_event(db, run_id, "ALERT", {"event": "HAZARD_HOLD_RELEASED", "reason": "Route clear again — resuming"})

                    near_xy = telemetry.get("nearest_obstacle_xy")
                    if hazard_proposal is not None:
                        proposal = hazard_proposal
                    elif (last_governance and "OBSTACLE_CLEARANCE_03" in (last_governance.get("policy_hits") or [])
                            and near_xy and float(telemetry.get("nearest_obstacle_m", 9.0)) < 0.5):
                        # Too close to something: back away slowly (the one move the gate allows here)
                        ax_, ay_ = float(telemetry.get("x", 0)) - float(near_xy[0]), float(telemetry.get("y", 0)) - float(near_xy[1])
                        n_ = math.hypot(ax_, ay_) or 1e-9
                        proposal = ActionProposal(
                            intent="MOVE_TO",
                            params={"x": float(telemetry.get("x", 0)) + ax_ / n_ * 0.8,
                                    "y": float(telemetry.get("y", 0)) + ay_ / n_ * 0.8, "max_speed": 0.25},
                            rationale="Slow retreat from obstacle",
                        )
                    elif wp:
                        proposal = ActionProposal(
                            intent="MOVE_TO",
                            params={"x": float(wp.get("x")), "y": float(wp.get("y")), "max_speed": float(wp.get("max_speed", 0.5))},
                            rationale="Following plan waypoint",
                        )
                    else:
                        # No plan — agent proposes action (may call LLM).
                        # Commit first so no write lock is held during the model call.
                        db.commit()
                        world_state = None
                        try:
                            world_state = await self.sim_for(run_id).get_world()
                        except Exception:
                            pass
                        try:
                            async with asyncio.timeout(self.AGENT_PROPOSAL_TIMEOUT):
                                proposal = await self.agent.propose(telemetry, goal, nl_task, last_governance, world_state)
                        except (asyncio.TimeoutError, Exception) as prop_err:
                            logger.warning("Run %s: agent proposal failed/timed out: %s — using deterministic fallback", run_id, prop_err)
                            proposal = self.agent.simple.propose(telemetry, goal, last_governance)
                    # Clamp planned max_speed to zone limits and human proximity
                    if proposal.intent == "MOVE_TO":
                        zone = telemetry.get("zone", "aisle")
                        limit = float(ZONE_SPEED_LIMITS.get(zone, 0.5))
                        p = proposal.params or {}
                        clamped = min(float(p.get("max_speed", 0.5)), limit)
                        # Also clamp near humans (slow-radius preemption)
                        human_dist = float(telemetry.get("human_distance_m", 999.0))
                        if human_dist < 3.0:
                            clamped = min(clamped, 0.3)
                        # And near hazard zones (the gate enforces this too)
                        from app.services.site_router import capped_speed
                        clamped = capped_speed(float(telemetry.get("x", 0)), float(telemetry.get("y", 0)), clamped,
                                               telemetry.get("site_constraints"))
                        if "x" in p and "y" in p:
                            clamped = capped_speed(float(p["x"]), float(p["y"]), clamped, telemetry.get("site_constraints"))
                        p["max_speed"] = clamped
                        proposal.params = p

                    if reviewed := self._review_proposals.pop(run_id, None):
                        proposal = reviewed
                    proposal_payload = proposal.model_dump()

                    # The gate must judge fresh positions: if planning took a while, re-read
                    # the robot and people, then record this as the world version a permit binds to.
                    if time.monotonic() - tel_fetched_at > settings_world_age() / 2:
                        try:
                            telemetry.update(await self.sim_for(run_id).get_telemetry())
                        except Exception as fresh_err:
                            logger.warning("Run %s: telemetry refresh failed: %s", run_id, fresh_err)
                    if await self._refresh_environment_plan(db, run_id, telemetry, goal):
                        await asyncio.sleep(0.2)
                        continue
                    authority.observe(telemetry, robot_id=self.robot_for(run_id))

                    # Governance evaluates and persists decision
                    gov_decision = self.gov.evaluate_and_record(
                        db, run_id, telemetry, proposal,
                    )
                    gov_payload = gov_decision.model_dump()

                    # Chain-of-trust event (decision)
                    decision_event_payload = {
                        "context": {
                            "telemetry": telemetry,
                            "mission_goal": goal,
                        },
                        "proposal": proposal_payload,
                        "governance": gov_payload,
                    }

                    decision_evt = self._append_event(db, run_id, "DECISION", decision_event_payload)
                    from app.observability import tracing as _tracing
                    _tracing.mission_event(run_id, "gate", inputs={"proposal": proposal_payload,
                                                                   "position": {k: telemetry.get(k) for k in ("x", "y", "speed", "zone")}},
                                           outputs={"decision": gov_decision.decision, "state": gov_decision.policy_state,
                                                    "policy_hits": gov_decision.policy_hits, "reasons": gov_decision.reasons[:5]})

                    # --- Runtime integrity check (anti-gaming) ---
                    if run_id not in self._integrity_checkers:
                        self._integrity_checkers[run_id] = RuntimeIntegrityChecker(run_id)
                    gaming_flags = self._integrity_checkers[run_id].check_tick(
                        proposal.intent,
                        proposal.params or {},
                        gov_decision.decision,
                    )
                    if gaming_flags:
                        self._append_event(db, run_id, "ALERT", {
                            "event": "runtime_integrity",
                            "flags": gaming_flags,
                        })
                        if self._ws_broadcast:
                            await self._ws_broadcast(run_id, {
                                "kind": "alert",
                                "data": {"event": "RUNTIME_INTEGRITY", "flags": gaming_flags},
                            })

                    # If approved, execute
                    execution = None
                    was_executed = False
                    if gov_decision.decision == "APPROVED":
                        # Reset waypoint denial counter on approval
                        self._wp_denial_counts[run_id] = 0
                        self._path_blocked.pop(run_id, None)

                        cmd = {"intent": proposal.intent, "params": proposal.params}
                        execution = await self._execute_permitted(
                            db, run_id, mission.id if mission else run.mission_id, proposal.intent, proposal.params or {})

                        # --- Execution verification: confirm sim actually responded ---
                        exec_verified = False
                        try:
                            # Check the response from send_command directly
                            if proposal.intent == "MOVE_TO":
                                sim_ack = execution.get("ok", False) or execution.get("ack", False)
                                exec_verified = sim_ack
                            elif proposal.intent == "STOP":
                                sim_ack = execution.get("ok", False) or execution.get("stopped", False)
                                exec_verified = sim_ack
                            else:
                                exec_verified = True
                        except Exception as verify_err:
                            logger.warning("Run %s: execution verification failed: %s", run_id, verify_err)
                            exec_verified = True  # fail-open on verification errors to avoid blocking

                        exec_payload = {"command": cmd, "result": execution, "verified": exec_verified}
                        self._append_event(db, run_id, "EXECUTION", exec_payload)
                        was_executed = True

                        if not exec_verified:
                            self._append_event(db, run_id, "ALERT", {
                                "event": "execution_unverified",
                                "detail": "Simulator did not acknowledge command execution",
                                "command": cmd,
                            })

                        # Track executed path
                        self._executed_paths.setdefault(run_id, []).append({
                            "x": round(float(telemetry.get("x", 0)), 4),
                            "y": round(float(telemetry.get("y", 0)), 4),
                            "speed": round(float(telemetry.get("speed", 0)), 4),
                            "ts": utc_now().isoformat(),
                        })

                        # The waypoint stays in the plan until the robot reaches it (checked each
                        # tick above), so every tick re-submits the move to the gate.
                        if wp and len(self._plans.get(run_id) or []) == 1:
                            gx_, gy_ = float(wp.get("x", 0)), float(wp.get("y", 0))
                            if math.hypot(gx_ - float(telemetry.get("x", 0)), gy_ - float(telemetry.get("y", 0))) < self.WAYPOINT_REACHED_M:
                                async with self._plans_lock:
                                    self._plans.pop(run_id, None)
                    else:
                        # Denied or NEEDS_REVIEW: stop the robot. Without this the simulator kept
                        # driving to the last approved target, so a denial only withheld a new one.
                        try:
                            stop_ack = await self.sim_for(run_id).send_command({"intent": "STOP", "params": {}})
                        except Exception as stop_err:
                            stop_ack = {"ok": False, "error": str(stop_err)}
                        self._append_event(db, run_id, "EXECUTION", {
                            "command": {"intent": "STOP", "params": {}},
                            "result": stop_ack,
                            "verified": bool(stop_ack.get("ok") or stop_ack.get("stopped")),
                            "enforced_by_gate": True,
                            "decision": gov_decision.decision,
                            "policy_hits": gov_decision.policy_hits,
                        })

                        # Increment waypoint denial counter
                        self._wp_denial_counts[run_id] = self._wp_denial_counts.get(run_id, 0) + 1
                        denial_count = self._wp_denial_counts[run_id]

                        # NEEDS_REVIEW: execute cautiously at reduced speed (soft policy hit)
                        # Only pause if NEEDS_REVIEW persists for too many consecutive ticks
                        if (gov_decision.decision == "NEEDS_REVIEW" and not gov_decision.hard_fail
                                and not self._path_blocked.get(run_id)):
                            NEEDS_REVIEW_PAUSE_THRESHOLD = 5  # pause after 5 consecutive NEEDS_REVIEW
                            if denial_count >= NEEDS_REVIEW_PAUSE_THRESHOLD:
                                logger.warning("Run %s: %d consecutive NEEDS_REVIEW — pausing for operator", run_id, denial_count)
                                run.status = "paused"
                                if mission and mission.status == "executing":
                                    mission.status = "paused"
                                self._append_event(db, run_id, "INTERVENTION", {
                                    "type": "AUTO_PAUSE",
                                    "reason": "Repeated governance review required — pausing for operator",
                                    "policy_hits": gov_decision.policy_hits,
                                    "denial_count": denial_count,
                                })
                                db.commit()
                                if self._ws_broadcast:
                                    await self._ws_broadcast(run_id, {
                                        "kind": "status",
                                        "data": {
                                            "status": "paused",
                                            "reason": "needs_operator_review",
                                            "policy_hits": gov_decision.policy_hits,
                                            "denial_reasons": gov_decision.reasons,
                                        },
                                    })
                                if run_id not in self._pause_flags:
                                    self._pause_flags[run_id] = asyncio.Event()
                                self._pause_flags[run_id].set()
                            else:
                                # Soft review: try the same move slower — but only if the gate
                                # approves that slower move too. Nothing executes unapproved.
                                cautious_params = dict(proposal.params or {})
                                cautious_params["max_speed"] = min(float(cautious_params.get("max_speed", 0.5)), 0.2)
                                # The STOP above advanced the controller generation. Judge and permit the
                                # slower move against the robot as it is now, or the controller refuses
                                # the permit as stale on every tick and the robot never moves again.
                                try:
                                    telemetry.update(await self.sim_for(run_id).get_telemetry())
                                except Exception as fresh_err:
                                    logger.warning("Run %s: telemetry refresh after stop failed: %s", run_id, fresh_err)
                                cautious = ActionProposal(intent=proposal.intent, params=cautious_params,
                                                          rationale=f"{proposal.rationale} (slowed after review)")
                                recheck = self.gov.evaluate_and_record(db, run_id, telemetry, cautious)
                                self._append_event(db, run_id, "DECISION", {
                                    "proposal": cautious.model_dump(),
                                    "governance": recheck.model_dump(),
                                    "note": "re-evaluated at reduced speed after NEEDS_REVIEW",
                                })
                                if recheck.decision == "APPROVED":
                                    logger.info("Run %s: NEEDS_REVIEW — slower move approved (count %d)", run_id, denial_count)
                                    cmd = {"intent": cautious.intent, "params": cautious_params}
                                    authority.observe(telemetry, robot_id=self.robot_for(run_id))
                                    execution = await self._execute_permitted(
                                        db, run_id, mission.id if mission else run.mission_id, cautious.intent, cautious_params)
                                    exec_verified = execution.get("ok", False) or execution.get("ack", False)
                                    if execution.get("rejected"):
                                        # The controller refused it: count it, so repeated refusals replan
                                        self._wp_denial_counts[run_id] = self._wp_denial_counts.get(run_id, 0) + 1
                                        if str(execution.get("reason", "")).startswith("trajectory_"):
                                            self._path_blocked[run_id] = True   # slower won't help: route around
                                    else:
                                        self._wp_denial_counts[run_id] = 0   # moving under an approved decision
                                    self._append_event(db, run_id, "EXECUTION", {
                                        "command": cmd,
                                        "result": execution,
                                        "verified": exec_verified,
                                        "cautious": True,
                                        "governance_state": recheck.policy_state,
                                    })
                                    was_executed = True
                                # (if not approved, the robot stays stopped)

                        elif (denial_count >= self.REPLAN_DENIAL_THRESHOLD
                              or (gov_decision.hard_fail and denial_count >= 3)) and wp:
                            # Trigger replanning: discard blocked waypoint and request new plan
                            blocked_wp = wp
                            self._path_blocked.pop(run_id, None)
                            logger.warning(
                                "Run %s: %d consecutive denials on waypoint %s — triggering replan",
                                run_id, denial_count, blocked_wp,
                            )
                            # Remove the blocked waypoint
                            async with self._plans_lock:
                                try:
                                    cur = self._plans.get(run_id)
                                    if cur:
                                        cur.pop(0)
                                        if not cur:
                                            self._plans.pop(run_id, None)
                                except Exception:
                                    pass

                            # Record replan event in chain-of-trust
                            replan_payload = {
                                "reason": "repeated_denial",
                                "denial_count": denial_count,
                                "blocked_waypoint": blocked_wp,
                                "policy_hits": gov_decision.policy_hits,
                                "policy_state": gov_decision.policy_state,
                            }
                            self._append_event(db, run_id, "REPLAN", replan_payload)
                            # Commit before calling the model: an open write transaction would
                            # hold SQLite's write lock for the whole call (up to ~30 s) and block
                            # an operator's stop.
                            db.commit()

                            # Attempt to generate a new plan via LLM
                            try:
                                denial_context = ", ".join(gov_decision.reasons) if gov_decision.reasons else "policy violation"
                                replan_instruction = (
                                    f"{nl_task}. Previous waypoint at ({blocked_wp.get('x')},{blocked_wp.get('y')}) "
                                    f"was blocked: {denial_context}. Plan an alternative route avoiding that area."
                                )
                                lessons = []
                                try:
                                    from app.services.planner_lessons import lessons_for_route
                                    lessons = lessons_for_route(db, telemetry, goal, avoid=blocked_wp)
                                except Exception as les_err:
                                    logger.warning("Run %s: lesson retrieval failed: %s", run_id, les_err)
                                planner = self.agent._gemini_planner()
                                from app.services.site_intel.service import site_intel as _si
                                from app.services.muse_planner import planning_robot
                                from app.observability import tracing as _tr
                                # Never hold a database transaction open across a model call: with
                                # two robots, a long replan would block the other robot's writes.
                                db.commit()
                                _robot_token = planning_robot.set(self.robot_for(run_id))
                                try:
                                    with _tr.within_mission(run_id):
                                        try:
                                            new_plan = await planner.generate_plan(telemetry, replan_instruction, goal, lessons=lessons,
                                                                                   untrusted_context=_si.planner_context())
                                        except TypeError:  # planners without the parameter
                                            new_plan = await planner.generate_plan(telemetry, replan_instruction, goal, lessons=lessons)
                                finally:
                                    planning_robot.reset(_robot_token)
                                try:
                                    from app.services.site_router import repair_plan, route_plan
                                    site = await self.sim_for(run_id).get_world()
                                    if new_plan.get("model_used") == "deterministic_fallback":
                                        # No model: route around the blocked spot along the aisles
                                        routed = route_plan(site, telemetry, goal, ZONE_SPEED_LIMITS, avoid=blocked_wp,
                                                            hazards=telemetry.get("site_constraints"))
                                        if routed:
                                            new_plan.update(waypoints=routed, model_used="site_router")
                                    else:
                                        fixed, n_fixed = repair_plan(site, telemetry, new_plan.get("waypoints", []), ZONE_SPEED_LIMITS)
                                        if n_fixed:
                                            new_plan.update(waypoints=fixed, repaired_legs=n_fixed)
                                        from app.services.site_router import crosses_hazard
                                        zones = telemetry.get("site_constraints")
                                        if zones and crosses_hazard(telemetry, new_plan.get("waypoints", []), zones):
                                            routed = route_plan(site, telemetry, goal, ZONE_SPEED_LIMITS, hazards=zones)
                                            if routed:
                                                new_plan.update(waypoints=routed, hazard_rerouted=True)
                                except Exception as route_err:
                                    logger.warning("Run %s: replan routing skipped: %s", run_id, route_err)
                                # Task-drift guard: a replan must still end at the mission destination
                                # (from the mission record, not the model) without wandering.
                                task_check = None
                                try:
                                    from app.services.task_guard import guard
                                    g = guard(new_plan, telemetry, goal, await self.sim_for(run_id).get_world(), ZONE_SPEED_LIMITS,
                                              hazards=telemetry.get("site_constraints"))
                                    new_plan, task_check = g["plan"], g["check"]
                                    self._append_event(db, run_id, "TASK_CHECK", {"stage": "replan", **task_check})
                                except Exception as tg_err:
                                    logger.warning("Run %s: task guard skipped: %s", run_id, tg_err)
                                new_wps = new_plan.get("waypoints", [])
                                if new_wps:
                                    async with self._plans_lock:
                                        self._plans[run_id] = new_wps
                                    replan_payload["new_plan_waypoints"] = len(new_wps)
                                    # The REPLAN event above is already hashed into the chain, so the
                                    # new plan (and the lessons that shaped it) is recorded as its own
                                    # PLAN event — auditable, and what the run view draws on the map.
                                    from app.config import settings as _settings
                                    applied = [
                                        {"id": l["id"], "text": l["text"]} for l in lessons
                                        if l["id"] in new_plan.get("lessons_applied", [])
                                    ]
                                    self._append_event(db, run_id, "PLAN", {
                                        "plan": new_plan,
                                        # site_router means the model-free fallback was routed along the aisles
                                        "source": "fallback" if new_plan.get("model_used") in ("deterministic_fallback", "site_router")
                                                  else _settings.planner_provider,
                                        "note": "Replan after governance denial",
                                        "blocked_waypoint": blocked_wp,
                                        "task_check": task_check,
                                        "lessons_offered": [{"id": l["id"], "text": l["text"]} for l in lessons],
                                        "lessons_applied": applied,
                                    })
                                    logger.info("Run %s: replanned with %d new waypoints", run_id, len(new_wps))
                            except Exception as replan_err:
                                logger.warning("Run %s: replan LLM call failed: %s", run_id, replan_err)

                            self._wp_denial_counts[run_id] = 0

                            if self._ws_broadcast:
                                await self._ws_broadcast(run_id, {
                                    "kind": "alert",
                                    "data": {"event": "REPLAN", "payload": replan_payload},
                                })

                    # Update the governance decision record with execution result and event hash
                    from app.db.models import GovernanceDecisionRecord
                    latest_gov = (
                        db.query(GovernanceDecisionRecord)
                        .filter(GovernanceDecisionRecord.run_id == run_id)
                        .order_by(GovernanceDecisionRecord.id.desc())
                        .first()
                    )
                    if latest_gov:
                        latest_gov.was_executed = "true" if was_executed else "false"
                        latest_gov.event_hash = decision_evt.hash

                    # Record outcome in agent memory (agentic mode)
                    self.agent.record_outcome(proposal, gov_decision, was_executed)

                    # Persist decision in DB-backed memory (#17)
                    try:
                        from app.services.persistent_memory import PersistentMemory
                        pmem = PersistentMemory()
                        pmem.store_decision(
                            db, run_id,
                            proposal.intent,
                            proposal.params or {},
                            gov_decision.decision,
                            gov_decision.policy_hits,
                            gov_decision.reasons,
                            was_executed,
                        )
                    except Exception:
                        pass  # non-critical

                    # Commit events/telemetry
                    db.commit()

                    # Broadcast event summary to UI
                    if self._ws_broadcast:
                        # Broadcast agent reasoning chain (agentic mode)
                        thought_chain = self.agent.last_thought_chain
                        if thought_chain:
                            await self._ws_broadcast(run_id, {
                                "kind": "agent_reasoning",
                                "data": {
                                    "steps": thought_chain,
                                    "total_steps": len(thought_chain),
                                },
                            })

                        # Compute execution_reason for UI clarity
                        execution_reason = "executed" if was_executed else f"blocked:{gov_decision.decision}"

                        await self._ws_broadcast(run_id, {
                            "kind": "event",
                            "data": {
                                "type": "DECISION",
                                "proposal": proposal_payload,
                                "governance": gov_payload,
                                "execution": execution,
                                "policy_state": gov_payload.get("policy_state", "SAFE"),
                                "execution_reason": execution_reason,
                                "distance_to_goal": distance_to_goal,
                                "stagnant_cycles": stagnant_cycles,
                                "executed_path_len": len(self._executed_paths.get(run_id, [])),
                            }
                        })

                    last_governance = gov_payload

                    # If STOP was approved, complete run
                    if proposal.intent == "STOP" and gov_decision.decision == "APPROVED":
                        run.status = "completed"
                        run.ended_at = utc_now()
                        # Also mark the parent mission as completed
                        if mission:
                            mission.status = "completed"

                        # Commit completion status IMMEDIATELY so the run is
                        # never left as "running" even if post-run analytics fail.
                        db.commit()
                        logger.info("Run %s completed (mission %s)", run_id, mission.id if mission else "?")

                        # Return robot to parking station (reset to start position)
                        try:
                            await self.sim_for(run_id).reset_robot()
                            logger.info("Run %s: robot returned to parking station", run_id)
                            # Broadcast fresh telemetry so the frontend map shows the robot back at start
                            if self._ws_broadcast:
                                try:
                                    reset_telem = await self.sim_for(run_id).get_telemetry()
                                    await self._ws_broadcast(run_id, {"kind": "telemetry", "data": reset_telem})
                                except Exception:
                                    pass
                        except Exception as reset_err:
                            logger.warning("Run %s: failed to reset robot to parking: %s", run_id, reset_err)

                        if self._ws_broadcast:
                            await self._ws_broadcast(run_id, {"kind": "status", "data": {"status": "completed"}})

                        # Fire-and-forget: heavy post-run analytics in background
                        asyncio.create_task(self._post_run_analytics(run_id))
                        break

                    # Tick succeeded — reset error counter
                    consecutive_errors = 0

                except Exception as tick_err:
                    consecutive_errors += 1
                    logger.warning(
                        "Run %s: tick error (%d/%d): %s",
                        run_id, consecutive_errors, self.MAX_CONSECUTIVE_TICK_ERRORS, tick_err,
                    )
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    if consecutive_errors >= self.MAX_CONSECUTIVE_TICK_ERRORS:
                        logger.error("Run %s: too many consecutive tick errors, marking failed", run_id)
                        try:
                            run = db.query(Run).filter(Run.id == run_id).first()
                            if run:
                                run.status = "failed"
                                run.ended_at = utc_now()
                                # Sync parent mission status
                                from app.db.models import Mission as _Mission
                                mission = db.query(_Mission).filter(_Mission.id == run.mission_id).first()
                                if mission and mission.status == "executing":
                                    mission.status = "failed"
                            if self._ws_broadcast:
                                try:
                                    reset_telem = await self.sim_for(run_id).get_telemetry()
                                    await self._ws_broadcast(run_id, {"kind": "telemetry", "data": reset_telem})
                                except Exception:
                                    pass
                                db.commit()
                        except Exception:
                            pass
                        # Return robot to parking station even on failure
                        try:
                            await self.sim_for(run_id).reset_robot()
                            logger.info("Run %s: robot returned to parking after failure", run_id)
                        except Exception:
                            pass
                        break
                finally:
                    db.close()
                    idle.set()

                await asyncio.sleep(1.0)

        except Exception as e:
            logger.exception("Run loop crashed: %s", e)
            # Mark run failed
            from app.db.session import SessionLocal
            db = SessionLocal()
            try:
                run = db.query(Run).filter(Run.id == run_id).first()
                if run:
                    run.status = "failed"
                    run.ended_at = utc_now()
                    # Sync parent mission status
                    from app.db.models import Mission as _Mission
                    mission = db.query(_Mission).filter(_Mission.id == run.mission_id).first()
                    if mission and mission.status == "executing":
                        mission.status = "failed"
                    db.commit()
            finally:
                db.close()
            if self._ws_broadcast:
                await self._ws_broadcast(run_id, {"kind": "status", "data": {"status": "failed"}})

        logger.info("Run loop ended: %s", run_id)

        # If an operator stopped the run but recording it failed, the run must not
        # stay marked "running" with no loop behind it.
        if self._stop_flags.get(run_id) and self._stop_flags[run_id].is_set():
            try:
                from app.db.session import SessionLocal
                sdb = SessionLocal()
                try:
                    run = sdb.query(Run).filter(Run.id == run_id).first()
                    if run and run.status in ("running", "planning", "paused"):
                        run.status = "stopped"
                        run.ended_at = utc_now()
                        sdb.commit()
                finally:
                    sdb.close()
            except Exception as st_err:
                logger.warning("Could not mark stopped run %s: %s", run_id, st_err)

        # Planner learning loop: distil location-aware lessons from the gate's
        # decisions for every run ending (completed, stopped or failed — denials
        # in an aborted run are often the most instructive). Idempotent per run.
        try:
            from app.db.session import SessionLocal
            from app.services.planner_lessons import distill_run
            ldb = SessionLocal()
            try:
                distill_run(ldb, run_id)
                # Signed experience for the learned router: where this run was slowed or stopped
                from app.services.route_learning import get_memory
                get_memory().record_run(ldb, run_id)
            finally:
                ldb.close()
        except Exception as dl_err:
            logger.warning("Lesson distillation failed for %s: %s", run_id, dl_err)

        # Close the mission trace with the run's final status
        try:
            from app.db.session import SessionLocal as _SL2
            from app.observability import tracing
            _tdb = _SL2()
            try:
                _r = _tdb.query(Run).filter(Run.id == run_id).first()
                tracing.mission_end(run_id, _r.status if _r else "ended")
            finally:
                _tdb.close()
        except Exception:
            pass

        # Cleanup finished task references
        try:
            from app.services.perception import perception
            perception.forget(run_id)
        except Exception:
            pass
        self._tasks.pop(run_id, None)
        self._stop_flags.pop(run_id, None)
        self._wp_denial_counts.pop(run_id, None)
        self._executed_paths.pop(run_id, None)
        self._last_positions.pop(run_id, None)
        self._stagnant_counts.pop(run_id, None)
        self._plan_contexts.pop(run_id, None)
        self._environment_holds.discard(run_id)
