from __future__ import annotations

import asyncio
import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional

from app.deps import get_db
from app.auth.jwt import get_current_user
from app.auth.roles import ADMIN, OPERATOR
from app.db.models import Run, Event, Mission, TelemetrySample
from app.schemas.run import RunOut, RunStartResponse
from app.schemas.events import EventOut
from app.services.run_service import RunService
from app.services.llm_factory import get_planner
from app.services.local_fallback_planner import generate_fallback_waypoint
from app.config import settings
from app.world_model import GEOFENCE

logger = logging.getLogger("app.routes_runs")


def _review_mission_plan(goal: dict, waypoints: list, plan_source: str) -> dict:
    """Mission-level governance gate: Sovereign Autonomy reviews the plan before execution.

    Checks:
    - Goal within geofence
    - All waypoints within geofence
    - Plan exists (not empty)

    Returns a review dict with verdict: APPROVED | BLOCKED | MODIFIED.
    """
    reasons = []
    checks_passed = []

    # Check goal is within geofence
    gx, gy = float(goal.get("x", 0)), float(goal.get("y", 0))
    goal_in_fence = (
        GEOFENCE["min_x"] <= gx <= GEOFENCE["max_x"]
        and GEOFENCE["min_y"] <= gy <= GEOFENCE["max_y"]
    )
    if goal_in_fence:
        checks_passed.append("goal_within_geofence")
    else:
        reasons.append(f"Goal ({gx:.1f}, {gy:.1f}) is outside geofence bounds")

    # Check all waypoints within geofence
    wp_violations = []
    for i, wp in enumerate(waypoints):
        wx, wy = float(wp.get("x", 0)), float(wp.get("y", 0))
        if not (GEOFENCE["min_x"] <= wx <= GEOFENCE["max_x"]
                and GEOFENCE["min_y"] <= wy <= GEOFENCE["max_y"]):
            wp_violations.append(f"waypoint {i} ({wx:.1f}, {wy:.1f})")
    if wp_violations:
        reasons.append(f"Out-of-bounds waypoints: {', '.join(wp_violations)}")
    else:
        checks_passed.append("all_waypoints_within_geofence")

    # Check plan is not empty
    if waypoints:
        checks_passed.append("plan_has_waypoints")
    else:
        reasons.append("No waypoints in plan")

    checks_passed.append("plan_source_verified")

    verdict = "BLOCKED" if (not goal_in_fence or wp_violations) else "APPROVED"

    return {
        "verdict": verdict,
        "plan_source": plan_source,
        "waypoint_count": len(waypoints),
        "checks_passed": checks_passed,
        "reasons": reasons,
        "goal": {"x": gx, "y": gy},
    }

router = APIRouter()
run_svc: RunService | None = None


def get_run_svc() -> RunService:
    assert run_svc is not None, "RunService not initialized"
    return run_svc


# --- Backward-compatible endpoint ---
# Old frontend builds call POST /runs with {"mission_id": "..."}
class _LegacyRunStart(BaseModel):
    mission_id: str


@router.post("/runs", response_model=RunStartResponse)
async def start_run_legacy(
    body: _LegacyRunStart,
    db: Session = Depends(get_db),
    user: str | None = Depends(OPERATOR),
):
    """Backward-compatible: accepts POST /runs {mission_id} and proxies to the
    canonical /missions/{id}/start handler."""
    return await start_run(body.mission_id, db)


