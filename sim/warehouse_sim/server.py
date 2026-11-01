"""Sovereign Autonomy live warehouse simulator.

Runs the benchmark's deterministic engine (backend/bench/world.py) in real time
behind the same HTTP API as the original mock simulator, so the backend and
dashboard work unchanged. What is new:

- Solid racks, edge-to-edge clearances, a robot that turns on the spot.
- Site activity: workers patrolling, people crossing at hotspots, a forklift
  on the main corridor whose driver stops for the robot.
- Hazards on demand: spills, dropped pallets, a worker stepping out, a forklift
  crossing (POST /scenario).
- Replay of any benchmark scenario by seed (POST /seed), so a demo can show
  the exact case a benchmark result came from.
- A robot camera frame (GET /frame) for the vision model.

Physics advances on a background clock at SIM_TICK_HZ; every request reads the
current state. Randomness comes from SIM_SEED, so a session replays exactly.
"""
from __future__ import annotations

import asyncio
import math
import os
import random
import threading
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from bench.scenarios import HOTSPOTS, generate
from bench.world import Circle, Layout, RobotState, Walker, World
from traffic import ActorNavigation, FORKLIFT_RADIUS, TrafficWorld

SIM_TICK_HZ = float(os.getenv("SIM_TICK_HZ", "10"))
SIM_SPEED = float(os.getenv("SIM_SPEED", "1.0"))        # 2.0 = twice real time
SIM_SEED = int(os.getenv("SIM_SEED", "42"))
SIM_TOKEN = os.getenv("SIM_TOKEN", "").strip()
PARKING = (3.0, 3.5)

layout = Layout()
_lock = threading.RLock()
_state: Dict[str, Any] = {"world": None, "mode": "live", "seed": SIM_SEED, "events": []}


def _require_token(request: Request) -> None:
    if SIM_TOKEN and (request.headers.get("X-Sim-Token") or "").strip() != SIM_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized simulator call")


# ---------------------------------------------------------------------------
# World construction
# ---------------------------------------------------------------------------

def _crossing_loop(rng: random.Random, hotspot, name: str, nav: ActorNavigation):
    """Someone who keeps crossing at a hotspot: across, pause, back."""
    vertical = hotspot[1] in (13.5,) or rng.random() < 0.5
    reach = rng.uniform(2.5, 3.5)
    if vertical:
        a, b = (hotspot[0], hotspot[1] - reach), (hotspot[0], hotspot[1] + reach)
    else:
        a, b = (hotspot[0] - reach, hotspot[1]), (hotspot[0] + reach, hotspot[1])
    clamp = lambda p: (min(39.5, max(0.5, p[0])), min(24.5, max(0.5, p[1])))  # noqa: E731
    start, end = nav.safe_point(clamp(a)), nav.safe_point(clamp(b))
    route = nav.route(start, end) if start and end else None
    if not route or len(route) < 2:
        return None
    worker = Walker(name, route, rng.uniform(0.8, 1.2), start_t=rng.uniform(0, 20),
                    loop=True, pause_s=rng.uniform(4.0, 12.0))
    worker.navigation_ready = True
    worker.pause_activity = "waiting_at_crossing"
    return worker


