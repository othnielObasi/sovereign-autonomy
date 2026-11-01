from __future__ import annotations

import json
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.deps import get_db
from app.db.models import Run, Mission
from app.schemas.sim import SimWorld, PathPreview, Point
from app.services.sim_adapter import SimAdapter
from app.services.path_planner import plan_path

router = APIRouter()
sim = SimAdapter()


class ScenarioIn(BaseModel):
    scenario: str = Field(
        ..., description="human_approach|human_too_close|path_blocked|spill|forklift_crossing|clear"
    )


@router.get("/sim/telemetry")
async def get_telemetry():
    """Proxy the simulator's current telemetry (robot position, sensors)."""
    try:
        telemetry = await sim.get_telemetry()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"sim error: {e}")
    # Include active hazard zones so every view shows what the gate enforces
    from app.services.site_intel.service import site_intel
    from app.services.perception import perception
    return perception.apply(site_intel.observe(telemetry))


class PlanCheckIn(BaseModel):
    start: Dict[str, float]
    goal: Dict[str, float]
    waypoints: list = Field(default_factory=list)


@router.post("/plans/check")
async def check_plan_for_drift(body: PlanCheckIn):
    """Run the task-drift guard on any plan, with no side effects (nothing moves, nothing is recorded).
    Shows what the guard would decide, and the aisle route it would use instead."""
    from app.services.task_guard import guard
    from app.world_model import ZONE_SPEED_LIMITS
    try:
        world = await sim.get_world()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"sim error: {e}")
    wps = [{"x": float(w["x"]), "y": float(w["y"]), "max_speed": float(w.get("max_speed", 0.5))}
           for w in body.waypoints if isinstance(w, dict) and "x" in w and "y" in w][:100]
    g = guard({"waypoints": wps, "model_used": "submitted plan"}, body.start, body.goal, world, ZONE_SPEED_LIMITS)
    return {"check": g["check"], "replaced": g["replaced"], "submitted": wps,
            "used": g["plan"]["waypoints"], "used_by": g["plan"].get("model_used")}


@router.get("/perception/status")
def perception_status():
    """Vision model, settings, active caution zones and the latest checks."""
    from app.services.perception import perception
    return perception.status()


@router.post("/perception/check")
async def perception_check():
    """Read the robot camera now with the vision model and compare it with the sensors."""
    from app.config import settings
    from app.services.perception import perception
    if not settings.vision_configured:
        raise HTTPException(status_code=503, detail="Vision needs NEBIUS_API_KEY (and VISION_ENABLED=true)")
    try:
        return await perception.check(sim)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"vision check failed (needs the warehouse simulator): {e}")


@router.get("/sim/world", response_model=SimWorld)
async def get_world():
    """Proxy the simulator's world definition (geofence, obstacles, human)."""
    try:
        return await sim.get_world()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"sim error: {e}")


@router.get("/sim/frame")
async def get_frame(size: int = 512):
    """The robot's camera view (PNG): heading-up, top-down, around the robot."""
    from fastapi import Response
    try:
        png = await sim.get_frame(size=max(128, min(size, 1024)))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"sim error (needs the warehouse simulator): {e}")
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-store"})


class SeedIn(BaseModel):
    seed: int
    mode: str = Field("benchmark", pattern="^(benchmark|live)$")


@router.post("/sim/seed")
async def load_seed(body: SeedIn):
    """Replay a benchmark scenario exactly (mode=benchmark) or load another live site (mode=live)."""
    try:
        return await sim.load_seed(body.seed, body.mode)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"sim error (needs the warehouse simulator): {e}")


@router.get("/bays")
async def list_bays():
    """Return the list of bays (docks/shelves/receiving) from the simulator world."""
    try:
        world = await sim.get_world()
        return {"bays": world.get("bays", [])}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"sim error: {e}")


@router.post("/sim/scenario")
async def trigger_scenario(body: ScenarioIn):
    """Inject a deterministic scenario into the simulator for demo purposes.

    Valid scenarios: human_approach, human_too_close, path_blocked, clear.
    """
    try:
        result = await sim.post_scenario(body.scenario)
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"sim error: {e}")


@router.get("/runs/{run_id}/path_preview", response_model=PathPreview)
async def path_preview(run_id: str, db: Session = Depends(get_db)):
    """Return a path polyline from latest pose to mission goal."""
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    mission = db.query(Mission).filter(Mission.id == run.mission_id).first()
    if not mission:
        raise HTTPException(status_code=404, detail="mission not found")

    goal = json.loads(mission.goal_json)
    telemetry = await sim.get_telemetry()

    world = await sim.get_world()
    start = {"x": float(telemetry.get("x", 0)), "y": float(telemetry.get("y", 0))}
    if world.get("racks"):
        # Route along the aisles, the way the robot will actually drive
        from app.services.site_router import route_plan
        wps = route_plan(world, start, {"x": float(goal.get("x", 0)), "y": float(goal.get("y", 0))}, {})
        if wps:
            pts = [start] + [{"x": w["x"], "y": w["y"]} for w in wps]
            return PathPreview(points=[Point(**p) for p in pts], note="Route along the aisles")
    points, note = plan_path(
        start={"x": float(telemetry.get("x", 0)), "y": float(telemetry.get("y", 0))},
        goal={"x": float(goal.get("x", 0)), "y": float(goal.get("y", 0))},
        obstacles=world.get("obstacles", []),
        clearance_m=0.75,
    )
    return PathPreview(points=[Point(**p) for p in points], note=note)