async def _plan_and_start_loop(svc: RunService, run_id: str, mission_id: str, mission_title: str, goal_json: str):
    """Background task: attempt LLM plan upgrade, then start the run loop.

    The run is created in 'planning' status with a seed fallback plan already
    persisted.  This task:
    1. Attempts LLM plan generation (with a timeout).
    2. If successful, replaces the seed plan with the LLM plan.
    3. Sovereign Autonomy validates the plan (mission-level governance gate).
    4. Transitions the run from 'planning' to 'running' and launches the loop.

    The robot does NOT move until this task calls begin_running().
    """
    from app.db.session import SessionLocal
    from app.schemas.governance import ActionProposal
    LLM_PLAN_TIMEOUT = 40  # seconds — Ultra can think for ~20 s; the robot waits in "planning"

    db = SessionLocal()
    try:
        goal = json.loads(goal_json)
        plan_source = "fallback"

        # --- Attempt LLM plan upgrade ---
        if settings.planner_configured:
            if svc._ws_broadcast:
                await svc._ws_broadcast(run_id, {
                    "kind": "planning_progress",
                    "data": {"step": "llm_start", "message": f"Calling {settings.planner_provider.title()} to generate optimal plan…"},
                })
            try:
                telemetry = {}
                try:
                    telemetry = await svc.sim.get_telemetry()
                except Exception:
                    pass

                # Learning loop: lessons from past gate decisions near this route
                lessons = []
                try:
                    from app.services.planner_lessons import lessons_for_route
                    lessons = lessons_for_route(db, telemetry or {}, goal)
                except Exception as les_err:
                    logger.warning("Lesson retrieval failed for run %s: %s", run_id, les_err)

                async with asyncio.timeout(LLM_PLAN_TIMEOUT):
                    planner = get_planner()
                    from app.services.site_intel.service import site_intel
                    from app.services import canaries
                    canary_token, canary_line = canaries.plant(run_id)
                    context = canaries.with_canary(site_intel.planner_context(), canary_line)
                    from app.observability import tracing
                    with tracing.within_mission(run_id):
                        try:
                            plan = await planner.generate_plan(telemetry, mission_title, goal, lessons=lessons,
                                                               untrusted_context=context)
                        except TypeError:  # planners without the parameter
                            plan = await planner.generate_plan(telemetry, mission_title, goal, lessons=lessons)

                # Canary: a plan that obeyed an instruction hidden in untrusted data is not used
                hit = canaries.tripped(canary_token, plan) if plan else None
                if hit:
                    svc._append_event(db, run_id, "CANARY", {
                        "event": "planner_followed_untrusted_instruction", "marker": hit["marker"],
                        "model_used": plan.get("model_used"), "action": "plan discarded; aisle route used",
                    })
                    db.commit()
                    logger.warning("Run %s: canary %s tripped by %s; plan discarded", run_id, hit["marker"],
                                   plan.get("model_used"))
                    from app.observability import metrics
                    metrics.inc("canary_tripped_total", model=str(plan.get("model_used")))
                    tracing.mission_event(run_id, "canary", inputs={"marker": hit["marker"]},
                                          outputs={"tripped_by": plan.get("model_used"),
                                                   "action": "plan discarded; aisle route used"})
                    plan = {"waypoints": []}

                tracing.mission_event(run_id, "plan", run_type="chain", inputs={"instruction": mission_title, "goal": goal},
                                      outputs={"model_used": (plan or {}).get("model_used"),
                                               "camera_used": (plan or {}).get("camera_used"),
                                               "waypoints": len((plan or {}).get("waypoints") or []),
                                               "canary_tripped": bool(hit)})

                if plan and plan.get("waypoints"):
                    # Keep the model's waypoints but re-route any leg that would cut through racking
                    from app.world_model import ZONE_SPEED_LIMITS as _ZL
                    site_world = None
                    try:
                        from app.services.site_router import repair_plan
                        site_world = await svc.sim.get_world()
                        fixed, n_fixed = repair_plan(site_world, telemetry, plan["waypoints"], _ZL)
                        if n_fixed:
                            plan["waypoints"], plan["repaired_legs"] = fixed, n_fixed
                    except Exception as rep_err:
                        logger.warning("Plan repair skipped for run %s: %s", run_id, rep_err)
                    plan_source = settings.planner_provider
                    # Task-drift guard: the plan must still end at the mission destination
                    # without wandering; otherwise the aisle route to the same goal is used.
                    task_check = None
                    if telemetry and site_world:
                        try:
                            from app.services.task_guard import guard
                            g = guard(plan, telemetry, goal, site_world, _ZL, hazards=telemetry.get("site_constraints"))
                            plan, task_check = g["plan"], g["check"]
                            if g["replaced"]:
                                plan_source = "fallback"
                            svc._append_event(db, run_id, "TASK_CHECK", {"stage": "mission_plan", **task_check})
                        except Exception as tg_err:
                            logger.warning("Task guard skipped for run %s: %s", run_id, tg_err)
                    async with svc._plans_lock:
                        svc._plans[run_id] = plan["waypoints"]
                    svc._append_event(db, run_id, "PLAN", {
                        "mission_id": mission_id,
                        "plan": plan,
                        "source": plan_source,
                        "note": "LLM multi-waypoint plan (upgraded from fallback)",
                        "task_check": task_check,
                        "lessons_offered": [{"id": l["id"], "text": l["text"]} for l in lessons],
                        "lessons_applied": [{"id": l["id"], "text": l["text"]} for l in lessons
                                            if l["id"] in plan.get("lessons_applied", [])],
                    })
                    db.commit()
                    logger.info("LLM plan ready for run %s (%d waypoints)", run_id, len(plan["waypoints"]))
                    if svc._ws_broadcast:
                        await svc._ws_broadcast(run_id, {
                            "kind": "planning_progress",
                            "data": {"step": "llm_done", "message": f"LLM plan ready — {len(plan['waypoints'])} waypoints generated", "waypoint_count": len(plan["waypoints"]), "source": plan_source, "model_used": plan.get("model_used")},
                        })
                else:
                    if svc._ws_broadcast:
                        await svc._ws_broadcast(run_id, {
                            "kind": "planning_progress",
                            "data": {"step": "llm_fallback", "message": "LLM returned no waypoints — using fallback plan", "source": "fallback"},
                        })
            except (asyncio.TimeoutError, Exception) as exc:
                logger.warning("LLM plan failed/timed out for run %s: %s — using seed fallback", run_id, exc)
                if svc._ws_broadcast:
                    await svc._ws_broadcast(run_id, {
                        "kind": "planning_progress",
                        "data": {"step": "llm_fallback", "message": f"LLM timed out — using fallback plan", "source": "fallback"},
                    })
        else:
            if svc._ws_broadcast:
                await svc._ws_broadcast(run_id, {
                    "kind": "planning_progress",
                    "data": {"step": "llm_skip", "message": "No LLM planner configured — using fallback plan", "source": "fallback"},
                })

        # --- Mission-level governance gate: Sovereign Autonomy reviews the plan ---
        if svc._ws_broadcast:
            await svc._ws_broadcast(run_id, {
                "kind": "planning_progress",
                "data": {"step": "governance_start", "message": "Sovereign Autonomy reviewing plan for safety compliance…"},
            })
        plan_wps = svc._plans.get(run_id, [])
        mission_review = _review_mission_plan(goal, plan_wps, plan_source)
        svc._append_event(db, run_id, "MISSION_REVIEW", mission_review)
        db.commit()

        if svc._ws_broadcast:
            await svc._ws_broadcast(run_id, {
                "kind": "event",
                "data": {"type": "MISSION_REVIEW", **mission_review},
            })

        if mission_review["verdict"] == "BLOCKED":
            # Mission fundamentally invalid — mark run as failed
            run = db.query(Run).filter(Run.id == run_id).first()
            if run:
                run.status = "failed"
                run.ended_at = __import__("app.utils.time", fromlist=["utc_now"]).utc_now()
                from app.db.models import Mission as _Mission
                m = db.query(_Mission).filter(_Mission.id == mission_id).first()
                if m:
                    m.status = "failed"
                db.commit()
            logger.warning("Run %s: mission BLOCKED by Sovereign Autonomy — %s", run_id, mission_review["reasons"])
            if svc._ws_broadcast:
                await svc._ws_broadcast(run_id, {"kind": "status", "data": {"status": "failed", "reason": "Mission blocked by governance"}})
            return

        # --- Transition planning → running and launch loop ---
        if svc._ws_broadcast:
            await svc._ws_broadcast(run_id, {
                "kind": "planning_progress",
                "data": {"step": "governance_done", "message": f"Plan approved — {len(plan_wps)} waypoints cleared for execution", "verdict": mission_review["verdict"]},
            })
        svc.begin_running(db, run_id)

        if svc._ws_broadcast:
            await svc._ws_broadcast(run_id, {"kind": "status", "data": {"status": "running", "plan_source": plan_source}})

    except Exception as exc:
        logger.error("Plan-and-start failed for run %s: %s", run_id, exc)
        try:
            db.rollback()
        except Exception:
            pass
        # Mark run as failed instead of launching a potentially broken loop
        try:
            run = db.query(Run).filter(Run.id == run_id).first()
            if run and run.status == "planning":
                run.status = "failed"
                run.ended_at = __import__("app.utils.time", fromlist=["utc_now"]).utc_now()
                db.commit()
                logger.warning("Run %s marked failed after planning error: %s", run_id, exc)
            if svc._ws_broadcast:
                await svc._ws_broadcast(run_id, {
                    "kind": "status",
                    "data": {"status": "failed", "reason": f"Planning failed: {exc}"},
                })
                await svc._ws_broadcast(run_id, {
                    "kind": "planning_progress",
                    "data": {"step": "error", "message": f"Planning failed — {exc}"},
                })
        except Exception as inner:
            logger.error("Failed to mark run %s as failed: %s", run_id, inner)
    finally:
        db.close()