def build_live_world(seed: int) -> World:
    rng = random.Random(seed)
    world = TrafficWorld(layout=layout, robot=RobotState(*PARKING), seed=seed)
    nav = world.pedestrian_nav
    pick_bays = [b for b in layout.bays.values() if b.get("type") == "pick" and math.hypot(b["x"] - PARKING[0], b["y"] - PARKING[1]) > 3]
    stations = [f for f in layout.data.get("features", []) if f["type"] == "packing_station"]
    for k, bay in enumerate(rng.sample(pick_bays, min(3, len(pick_bays)))):
        station = stations[k % len(stations)] if stations else bay
        start = nav.safe_point((bay["x"], bay["y"]))
        goal = nav.safe_point((station["x"], station["y"] - 0.5))
        route = nav.route(start, goal) if start and goal else None
        if route and len(route) > 1:
            worker = Walker(f"Worker {chr(65 + k)}", route, rng.uniform(0.6, 1.0), start_t=rng.uniform(0, 10),
                            loop=True, pause_s=rng.uniform(5, 9))
            worker.navigation_ready = True
            worker.task_stops = [(start, bay["id"]), (goal, station.get("label", "Packing"))]
            shelf = min(layout.racks, key=lambda rack: rack.distance(*start), default=None)
            worker.work_faces = [(goal, (station["x"], station["y"] + 0.55))]
            if shelf:
                worker.work_faces.append((start, shelf.nearest_point(*start)))
            world.walkers.append(worker)
    for k, hs in enumerate(rng.sample(HOTSPOTS, 3)):
        worker = _crossing_loop(rng, hs, f"Runner {k + 1}", nav)
        if worker:
            world.walkers.append(worker)
    start, end = world.vehicle_nav.safe_point((2.0, 13.5)), world.vehicle_nav.safe_point((38.0, 13.5))
    route = world.vehicle_nav.route(start, end) if start and end else None
    if route and len(route) > 1:
        vehicle = Walker("Forklift", route, 1.4, start_t=5.0, loop=True, pause_s=6.0, radius=FORKLIFT_RADIUS, kind="forklift")
        vehicle.navigation_ready = True
        world.walkers.append(vehicle)
    return world


def _world() -> World:
    if _state["world"] is None:
        _state["world"] = build_live_world(_state["seed"])
    return _state["world"]


async def _clock() -> None:
    dt = 1.0 / SIM_TICK_HZ
    while True:
        t0 = time.perf_counter()
        with _lock:
            _world().step(dt * SIM_SPEED)
        await asyncio.sleep(max(0.0, dt - (time.perf_counter() - t0)))


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(_clock())
    yield
    task.cancel()


