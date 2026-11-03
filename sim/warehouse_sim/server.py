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
import json
import math
import os
import random
import threading
import time
import sqlite3
import uuid
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.autonomy import permit as permits
from app.autonomy.robot_profiles import configured_profile, move_violation
from app.autonomy.controller import ControllerJournal
from bench.scenarios import HOTSPOTS, generate
from bench.world import ROBOT_R, Circle, Layout, RobotState, Walker, World, drive_robot, load_layout
from traffic import ActorNavigation, FORKLIFT_RADIUS, TrafficWorld

SIM_TICK_HZ = float(os.getenv("SIM_TICK_HZ", "10"))
SIM_SPEED = float(os.getenv("SIM_SPEED", "1.0"))        # 2.0 = twice real time
SIM_SEED = int(os.getenv("SIM_SEED", "42"))
SIM_TOKEN = os.getenv("SIM_TOKEN", "").strip()
# Every MOVE_TO must carry a permit signed with this secret (shared with the backend).
# Unset = no move is accepted (fails closed). STOP and WAIT never need a permit.
PERMIT_SECRET = os.getenv("PERMIT_SECRET", "").strip().encode()
AUTHORITY_BASE_URL = os.getenv("AUTHORITY_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
SIM_REDEEM_TIMEOUT_S = float(os.getenv("SIM_REDEEM_TIMEOUT_S", "1.0"))
SIM_STATE_DB = os.getenv("SIM_STATE_DB", "data/controller.db")
if not math.isfinite(SIM_REDEEM_TIMEOUT_S) or not 0 < SIM_REDEEM_TIMEOUT_S <= 2:
    raise ValueError("SIM_REDEEM_TIMEOUT_S must be in (0, 2]")
SIM_ROBOT_ID = os.getenv("SIM_ROBOT_ID", "robot-1")
# Dead-man stop: if no permitted move arrives for this long, the robot brakes on its
# own, so a crashed or cut-off backend cannot leave it driving. 0 disables it.
SIM_DEADMAN_S = float(os.getenv("SIM_DEADMAN_S", "5"))
# Which site the live simulator runs: "factory" (default) or "warehouse" (the benchmark site)
SITE_LAYOUT = os.getenv("SITE_LAYOUT", "pharma").strip() or "pharma"
SITE = load_layout(site=SITE_LAYOUT)
PARKING = tuple((SITE.get("parking") or {}).get(os.getenv("SIM_ROBOT_ID", "robot-1"), (3.0, 3.5)))
# Other robots: "id@x,y;id@x,y" (parking spots). Default: the site's own parking list.
SIM_FLEET = os.getenv("SIM_FLEET", ";".join(f"{rid}@{xy[0]},{xy[1]}" for rid, xy in (SITE.get("parking") or {}).items())
                      or "robot-2@3.0,21.5")
SITE_HOTSPOTS = [tuple(h) for h in SITE.get("hotspots") or []]
VEHICLE_LANE = [tuple(p) for p in SITE.get("vehicle_lane") or [(2.0, 13.5), (38.0, 13.5)]]


def _parse_fleet(spec: str) -> Dict[str, tuple]:
    out = {}
    for part in (spec or "").split(";"):
        if "@" in part:
            rid, xy = part.split("@", 1)
            x, y = xy.split(",")
            if rid.strip() and rid.strip() != SIM_ROBOT_ID:
                out[rid.strip()] = (float(x), float(y))
    return out


FLEET_PARKING = _parse_fleet(SIM_FLEET)

layout = Layout(SITE)
_lock = threading.RLock()
_state: Dict[str, Any] = {"world": None, "mode": "live", "seed": SIM_SEED, "events": []}
_used_permits: Dict[str, float] = {}     # permit id -> expiry; a permit works once
_estop: Dict[str, Any] = {"engaged": False, "reason": "", "since": None}       # global
_robot_estops: Dict[str, Dict[str, Any]] = {}                                   # robot id -> reason/since
_deadman: Dict[str, Any] = {"last_move": None, "tripped": 0}                     # robot-1 (kept for compatibility)
_others: Dict[str, RobotState] = {rid: RobotState(*xy) for rid, xy in FLEET_PARKING.items()}
_other_deadman: Dict[str, Dict[str, Any]] = {rid: {"last_move": None, "tripped": 0} for rid in FLEET_PARKING}
_contacts: Dict[str, int] = {"robot_contact": 0}
_boot_id = uuid.uuid4().hex
_generations: Dict[str, int] = {}
_journal = ControllerJournal(SIM_STATE_DB)
for _stopped_id, _stop in _journal.stops().items():
    if _stopped_id == "*":
        _estop.update(engaged=True, **_stop)
    else:
        _robot_estops[_stopped_id] = _stop


def _fence(robot_id: Optional[str] = None) -> None:
    """Called under _lock. A stop/reset overtakes every earlier pending reply."""
    for rid in [robot_id] if robot_id else fleet_ids():
        _generations[rid] = _generations.get(rid, 0) + 1


def _controller_context(w: World, robot_id: str) -> dict:
    return dict(_journal.environment(w.layout.experience_identity), boot_id=_boot_id, generation=_generations.get(robot_id, 0),
                capability_profile_version=configured_profile(SITE, robot_id).version)


def _environment_change(w: World, reason: str) -> None:
    _fence()
    for rid in fleet_ids():
        _robot(w, rid).target = None
    _journal.environment(w.layout.experience_identity, reason)


def _http_redemption(envelope: str) -> str:
    """Bounded callback, outside _lock; never retry a spent permit automatically."""
    request = urllib.request.Request(AUTHORITY_BASE_URL + "/authority/redeem",
                                     data=json.dumps({"request": envelope}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
    try:
        # Do not send signed controller requests through an ambient HTTP proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=SIM_REDEEM_TIMEOUT_S) as response:
            result = json.loads(response.read(131072))
            if not isinstance(result, dict) or not isinstance(result.get("redemption"), str):
                raise ValueError("missing redemption")
            return result["redemption"]
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            try:
                detail = json.loads(exc.read(65536)).get("detail", "authority_refused")
            except (ValueError, TypeError):
                detail = "authority_refused"
            raise HTTPException(status_code=403, detail=detail) from exc
        raise HTTPException(status_code=503, detail="authority_unavailable") from exc
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=503, detail="authority_unavailable") from exc


def _post_redemption(envelope: str) -> str:
    return _http_redemption(envelope)


def fleet_ids() -> List[str]:
    return [SIM_ROBOT_ID] + list(_others)


def _robot(w: World, robot_id: Optional[str]) -> RobotState:
    rid = robot_id or SIM_ROBOT_ID
    if rid == SIM_ROBOT_ID:
        return w.robot
    if rid in _others:
        return _others[rid]
    raise HTTPException(status_code=404, detail=f"unknown robot {rid}")


def _estopped(robot_id: str) -> bool:
    return bool(_estop["engaged"]) or robot_id in _robot_estops


def _robot_bodies(w: World, exclude: str) -> List[Circle]:
    """Every other robot as a solid body."""
    bodies = []
    for rid in fleet_ids():
        if rid != exclude:
            r = _robot(w, rid)
            bodies.append(Circle(r.x, r.y, configured_profile(SITE, rid).radius_m, "robot"))
    return bodies


def _require_token(request: Request) -> None:
    if SIM_TOKEN and (request.headers.get("X-Sim-Token") or "").strip() != SIM_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized simulator call")


# ---------------------------------------------------------------------------
# World construction
# ---------------------------------------------------------------------------

def _crossing_loop(rng: random.Random, hotspot, name: str, nav: ActorNavigation):
    """Someone who keeps crossing at a hotspot: across, pause, back."""
    vertical = abs(hotspot[1] - VEHICLE_LANE[0][1]) < 0.5 or rng.random() < 0.5   # across the vehicle lane
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
    stations = [f for f in layout.data.get("features", []) if f["type"] in ("packing_station", "work_station", "qc_station")]
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
    for k, hs in enumerate(rng.sample(SITE_HOTSPOTS or HOTSPOTS, 3)):
        worker = _crossing_loop(rng, hs, f"Runner {k + 1}", nav)
        if worker:
            world.walkers.append(worker)
    start, end = world.vehicle_nav.safe_point(VEHICLE_LANE[0]), world.vehicle_nav.safe_point(VEHICLE_LANE[-1])
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
            w = _world()
            last = _deadman["last_move"]
            if (SIM_DEADMAN_S > 0 and w.robot.target is not None and last is not None
                    and time.monotonic() - last > SIM_DEADMAN_S):
                w.command("STOP")
                _fence(SIM_ROBOT_ID)
                _deadman["tripped"] += 1
                _deadman["last_move"] = None
            for rid, r in _others.items():
                dm = _other_deadman[rid]
                if (SIM_DEADMAN_S > 0 and r.target is not None and dm["last_move"] is not None
                        and time.monotonic() - dm["last_move"] > SIM_DEADMAN_S):
                    r.target = None
                    _fence(rid)
                    dm["tripped"] += 1
                    dm["last_move"] = None
                drive_robot(r, dt * SIM_SPEED)
            w.step(dt * SIM_SPEED)
            ids = fleet_ids()
            for i, a in enumerate(ids):
                for b in ids[i + 1:]:
                    ra, rb = _robot(w, a), _robot(w, b)
                    if math.hypot(ra.x - rb.x, ra.y - rb.y) < configured_profile(SITE, a).radius_m + configured_profile(SITE, b).radius_m:
                        _contacts["robot_contact"] += 1
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


def _telemetry(w: World, robot_id: Optional[str] = None) -> Dict[str, Any]:
    """Telemetry for one robot; the other robots appear as obstacles."""
    rid = robot_id or SIM_ROBOT_ID
    bodies = _robot_bodies(w, rid)       # from real positions, before any swap
    peers = [{"robot_id": peer, "x": round(_robot(w,peer).x,3), "y": round(_robot(w,peer).y,3),
              "theta": _robot(w,peer).theta, "speed": _robot(w,peer).speed,
              "robot_kind": configured_profile(SITE,peer).kind}
             for peer in fleet_ids() if peer != rid]
    if rid != SIM_ROBOT_ID:
        r = _robot(w, rid)
        saved = w.robot
        w.robot = r                      # reuse the world's sensing for this robot's pose
        try:
            tel = _telemetry_one(w, rid, bodies, peers)
        finally:
            w.robot = saved
        return tel
    return _telemetry_one(w, rid, bodies, peers)


def _telemetry_one(w: World, robot_id: str, bodies: List[Circle], peers: List[Dict[str, Any]]) -> Dict[str, Any]:
    tel = w.telemetry()
    profile = configured_profile(SITE, robot_id)
    tel['nearest_obstacle_m'] += ROBOT_R - profile.radius_m
    for body in bodies:                  # other robots count as obstacles for clearance
        gap = body.distance(w.robot.x, w.robot.y) - profile.radius_m
        if gap < tel["nearest_obstacle_m"]:
            tel["nearest_obstacle_m"] = round(gap, 3)
            p = body.nearest_point(w.robot.x, w.robot.y)
            tel["nearest_obstacle_xy"] = [round(p[0], 3), round(p[1], 3)]
    events = list(_state["events"])
    if tel["nearest_obstacle_m"] < 0:   # bodies overlap: report contact, not an impossible distance
        tel["nearest_obstacle_m"] = 0.0
        events.append("contact")
    people = _people(w)
    nearest = min(people, key=lambda p: math.hypot(p["x"] - w.robot.x, p["y"] - w.robot.y), default=None)
    tel.update({
        **_controller_context(w, robot_id),
        "environment_changes": _journal.environment_changes(),
        "accepted_actions": _journal.accepted(robot_id),
        "events": events,
        "human": dict(nearest, type="human", id="nearest", role="primary") if nearest else None,
        "walking_humans": people,
        "idle_robots": peers,
        "obstacles": _obstacles(w) + [{"x": round(b.x, 2), "y": round(b.y, 2), "r": b.r, "type": "robot"}
                                      for b in bodies],
        "bounds": w.layout.geofence,
        "target": w.robot.target,
        "robot_id": robot_id,
        "robot_kind": profile.kind, "robot_profile": profile.public(),
        "estop": dict(_estop, robot=_robot_estops.get(robot_id)),
        "deadman_trips": (_deadman if robot_id == SIM_ROBOT_ID else _other_deadman[robot_id])["tripped"],
        "robot_contacts": _contacts["robot_contact"],
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
    # Required for MOVE_TO: the action's identity fields and its signed permit
    action: Optional[Dict[str, Any]] = None
    permit: Optional[str] = None
    robot_id: Optional[str] = None      # STOP / WAIT target (MOVE_TO uses the permit's robot)


class EstopRequest(BaseModel):
    engaged: bool
    reason: str = ""
    release_token: str = ""
    robot_id: Optional[str] = None      # None = every robot


def _check_permit(cmd: Command) -> dict:
    """Refuse a move unless its permit is valid for exactly this command and unused."""
    if len(PERMIT_SECRET) < 32:
        raise HTTPException(status_code=403, detail="permit_verification_not_configured")
    if not cmd.permit or not isinstance(cmd.action, dict):
        raise HTTPException(status_code=403, detail="permit_required")
    action = dict(cmd.action, kind=cmd.intent, params=cmd.params)
    if action.get("robot_id") not in fleet_ids():
        raise HTTPException(status_code=403, detail="wrong_robot")
    try:
        payload = permits.verify_for_action(PERMIT_SECRET, cmd.permit, action)
    except permits.PermitError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    now = time.time()
    for pid in [p for p, exp in _used_permits.items() if exp < now]:
        del _used_permits[pid]
    if payload["id"] in _used_permits or _journal.seen(payload["id"]):
        raise HTTPException(status_code=403, detail="permit_replayed")
    if payload.get("controller") != _controller_context(_world(), action["robot_id"]):
        raise HTTPException(status_code=403, detail="controller_context_changed")
    return payload


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
def telemetry(request: Request, robot_id: Optional[str] = None):
    _require_token(request)
    with _lock:
        return _telemetry(_world(), robot_id)


@app.get("/fleet")
def fleet(request: Request):
    """Every robot: pose, target, e-stop and dead-man state."""
    _require_token(request)
    with _lock:
        w = _world()
        out = []
        for rid in fleet_ids():
            r = _robot(w, rid)
            out.append({"robot_id": rid, "robot_kind": configured_profile(SITE,rid).kind, "robot_profile": configured_profile(SITE,rid).public(), "x": round(r.x, 3), "y": round(r.y, 3), "theta": round(r.theta, 3),
                        "speed": round(r.speed, 3), "target": r.target, "estopped": _estopped(rid)})
        return {"robots": out, "robot_contacts": _contacts["robot_contact"]}


@app.get("/world")
def world(request: Request):
    _require_token(request)
    with _lock:
        w = _world()
        d = w.layout.data
        people = _people(w)
        return {
            **_journal.environment(w.layout.experience_identity),
            "geofence": d["geofence"], "zones": d["zones"], "racks": d.get("racks", []),
            "features": d.get("features", []), "bays": d["bays"], "obstacles": _obstacles(w),
            "human": people[0] if people else None, "walking_humans": people, "idle_robots": [],
            "hotspots": [{"x": x, "y": y} for x, y in (SITE_HOTSPOTS or HOTSPOTS)], "mode": _state["mode"], "seed": _state["seed"],
            "site": {"name": SITE.get("name", SITE_LAYOUT), "title": SITE.get("title", "Warehouse")},
            "presets": SITE.get("presets", []), "parking": SITE.get("parking", {}),
        }


@app.post("/reset")
def reset_robot(request: Request, robot_id: Optional[str] = None):
    _require_token(request)
    with _lock:
        w = _world()
        rid = robot_id or SIM_ROBOT_ID
        _fence(rid)
        if rid != SIM_ROBOT_ID:
            _robot(w, rid)
            _others[rid] = RobotState(*FLEET_PARKING[rid])
            x, y = FLEET_PARKING[rid]
            return {"ok": True, "position": {"x": x, "y": y}, "msg": f"{rid} reset to its parking spot"}
        start = PARKING if _state["mode"] == "live" else _state.get("start", PARKING)
        w.robot = RobotState(*start)
        _state["events"] = []
        return {"ok": True, "position": {"x": start[0], "y": start[1]}, "msg": "Robot reset to start"}


@app.post("/command")
def command(request: Request, cmd: Command):
    _require_token(request)
    if cmd.intent == "MOVE_TO":
        # Snapshot under the local lock, then release it for the network call.
        # STOP/e-stop and physics remain responsive during an authority outage.
        with _lock:
            w = _world()
            rid = (cmd.action or {}).get("robot_id") or SIM_ROBOT_ID
            if _estopped(rid):
                raise HTTPException(status_code=423, detail="estop_engaged")
            violation = move_violation(configured_profile(SITE, rid), cmd.params)
            if violation:
                raise HTTPException(status_code=403, detail=violation)
            payload = _check_permit(cmd)
            action = dict(cmd.action, kind=cmd.intent, params=cmd.params)
            context = _controller_context(w, rid)
            try:
                x, y, speed = float(cmd.params["x"]), float(cmd.params["y"]), float(cmd.params.get("max_speed", 0.5))
                g = w.layout.geofence
                if (not all(math.isfinite(v) for v in (x, y, speed)) or speed < 0
                        or not (g["min_x"] <= x <= g["max_x"] and g["min_y"] <= y <= g["max_y"])):
                    raise ValueError("outside geofence or invalid speed")
            except (KeyError, TypeError, ValueError) as exc:
                raise HTTPException(status_code=403, detail="invalid_move_parameters") from exc
            envelope = permits.redemption_request(PERMIT_SECRET, cmd.permit, action, context)
        response = _post_redemption(envelope)
        with _lock:
            w = _world()
            if _estopped(rid) or context != _controller_context(w, rid):
                raise HTTPException(status_code=403, detail="controller_context_changed")
            try:
                permits.verify_redemption_response(PERMIT_SECRET, response, envelope)
                permits.verify_for_action(PERMIT_SECRET, cmd.permit, action)
            except permits.PermitError as exc:
                raise HTTPException(status_code=403, detail=str(exc)) from exc
            try:
                _journal.accept(action, payload["id"])
            except sqlite3.IntegrityError as exc:
                raise HTTPException(status_code=403, detail="permit_replayed") from exc
            except sqlite3.Error as exc:
                raise HTTPException(status_code=503, detail="controller_journal_unavailable") from exc
            _used_permits[payload["id"]] = float(payload["expires"])
            _fence(rid)
            r = _robot(w, rid)
            r.target = {"x": x, "y": y, "max_speed": speed}
            (_deadman if rid == SIM_ROBOT_ID else _other_deadman[rid])["last_move"] = time.monotonic()
            return {"ok": True, "set_target": r.target, "robot_id": rid, "action_id": action["action_id"]}
    with _lock:
        w = _world()
        if cmd.intent in ("STOP", "WAIT"):
            _fence(cmd.robot_id or SIM_ROBOT_ID)
            r = _robot(w, cmd.robot_id)
            r.target = None
            if cmd.intent == "STOP":
                return {"ok": True, "stopped": True, "robot_id": cmd.robot_id or SIM_ROBOT_ID}
            return {"ok": True, "wait": cmd.params.get("seconds", 1), "robot_id": cmd.robot_id or SIM_ROBOT_ID}
        return {"ok": False, "error": f"Unknown intent: {cmd.intent}"}


@app.post("/estop")
def estop(request: Request, body: EstopRequest):
    """Controller-level stop. Engaging is always allowed; releasing needs a release
    token signed by the backend, so only an authorized reset can lift it."""
    _require_token(request)
    with _lock:
        w = _world()
        if body.engaged:
            _fence(body.robot_id)
            if body.robot_id:                       # one robot
                _robot(w, body.robot_id).target = None
                _robot_estops.setdefault(body.robot_id, {"reason": body.reason, "since": time.time()})
            else:                                   # every robot
                for rid in fleet_ids():
                    _robot(w, rid).target = None
                if not _estop["engaged"]:
                    _estop.update(engaged=True, reason=body.reason, since=time.time())
            _journal.stop(body.robot_id or "*", body.reason)
            return {"ok": True, "engaged": True, "robot_id": body.robot_id}
        if len(PERMIT_SECRET) < 32:
            raise HTTPException(status_code=403, detail="permit_verification_not_configured")
        try:
            release = permits.verify_release(PERMIT_SECRET, body.release_token, body.robot_id or "*")
            _journal.release(body.robot_id or "*", release["id"])
        except permits.PermitError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=403, detail="release_replayed") from exc
        _fence(body.robot_id)
        if body.robot_id:
            _robot_estops.pop(body.robot_id, None)
        else:
            _estop.update(engaged=False, reason="", since=None)
        return {"ok": True, "engaged": False, "robot_id": body.robot_id}


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
        if body.scenario not in SCENARIOS:
            raise HTTPException(status_code=422, detail="unknown_scenario")
        _environment_change(w, f"scenario:{body.scenario}")
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
        _environment_change(_world(), f"seed:{body.mode}:{body.seed}")
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
def frame(request: Request, size: int = 512, view_m: float = 12.0, robot_id: Optional[str] = None):
    """Robot camera: a heading-up top-down view around the robot, as PNG."""
    _require_token(request)
    from camera import render
    with _lock:
        w = _world()
        saved = w.robot
        w.robot = _robot(w, robot_id)
        try:
            png = render(w, size=max(128, min(size, 1024)), view_m=max(4.0, min(view_m, 30.0)))
        finally:
            w.robot = saved
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