@router.post("/missions/{mission_id}/start", response_model=RunStartResponse)
async def start_run(
    mission_id: str,
    db: Session = Depends(get_db),
    user: str | None = Depends(OPERATOR),
):
    mission = db.query(Mission).filter(Mission.id == mission_id).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    if getattr(mission, "status", "draft") == "deleted":
        raise HTTPException(status_code=400, detail="Cannot start a deleted mission")
    svc = get_run_svc()

    # Guard: prevent duplicate starts for the same mission
    active_run = (
        db.query(Run)
        .filter(Run.mission_id == mission_id)
        .filter(Run.status.in_(("planning", "running", "paused")))
        .first()
    )
    if active_run:
        raise HTTPException(
            status_code=409,
            detail=f"Mission already has an active run ({active_run.id}, status={active_run.status}). "
                   f"Stop or complete it before starting a new one.",
        )

    # Guard: limit concurrent active runs to prevent sim/event-loop saturation
    MAX_CONCURRENT_RUNS = 5
    active_count = db.query(Run).filter(Run.status.in_(("planning", "running"))).count()
    if active_count >= MAX_CONCURRENT_RUNS:
        raise HTTPException(
            status_code=409,
            detail=f"Too many active runs ({active_count}). "
                   f"Stop an existing run before starting a new one (max {MAX_CONCURRENT_RUNS}).",
        )

    # Reset simulator robot to starting position for a clean run
    try:
        await svc.sim.reset_robot()
        logger.info("Sim robot reset to start position for mission %s", mission_id)
    except Exception as reset_err:
        logger.warning("Failed to reset sim robot: %s — continuing with current position", reset_err)

    # Create run in 'planning' status — loop not launched yet
    run = svc.start_run(db, mission_id)

    # Persist a seed fallback plan synchronously so the PLAN event is
    # immediately visible in the chain-of-trust, even before LLM planning.
    try:
        telemetry = await svc.sim.get_telemetry()
    except Exception:
        telemetry = {}

    # Seed plan: a route along the aisles when the site map is known, else one short step
    seed_wps = None
    try:
        from app.services.site_router import route_plan
        from app.world_model import ZONE_SPEED_LIMITS as _ZL
        if telemetry:
            seed_wps = route_plan(await svc.sim.get_world(), telemetry, json.loads(mission.goal_json), _ZL)
    except Exception as route_err:
        logger.warning("Aisle routing unavailable for run %s: %s", run.id, route_err)
    if not seed_wps:
        seed_wps = [generate_fallback_waypoint(telemetry, json.loads(mission.goal_json))]
    svc._plans[run.id] = seed_wps
    svc._append_event(db, run.id, "PLAN", {
        "mission_id": mission.id,
        "plan": {"waypoints": seed_wps, "model_used": "site_router" if len(seed_wps) > 1 else "step_fallback"},
        "source": "fallback",
        "note": "Seed plan along the aisles — model plan pending" if len(seed_wps) > 1 else "Seed fallback plan — LLM plan pending",
    })
    db.commit()

    # Fire background task: attempt LLM plan upgrade → transition to 'running' → launch loop.
    # The robot will NOT move until the background task calls begin_running().
    asyncio.create_task(
        _plan_and_start_loop(svc, run.id, mission.id, mission.title, mission.goal_json)
    )

    # Mark mission as executing
    mission.status = "executing"
    db.commit()
    return RunStartResponse(run_id=run.id)