app = FastAPI(title="Sovereign Autonomy Warehouse Simulator", version="0.2.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

def _obstacles(w: World) -> List[Dict[str, Any]]:
    out = [{"x": c.x, "y": c.y, "r": c.r, "type": c.kind} for c in w.layout.static]
    out += [{"x": round(c.x, 2), "y": round(c.y, 2), "r": c.r, "type": c.kind, **(c.meta or {})} for c in w.active_spawns]
    out += [{"x": round(v.pos[0], 2), "y": round(v.pos[1], 2), "r": v.radius, "type": "forklift",
             "heading": round(_heading(v), 3)} for v in w.vehicles()]
    return out


def _heading(v: Walker) -> float:
    if getattr(v, "activity", "") == "working":
        for stand, face in getattr(v, "work_faces", []):
            if math.dist(v.pos, stand) < 0.6:
                return math.atan2(face[1] - v.pos[1], face[0] - v.pos[0])
    if hasattr(v, "heading"):
        return v.heading
    if v.idx + 1 < len(v.route):
        tx, ty = v.route[v.idx + 1]
        return math.atan2(ty - v.pos[1], tx - v.pos[0])
    return 0.0


def _people(w: World) -> List[Dict[str, Any]]:
    return [{"x": round(p.pos[0], 2), "y": round(p.pos[1], 2), "name": p.name, "type": "worker",
             "role": "worker", "conf": 0.9, "speed": round(getattr(p, "actual_speed", 0.0), 3),
             "heading": round(_heading(p), 3), "activity": getattr(p, "activity", "walking"),
             "destination": min(getattr(p, "task_stops", [(p.route[-1], "Crossing destination")]),
                                key=lambda stop: math.dist(stop[0], p.route[-1]))[1]} for p in w.people()]


def _telemetry(w: World) -> Dict[str, Any]:
    tel = w.telemetry()
    events = list(_state["events"])
    if tel["nearest_obstacle_m"] < 0:   # bodies overlap: report contact, not an impossible distance
        tel["nearest_obstacle_m"] = 0.0
        events.append("contact")
    people = _people(w)
    nearest = min(people, key=lambda p: math.hypot(p["x"] - w.robot.x, p["y"] - w.robot.y), default=None)
    tel.update({
        "events": events,
        "human": dict(nearest, type="human", id="nearest", role="primary") if nearest else None,
        "walking_humans": people,
        "idle_robots": [],
        "obstacles": _obstacles(w),
        "bounds": w.layout.geofence,
        "target": w.robot.target,
        "sim_time": round(w.t, 2),
        "mode": _state["mode"],
        "seed": _state["seed"],
        "timestamp": time.time(),
    })
    return tel


# ---------------------------------------------------------------------------
# API (compatible with sim/mock_sim)
# ---------------------------------------------------------------------------

class Command(BaseModel):
    intent: str = Field(..., description="MOVE_TO|STOP|WAIT")
    params: Dict[str, Any] = Field(default_factory=dict)


class ScenarioRequest(BaseModel):
    scenario: str
    params: Dict[str, Any] = Field(default_factory=dict)


class SeedRequest(BaseModel):
    seed: int
    mode: str = Field("benchmark", description="benchmark: replay a benchmark scenario exactly; live: site activity")


@app.get("/health")
def health():
    return {"status": "ok", "engine": "bench.world", "mode": _state["mode"], "seed": _state["seed"]}


@app.get("/telemetry")
def telemetry(request: Request):
    _require_token(request)
    with _lock:
        return _telemetry(_world())


@app.get("/world")
def world(request: Request):
    _require_token(request)
    with _lock:
        w = _world()
        d = w.layout.data
        people = _people(w)
        return {
            "geofence": d["geofence"], "zones": d["zones"], "racks": d.get("racks", []),
            "features": d.get("features", []), "bays": d["bays"], "obstacles": _obstacles(w),
            "human": people[0] if people else None, "walking_humans": people, "idle_robots": [],
            "hotspots": [{"x": x, "y": y} for x, y in HOTSPOTS], "mode": _state["mode"], "seed": _state["seed"],
        }


@app.post("/reset")
def reset_robot(request: Request):
    _require_token(request)
    with _lock:
        w = _world()
        start = PARKING if _state["mode"] == "live" else _state.get("start", PARKING)
        w.robot = RobotState(*start)
        _state["events"] = []
        return {"ok": True, "position": {"x": start[0], "y": start[1]}, "msg": "Robot reset to start"}


@app.post("/command")
def command(request: Request, cmd: Command):
    _require_token(request)
    with _lock:
        w = _world()
        g = w.layout.geofence
        if cmd.intent == "MOVE_TO":
            x = float(cmd.params.get("x", w.robot.x))
            y = float(cmd.params.get("y", w.robot.y))
            if not (g["min_x"] <= x <= g["max_x"] and g["min_y"] <= y <= g["max_y"]):
                return {"ok": False, "error": f"Target ({x},{y}) outside geofence"}
            w.command("MOVE_TO", {"x": x, "y": y, "max_speed": float(cmd.params.get("max_speed", 0.5))})
            return {"ok": True, "set_target": w.robot.target}
        if cmd.intent == "STOP":
            w.command("STOP")
            return {"ok": True, "stopped": True}
        if cmd.intent == "WAIT":
            w.command("STOP")
            return {"ok": True, "wait": cmd.params.get("seconds", 1)}
        return {"ok": False, "error": f"Unknown intent: {cmd.intent}"}


SCENARIOS = {
    "human_approach": "A worker walks toward the robot and stops about 2.5 m ahead",
    "human_too_close": "A worker steps out 0.8 m in front of the robot",
    "path_blocked": "A pallet is dropped 2 m ahead of the robot",
    "spill": "A spill appears 3 m ahead of the robot",
    "forklift_crossing": "The forklift drives across the robot's path on the corridor",
    "clear": "Remove injected hazards",
}


SPILL_SUBSTANCES = ["isopropyl alcohol", "hydraulic oil", "sodium hypochlorite solution", "detergent"]


def _ahead(w: World, d: float):
    return (w.robot.x + math.cos(w.robot.theta) * d, w.robot.y + math.sin(w.robot.theta) * d)


@app.get("/scenarios")
def list_scenarios(request: Request):
    _require_token(request)
    return {"scenarios": [{"id": k, "description": v} for k, v in SCENARIOS.items()]}


@app.post("/scenario")
def inject_scenario(request: Request, body: ScenarioRequest):
    _require_token(request)
    with _lock:
        w = _world()
        s = body.scenario
        if s in ("human_approach", "human_too_close"):
            w.walkers = [v for v in w.walkers if v.name != "Injected worker"]
            d = 2.5 if s == "human_approach" else 0.8
            tx, ty = _ahead(w, d)
            sx, sy = _ahead(w, d + 4.0)
            w.walkers.append(Walker("Injected worker", [(sx, sy), (tx, ty)], 1.2 if d > 1 else 3.0,
                                    start_t=w.t, pause_s=8.0))
            if d < 1:  # step out right there
                w.walkers[-1].pos = (tx, ty)
                w.walkers[-1].idx = 1
                w.walkers[-1].pause_until = w.t + 8.0
        elif s in ("path_blocked", "spill"):
            x, y = _ahead(w, 2.0 if s == "path_blocked" else 3.0)
            _state["spills"] = _state.get("spills", 0) + 1
            n = _state["spills"]
            meta = None
            if s == "spill":
                # What was spilled comes from the warehouse system (the tote that was dropped)
                substance = str(body.params.get("substance") or SPILL_SUBSTANCES[(n - 1) % len(SPILL_SUBSTANCES)])
                meta = {"id": f"spill-{n}", "substance": substance,
                        "source": f"WMS: tote T-{4400 + n} dropped, contents '{substance}'"}
            w.active_spawns.append(Circle(x, y, 0.5 if s == "path_blocked" else 0.45,
                                          "dropped_pallet" if s == "path_blocked" else "spill", meta))
        elif s == "forklift_crossing":
            fl = next((v for v in w.walkers if v.kind == "forklift"), None)
            if fl:
                if isinstance(w, TrafficWorld):
                    start, end = w.vehicle_nav.safe_point((2.0, 13.5)), w.vehicle_nav.safe_point((38.0, 13.5))
                    route = w.vehicle_nav.route(start, end) if start and end else None
                    if route:
                        fl.pos, fl.idx, fl.pause_until, fl.route = start, 0, 0.0, route
                else:
                    fl.pos, fl.idx, fl.pause_until = (2.0, 13.5), 0, 0.0
                    fl.route = [(2.0, 13.5), (38.0, 13.5)]
        elif s == "clear":
            w.active_spawns.clear()
            w.walkers = [v for v in w.walkers if v.name != "Injected worker"]
        else:
            return {"ok": False, "error": f"Unknown scenario '{s}'", "available": list(SCENARIOS)}
        _state["events"] = [f"scenario:{s}"]
        return {"ok": True, "scenario": s, "description": SCENARIOS[s]}


@app.post("/seed")
def load_seed(request: Request, body: SeedRequest):
    """Load a benchmark scenario exactly (mode=benchmark) or a different live site (mode=live)."""
    _require_token(request)
    with _lock:
        if body.mode == "benchmark":
            sc = generate(body.seed, layout)
            _state["world"] = sc.build_world(layout)
            _state["start"] = sc.start
            info = sc.summary()
            info["goal"] = {"x": sc.goal[0], "y": sc.goal[1], "bay": sc.goal_bay}
        else:
            _state["world"] = build_live_world(body.seed)
            info = {"seed": body.seed}
        _state.update(mode=body.mode, seed=body.seed, events=[])
        return {"ok": True, "mode": body.mode, **info}


@app.get("/frame")
def frame(request: Request, size: int = 512, view_m: float = 12.0):
    """Robot camera: a heading-up top-down view around the robot, as PNG."""
    _require_token(request)
    from camera import render
    with _lock:
        png = render(_world(), size=max(128, min(size, 1024)), view_m=max(4.0, min(view_m, 30.0)))
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-store"})


class PathSmoothRequest(BaseModel):
    waypoints: List[Dict[str, float]]
    resolution: int = Field(default=20, ge=5, le=100)


@app.post("/path/smooth")
def smooth_path(request: Request, body: PathSmoothRequest):
    """Route between consecutive waypoints along the aisles (replaces Bezier smoothing)."""
    _require_token(request)
    pts: List[Dict[str, float]] = []
    for a, b in zip(body.waypoints, body.waypoints[1:]):
        r = layout.route((a["x"], a["y"]), (b["x"], b["y"])) or [(a["x"], a["y"]), (b["x"], b["y"])]
        pts += [{"x": round(x, 2), "y": round(y, 2)} for x, y in (r if not pts else r[1:])]
    return {"points": pts or body.waypoints, "input_count": len(body.waypoints), "output_count": len(pts)}