@router.get("/runs", response_model=List[RunOut])
def list_runs(
    mission_id: Optional[str] = Query(None, description="Filter by mission ID"),
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(Run)
    if mission_id:
        q = q.filter(Run.mission_id == mission_id)
    if status:
        q = q.filter(Run.status == status)
    rows = q.order_by(Run.started_at.desc()).offset(offset).limit(limit).all()
    return [
        RunOut(id=r.id, mission_id=r.mission_id, status=r.status, started_at=r.started_at, ended_at=r.ended_at)
        for r in rows
    ]


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    # Reading a run never restarts it. A robot only moves after an explicit
    # start or resume; startup pauses runs left over from a restart.
    return RunOut(
        id=run.id,
        mission_id=run.mission_id,
        status=run.status,
        started_at=run.started_at,
        ended_at=run.ended_at,
    )


@router.post("/runs/{run_id}/stop")
async def stop_run(
    run_id: str,
    db: Session = Depends(get_db),
    user: str | None = Depends(get_current_user),
):
    svc = get_run_svc()
    await svc.stop_run(db, run_id)
    return {"ok": True}


@router.post("/runs/{run_id}/pause")
async def pause_run(
    run_id: str,
    db: Session = Depends(get_db),
    user: str | None = Depends(OPERATOR),
):
    """Pause a running run — robot stops executing but run can be resumed."""
    svc = get_run_svc()
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != "running":
        raise HTTPException(status_code=400, detail=f"Cannot pause run in state '{run.status}'")
    await svc.pause_run(db, run_id)
    return {"ok": True, "status": "paused"}


@router.post("/runs/{run_id}/resume")
async def resume_run(
    run_id: str,
    db: Session = Depends(get_db),
    user: str | None = Depends(OPERATOR),
):
    """Resume a paused run."""
    svc = get_run_svc()
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != "paused":
        raise HTTPException(status_code=400, detail=f"Cannot resume run in state '{run.status}'")
    from app.autonomy.core import Rejected
    try:
        result = await svc.resume_run(db, run_id) or {}
    except Rejected as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"ok": True, "status": "running", **result}


@router.get("/runs/{run_id}/events", response_model=List[EventOut])
def list_events(
    run_id: str,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Event)
        .filter(Event.run_id == run_id)
        .order_by(Event.ts.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        EventOut(
            id=r.id,
            run_id=r.run_id,
            ts=r.ts,
            type=r.type,
            payload=json.loads(r.payload_json),
            hash=r.hash,
            prev_hash=r.prev_hash or "0" * 64,
        )
        for r in rows
    ]


@router.get("/runs/{run_id}/telemetry")
def list_telemetry(
    run_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(TelemetrySample)
        .filter(TelemetrySample.run_id == run_id)
        .order_by(TelemetrySample.ts.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        {"id": r.id, "run_id": r.run_id, "ts": r.ts.isoformat(), "payload": json.loads(r.payload_json)}
        for r in rows
    ]


@router.get("/runs/{run_id}/replay")
def replay_run(
    run_id: str,
    include_telemetry: bool = Query(False, description="Include raw telemetry samples"),
    db: Session = Depends(get_db),
):
    """Return the full timeline of a run for audit replay, including chain integrity verification."""
    from app.services.replay_service import get_run_timeline

    timeline = get_run_timeline(db, run_id, include_telemetry=include_telemetry)
    if not timeline:
        raise HTTPException(status_code=404, detail="Run not found")
    return timeline


@router.get("/runs/{run_id}/audit-bundle")
def audit_bundle(
    run_id: str,
    db: Session = Depends(get_db),
):
    """Export a self-contained audit bundle for regulatory submission."""
    from app.services.replay_service import export_audit_bundle

    bundle = export_audit_bundle(db, run_id)
    if not bundle:
        raise HTTPException(status_code=404, detail="Run not found")
    return bundle


@router.get("/runs/{run_id}/scores")
def get_run_scores(
    run_id: str,
    db: Session = Depends(get_db),
):
    """Compute and return multi-objective scorecard for a run."""
    from app.services.scoring_engine import compute_scorecard

    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return compute_scorecard(db, run_id)


@router.get("/runs/{run_id}/risk-heatmap")
def get_risk_heatmap(
    run_id: str,
    grid_size: float = Query(2.0, ge=0.5, le=10.0, description="Grid cell size in meters"),
    db: Session = Depends(get_db),
):
    """Compute spatial risk heatmap from governance decisions (#21).

    Returns a grid of risk scores based on where denials and
    high-risk decisions occurred during the run.
    """
    import json as _json
    from app.db.models import GovernanceDecisionRecord
    from app.world_model import GEOFENCE

    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    decisions = (
        db.query(GovernanceDecisionRecord)
        .filter(GovernanceDecisionRecord.run_id == run_id)
        .all()
    )

    min_x = GEOFENCE["min_x"]
    max_x = GEOFENCE["max_x"]
    min_y = GEOFENCE["min_y"]
    max_y = GEOFENCE["max_y"]

    # Build grid
    cols = int((max_x - min_x) / grid_size) + 1
    rows = int((max_y - min_y) / grid_size) + 1
    grid = [[0.0] * cols for _ in range(rows)]
    counts = [[0] * cols for _ in range(rows)]

    for d in decisions:
        try:
            tel = _json.loads(d.telemetry_summary or "{}")
            x = float(tel.get("x", 0))
            y = float(tel.get("y", 0))
            col = int((x - min_x) / grid_size)
            row = int((y - min_y) / grid_size)
            if 0 <= row < rows and 0 <= col < cols:
                # Weight: denials=1.0, needs_review=0.7, approved=0.1
                weight = 1.0 if d.decision == "DENIED" else (0.7 if d.decision == "NEEDS_REVIEW" else 0.1)
                grid[row][col] += d.risk_score * weight
                counts[row][col] += 1
        except Exception:
            continue

    # Normalize to 0-1
    max_val = max(max(row) for row in grid) if grid else 1.0
    if max_val > 0:
        grid = [[cell / max_val for cell in row] for row in grid]

    # Build cell list for frontend
    cells = []
    for r in range(rows):
        for c in range(cols):
            if grid[r][c] > 0.05:  # skip near-zero cells
                cells.append({
                    "x": round(min_x + c * grid_size, 1),
                    "y": round(min_y + r * grid_size, 1),
                    "risk": round(grid[r][c], 3),
                    "decisions": counts[r][c],
                })

    return {
        "run_id": run_id,
        "grid_size": grid_size,
        "bounds": {"min_x": min_x, "max_x": max_x, "min_y": min_y, "max_y": max_y},
        "cells": cells,
        "total_decisions": len(decisions),
    }


@router.get("/runs/{run_id}/introspection")
def get_run_introspection(
    run_id: str,
    db: Session = Depends(get_db),
):
    """Agent introspection: thought chains, denial history, memory recalls (#20)."""
    import json as _json

    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # Gather DECISION events for thought chain
    decision_events = (
        db.query(Event)
        .filter(Event.run_id == run_id, Event.type == "DECISION")
        .order_by(Event.ts.asc())
        .all()
    )

    # Gather REPLAN events
    replan_events = (
        db.query(Event)
        .filter(Event.run_id == run_id, Event.type == "REPLAN")
        .order_by(Event.ts.asc())
        .all()
    )

    # Gather PLAN events
    plan_events = (
        db.query(Event)
        .filter(Event.run_id == run_id, Event.type == "PLAN")
        .order_by(Event.ts.asc())
        .all()
    )

    # Build denial history
    from app.db.models import GovernanceDecisionRecord
    denials = (
        db.query(GovernanceDecisionRecord)
        .filter(
            GovernanceDecisionRecord.run_id == run_id,
            GovernanceDecisionRecord.decision.in_(["DENIED", "NEEDS_REVIEW"]),
        )
        .order_by(GovernanceDecisionRecord.ts.asc())
        .all()
    )

    denial_history = []
    for d in denials:
        denial_history.append({
            "ts": d.ts.isoformat() if d.ts else None,
            "decision": d.decision,
            "policy_hits": _json.loads(d.policy_hits or "[]"),
            "reasons": _json.loads(d.reasons or "[]"),
            "risk_score": d.risk_score,
            "policy_state": d.policy_state,
        })

    # Memory context
    try:
        from app.services.persistent_memory import PersistentMemory
        mem = PersistentMemory()
        memory_context = mem.recall_for_context(db)
        memory_stats = mem.get_stats(db)
    except Exception:
        memory_context = "Memory unavailable"
        memory_stats = {}

    return {
        "run_id": run_id,
        "total_decisions": len(decision_events),
        "total_replans": len(replan_events),
        "total_plans": len(plan_events),
        "denial_count": len(denials),
        "denial_history": denial_history[:50],
        "replans": [
            {
                "ts": e.ts.isoformat() if e.ts else None,
                "payload": _json.loads(e.payload_json),
            }
            for e in replan_events
        ],
        "plans": [
            {
                "ts": e.ts.isoformat() if e.ts else None,
                "payload": _json.loads(e.payload_json),
            }
            for e in plan_events
        ],
        "memory_context": memory_context,
        "memory_stats": memory_stats,
    }
