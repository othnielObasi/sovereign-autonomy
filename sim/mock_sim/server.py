from __future__ import annotations

"""Mock Simulator

- Maintains a robot state in memory.
- Updates position toward a target goal when it receives MOVE_TO.
- Produces a lightweight "perception" summary:
  - nearest obstacle distance
  - human distance (metres)
  - whether a human is detected (nearby)
  - confidence score (simulated)
- Emits simple events like near_miss when clearance is low.
- Supports deterministic scenario injection via POST /scenario.

This is intentionally simple but realistic enough for a governance/ops demo.
"""

import json
import math
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Sovereign Autonomy Mock Simulator", version="0.1.0")

SIM_TICK_HZ = float(os.getenv("SIM_TICK_HZ", "10"))
DT = 1.0 / max(SIM_TICK_HZ, 1.0)

# Motion dynamics
MAX_ACCEL = 0.8       # m/s^2 — trapezoidal velocity ramp-up
MAX_DECEL = 1.2       # m/s^2 — braking deceleration
MAX_HEADING_RATE = 2.0  # rad/s — maximum turning rate

SIM_TOKEN = os.getenv("SIM_TOKEN", "").strip()


def _require_sim_token(request: Request) -> None:
    """Require X-Sim-Token header if SIM_TOKEN is configured."""
    if not SIM_TOKEN:
        return
    got = (request.headers.get("X-Sim-Token") or "").strip()
    if got != SIM_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized simulator call")


# --- Load world.json relative to this file, not the CWD ---
HERE = Path(__file__).resolve().parent
WORLD_PATH = HERE / "world.json"
with WORLD_PATH.open("r", encoding="utf-8") as f:
    WORLD = json.load(f)

OBSTACLES: List[Dict[str, Any]] = list(WORLD.get("obstacles", []))
HUMAN_DEFAULT = WORLD.get("human", {"x": 14, "y": 7})
ZONES = WORLD.get("zones", [])
GEOFENCE = WORLD.get("geofence", {"min_x": 0, "max_x": 40, "min_y": 0, "max_y": 25})
BAYS = WORLD.get("bays", [])


class Command(BaseModel):
    intent: str = Field(..., description="MOVE_TO|STOP|WAIT")
    params: Dict[str, Any] = Field(default_factory=dict)


class PathSmoothRequest(BaseModel):
    """Request for Bezier path smoothing."""
    waypoints: List[Dict[str, float]] = Field(..., description="List of {x, y} waypoints")
    resolution: int = Field(default=20, ge=5, le=100, description="Points per Bezier segment")


class ScenarioRequest(BaseModel):
    scenario: str = Field(
        ...,
        description=(
            "human_approach|human_too_close|path_blocked|clear|"
            "speed_violation|geofence_breach|low_confidence|"
            "multi_worker_congestion|loading_bay_rush|corridor_squeeze"
        ),
    )
    params: Dict[str, Any] = Field(default_factory=dict)


# ---- Mutable human position (can be moved by scenarios) ----
human_pos: Dict[str, float] = dict(HUMAN_DEFAULT)
# Extra obstacles injected by scenarios
extra_obstacles: List[Dict[str, float]] = []
# Scenario lock: when a scenario (e.g. human_approach) is injected we hold the
# primary human at the injected location for a short deterministic window so
# governance reactions are reproducible. This avoids immediate override by
# ambient walking behaviour.
scenario_lock_until: float = 0.0
SCENARIO_LOCK_SECS = 5.0

# ---- Additional walking humans (ambient warehouse workers) ----
# Each has a patrol path and walks between waypoints
import copy

class WalkingHuman:
    """A human worker that walks a patrol loop in the warehouse."""

    def __init__(self, name: str, waypoints: List[Dict[str, float]], speed: float = 0.6):
        self.name = name
        self.waypoints = waypoints
        self.speed = speed
        self.pos = dict(waypoints[0])
        self.wp_idx = 0
        self.paused_until = 0.0  # timestamp to pause until (simulates stopping at a shelf)

    def step(self, dt: float) -> None:
        now = time.time()
        if now < self.paused_until:
            return
        tgt = self.waypoints[self.wp_idx]
        dx = tgt["x"] - self.pos["x"]
        dy = tgt["y"] - self.pos["y"]
        d = math.sqrt(dx * dx + dy * dy)
        if d < 0.15:
            # Arrived at waypoint — pause briefly, then move to next
            self.paused_until = now + random.uniform(1.0, 3.0)
            self.wp_idx = (self.wp_idx + 1) % len(self.waypoints)
        else:
            step = min(self.speed * dt, d)
            self.pos["x"] += (dx / d) * step
            self.pos["y"] += (dy / d) * step

    def to_dict(self) -> Dict[str, Any]:
        return {"x": round(self.pos["x"], 2), "y": round(self.pos["y"], 2), "name": self.name, "type": "worker", "conf": 0.9}


# Patrol routes that feel natural for a warehouse
# Aisle A: y≈3.5 (between rack rows A and B)
# Aisle B: y≈7.5 (between rack rows B and C)
# Cross-aisle gaps at x≈12.5 and x≈25.5
walking_humans: List[WalkingHuman] = [
    WalkingHuman("Worker A", [
        {"x": 3, "y": 3.5}, {"x": 10, "y": 3.5},
        {"x": 12.5, "y": 7.5}, {"x": 3, "y": 7.5},
    ], speed=0.5),
    WalkingHuman("Worker B", [
        {"x": 10, "y": 17}, {"x": 20, "y": 17}, {"x": 20, "y": 22}, {"x": 10, "y": 22},
    ], speed=0.4),
    WalkingHuman("Forklift Op", [
        {"x": 12, "y": 13.5}, {"x": 30, "y": 13.5}, {"x": 30, "y": 21}, {"x": 12, "y": 21},
    ], speed=0.7),
]

# Make the primary human dynamic by turning it into a WalkingHuman
# Primary human will patrol a small square around the default human location.
try:
    _hx = float(HUMAN_DEFAULT.get("x", 14))
    _hy = float(HUMAN_DEFAULT.get("y", 7))
except Exception:
    _hx, _hy = 14.0, 7.0

primary_human = WalkingHuman(
    "Primary Human",
    [
        {"x": _hx, "y": _hy},
        {"x": _hx + 2.0, "y": _hy},
        {"x": _hx + 2.0, "y": _hy + 2.0},
        {"x": _hx, "y": _hy + 2.0},
    ],
    speed=0.45,
)

# Append primary human to walking_humans so it is stepped and included in telemetry
walking_humans.append(primary_human)

# ---- Second robot (idle in staging area, for visual realism) ----
idle_robots: List[Dict[str, Any]] = [
    {"x": 34.0, "y": 17.0, "theta": 1.57, "speed": 0.0, "label": "R-02 (Idle)", "status": "idle"},
]


state: Dict[str, Any] = {
    "x": 3.0,
    "y": 3.5,
    "theta": 0.0,
    "speed": 0.0,
    "zone": "aisle",
    "nearest_obstacle_m": 999.0,
    "human_detected": False,
    "human_conf": 0.0,
    "human_distance_m": 999.0,
    "events": [],
    "target": None,  # {"x": float, "y": float, "max_speed": float}
    "last_update": time.time(),
}


def _zone_for(x: float, y: float) -> str:
    for z in ZONES:
        r = z["rect"]
        if r["min_x"] <= x <= r["max_x"] and r["min_y"] <= y <= r["max_y"]:
            return z["name"]
    return "aisle"


def _dist(a: Dict[str, Any], x: float, y: float) -> float:
    return math.sqrt((a["x"] - x) ** 2 + (a["y"] - y) ** 2)


def _all_obstacles() -> List[Dict[str, Any]]:
    return OBSTACLES + extra_obstacles


def _nearest_obstacle(x: float, y: float) -> float:
    obs = _all_obstacles()
    if not obs:
        return 999.0
    return min(_dist(o, x, y) for o in obs)


def _human_signal(x: float, y: float) -> tuple[bool, float, float]:
    """Returns (detected, confidence, distance_m) for the nearest human (primary + walking)."""
    # Check primary human
    d_primary = _dist(human_pos, x, y)

    # Check walking humans — find nearest overall
    d_min = d_primary
    for wh in walking_humans:
        d_wh = _dist(wh.pos, x, y)
        if d_wh < d_min:
            d_min = d_wh

    detected = d_min < 5.0  # wider detection radius for distance-based governance
    if not detected:
        return False, 0.0, d_min
    # Support forced low confidence for low_confidence scenario
    if state.get("_force_low_conf"):
        conf = random.uniform(0.35, 0.50)
        state.pop("_force_low_conf", None)
    else:
        conf = max(0.4, min(0.95, 0.7 + random.uniform(-0.15, 0.15)))
    return True, conf, d_min


def _step() -> None:
    now = time.time()
    dt = now - state["last_update"]
    if dt <= 0:
        return
    state["last_update"] = now
    state["events"] = []

    # Tick walking humans
    for wh in walking_humans:
        wh.step(dt)

    # Update the primary human canonical position used elsewhere in the simulator
    try:
        # Respect scenario lock: if a deterministic scenario was injected
        # recently, keep the human at that injected location until the lock
        # expires. Otherwise let the primary human patrol normally.
        if time.time() > scenario_lock_until:
            human_pos["x"] = primary_human.pos["x"]
            human_pos["y"] = primary_human.pos["y"]
    except Exception:
        pass

    target = state.get("target")
    if target:
        tx, ty = float(target["x"]), float(target["y"])
        max_speed = float(target.get("max_speed", 0.5))

        dx, dy = tx - state["x"], ty - state["y"]
        dist = math.sqrt(dx * dx + dy * dy)

        if dist < 0.05:
            # Arrived
            state["speed"] = 0.0
            state["target"] = None
        else:
            # --- Trapezoidal velocity profile ---
            current_speed = state["speed"]

            # Desired speed starts at max_speed
            desired_speed = max_speed

            # Basic slowdown near obstacles to make demo interesting
            obs = _nearest_obstacle(state["x"], state["y"])
            if obs < 0.8:
                desired_speed = min(desired_speed, 0.35)
                state["events"].append("near_miss")

            # Deceleration ramp: slow down when approaching target
            # v^2 = 2 * a * d  →  v = sqrt(2 * MAX_DECEL * dist)
            decel_speed = math.sqrt(2.0 * MAX_DECEL * dist)
            desired_speed = min(desired_speed, decel_speed)

            # Apply acceleration/deceleration limits
            if desired_speed > current_speed:
                step_speed = min(desired_speed, current_speed + MAX_ACCEL * dt)
            else:
                step_speed = max(desired_speed, current_speed - MAX_DECEL * dt)
            step_speed = max(step_speed, 0.0)

            # --- Heading rate limit ---
            desired_theta = math.atan2(dy, dx)
            current_theta = state["theta"]
            # Shortest angular difference
            dtheta = math.atan2(math.sin(desired_theta - current_theta),
                                math.cos(desired_theta - current_theta))
            max_dtheta = MAX_HEADING_RATE * dt
            clamped_dtheta = max(-max_dtheta, min(max_dtheta, dtheta))
            new_theta = current_theta + clamped_dtheta

            # Move along the *current* (rate-limited) heading
            ux = math.cos(new_theta)
            uy = math.sin(new_theta)
            step_dist = step_speed * dt
            state["x"] += ux * min(step_dist, dist)
            state["y"] += uy * min(step_dist, dist)
            state["theta"] = new_theta
            state["speed"] = step_speed

    # Update perception
    state["zone"] = _zone_for(state["x"], state["y"])
    state["nearest_obstacle_m"] = float(_nearest_obstacle(state["x"], state["y"]))
    hd, hc, hd_m = _human_signal(state["x"], state["y"])
    state["human_detected"] = hd
    state["human_conf"] = float(hc)
    state["human_distance_m"] = float(hd_m)

    # Geofence enforcement: clamp position to boundaries
    if state["x"] < GEOFENCE["min_x"]:
        state["x"] = GEOFENCE["min_x"]
        state["speed"] = 0.0
        state["target"] = None
        state["events"].append("geofence_violation")
    elif state["x"] > GEOFENCE["max_x"]:
        state["x"] = GEOFENCE["max_x"]
        state["speed"] = 0.0
        state["target"] = None
        state["events"].append("geofence_violation")
    if state["y"] < GEOFENCE["min_y"]:
        state["y"] = GEOFENCE["min_y"]
        state["speed"] = 0.0
        state["target"] = None
        state["events"].append("geofence_violation")
    elif state["y"] > GEOFENCE["max_y"]:
        state["y"] = GEOFENCE["max_y"]
        state["speed"] = 0.0
        state["target"] = None
        state["events"].append("geofence_violation")


@app.get("/health")
def health():
    """Liveness check — no auth required."""
    return {"status": "ok"}


@app.get("/telemetry")
def telemetry(request: Request):
    _require_sim_token(request)
    _step()
    return {
        "x": round(state["x"], 4),
        "y": round(state["y"], 4),
        "theta": round(state["theta"], 4),
        "speed": round(state["speed"], 4),
        "zone": state["zone"],
        "nearest_obstacle_m": round(state["nearest_obstacle_m"], 3),
        "human_detected": state["human_detected"],
        "human_conf": round(state["human_conf"], 3),
        "human_distance_m": round(state["human_distance_m"], 3),
        "events": state["events"],
        # Enriched fields
        "human": {"x": human_pos["x"], "y": human_pos["y"], "type": "human", "id": "primary", "role": "primary"},
        # Mark walking humans explicitly as workers; primary human is also present in this list
        "walking_humans": [dict(wh.to_dict(), role="worker") for wh in walking_humans],
        "idle_robots": idle_robots,
        "obstacles": _all_obstacles(),
        "bounds": GEOFENCE,
        "target": state.get("target"),
        "timestamp": time.time(),
    }


@app.get("/world")
def world(request: Request):
    _require_sim_token(request)
    return {
        "geofence": GEOFENCE,
        "zones": ZONES,
        "obstacles": _all_obstacles(),
        "human": human_pos,
        "walking_humans": [wh.to_dict() for wh in walking_humans],
        "idle_robots": idle_robots,
        "bays": BAYS,
    }


@app.post("/reset")
def reset_robot(request: Request):
    """Reset robot to starting position (2, 2) with zero velocity.

    Called at the beginning of each run to ensure a clean starting state.
    """
    _require_sim_token(request)
    state["x"] = 2.0
    state["y"] = 2.0
    state["theta"] = 0.0
    state["speed"] = 0.0
    state["target"] = None
    state["events"] = []
    state["last_update"] = time.time()
    # Reset perception to clean state
    state["zone"] = _zone_for(2.0, 2.0)
    state["nearest_obstacle_m"] = float(_nearest_obstacle(2.0, 2.0))
    hd, hc, hd_m = _human_signal(2.0, 2.0)
    state["human_detected"] = hd
    state["human_conf"] = float(hc)
    state["human_distance_m"] = float(hd_m)
    return {"ok": True, "position": {"x": 2.0, "y": 2.0}, "msg": "Robot reset to start"}


@app.post("/command")
def command(request: Request, cmd: Command):
    _require_sim_token(request)
    _step()

    if cmd.intent == "MOVE_TO":
        x = float(cmd.params.get("x", state["x"]))
        y = float(cmd.params.get("y", state["y"]))
        max_speed = float(cmd.params.get("max_speed", 0.5))
        # Reject targets outside geofence
        if not (GEOFENCE["min_x"] <= x <= GEOFENCE["max_x"] and GEOFENCE["min_y"] <= y <= GEOFENCE["max_y"]):
            return {"ok": False, "error": f"Target ({x},{y}) outside geofence"}
        state["target"] = {"x": x, "y": y, "max_speed": max_speed}
        return {"ok": True, "set_target": state["target"]}

    if cmd.intent == "STOP":
        state["target"] = None
        state["speed"] = 0.0
        return {"ok": True, "stopped": True}

    if cmd.intent == "WAIT":
        return {"ok": True, "wait": cmd.params.get("seconds", 1)}

    return {"ok": False, "error": f"Unknown intent: {cmd.intent}"}


# ---------------------------------------------------------------------------
# Scenario injection (Fix 2)
# ---------------------------------------------------------------------------
@app.post("/scenario")
def inject_scenario(request: Request, body: ScenarioRequest):
    """Deterministically inject a scenario for governance demo.

    Scenarios:
      - human_approach: Move human to ~2.5m from robot (triggers SLOW)
      - human_too_close: Move human to ~0.8m from robot (triggers STOP)
      - path_blocked: Insert obstacle directly ahead of robot
      - clear: Reset human & obstacles to defaults
    """
    _require_sim_token(request)
    global human_pos, extra_obstacles, scenario_lock_until

    rx, ry = state["x"], state["y"]
    theta = state.get("theta", 0.0)

    if body.scenario == "human_approach":
        # Place human 2.5m ahead of robot
        human_pos["x"] = round(rx + 2.5 * math.cos(theta), 2)
        human_pos["y"] = round(ry + 2.5 * math.sin(theta), 2)
        # Lock this injected position for a short deterministic window
        scenario_lock_until = time.time() + SCENARIO_LOCK_SECS
        return {"ok": True, "scenario": "human_approach", "human": dict(human_pos)}

    elif body.scenario == "human_too_close":
        # Place human 0.8m ahead of robot
        human_pos["x"] = round(rx + 0.8 * math.cos(theta), 2)
        human_pos["y"] = round(ry + 0.8 * math.sin(theta), 2)
        # Lock this injected position for a short deterministic window
        scenario_lock_until = time.time() + SCENARIO_LOCK_SECS
        return {"ok": True, "scenario": "human_too_close", "human": dict(human_pos)}

    elif body.scenario == "path_blocked":
        # Insert obstacle 1.5m ahead of robot
        ox = round(rx + 1.5 * math.cos(theta), 2)
        oy = round(ry + 1.5 * math.sin(theta), 2)
        extra_obstacles.append({"x": ox, "y": oy, "r": 0.4})
        return {"ok": True, "scenario": "path_blocked", "obstacle": {"x": ox, "y": oy}}

    elif body.scenario == "clear":
        # Reset to defaults
        human_pos.update(HUMAN_DEFAULT)
        extra_obstacles.clear()
        # Clear any scenario lock so ambient behaviour resumes
        scenario_lock_until = 0.0
        # Reset walking humans to initial positions
        for wh in walking_humans:
            wh.pos = dict(wh.waypoints[0])
            wh.wp_idx = 0
            wh.paused_until = 0.0
        return {"ok": True, "scenario": "clear"}

    elif body.scenario == "speed_violation":
        # Teleport robot into the loading_bay zone and set a high-speed target
        # across the bay.  The governance engine should flag SAFE_SPEED_01
        # because loading_bay limit is 0.4 m/s.
        state["x"] = 5.0
        state["y"] = 21.0
        state["theta"] = 0.0
        state["target"] = {"x": 35.0, "y": 21.0, "max_speed": 0.8}
        state["speed"] = 0.8
        return {"ok": True, "scenario": "speed_violation", "robot": {"x": 5.0, "y": 21.0}, "target": state["target"]}

    elif body.scenario == "geofence_breach":
        # Move robot to the edge of the geofence and set a target outside it.
        # Governance should flag GEOFENCE_01.
        state["x"] = 39.0
        state["y"] = 12.0
        state["theta"] = 0.0
        state["target"] = {"x": 42.0, "y": 12.0, "max_speed": 0.5}
        state["speed"] = 0.5
        return {"ok": True, "scenario": "geofence_breach", "robot": {"x": 39.0, "y": 12.0}, "target": state["target"]}

    elif body.scenario == "low_confidence":
        # Place human near robot but inject low-confidence perception.
        # This triggers UNCERTAINTY_04.
        human_pos["x"] = round(rx + 2.0 * math.cos(theta), 2)
        human_pos["y"] = round(ry + 2.0 * math.sin(theta), 2)
        scenario_lock_until = time.time() + SCENARIO_LOCK_SECS
        # We force a low confidence next tick by adding a transient noise flag
        state["_force_low_conf"] = True
        return {"ok": True, "scenario": "low_confidence", "human": dict(human_pos)}

    elif body.scenario == "multi_worker_congestion":
        # Move three walking workers very close to the robot's current position
        # to create a congested zone.  Multiple proximity policies fire.
        offsets = [(1.5, 0.5), (-0.8, 1.2), (0.5, -1.0)]
        moved = []
        for i, (dx, dy) in enumerate(offsets):
            if i < len(walking_humans):
                walking_humans[i].pos["x"] = round(rx + dx, 2)
                walking_humans[i].pos["y"] = round(ry + dy, 2)
                walking_humans[i].paused_until = time.time() + SCENARIO_LOCK_SECS
                moved.append(walking_humans[i].to_dict())
        scenario_lock_until = time.time() + SCENARIO_LOCK_SECS
        return {"ok": True, "scenario": "multi_worker_congestion", "workers": moved}

    elif body.scenario == "loading_bay_rush":
        # Simulate a busy loading bay: teleport robot to the bay and place two
        # workers + an obstacle in the path.  Triggers speed limit, proximity,
        # and obstacle clearance policies simultaneously.
        state["x"] = 8.0
        state["y"] = 20.0
        state["theta"] = 0.0
        state["target"] = {"x": 30.0, "y": 20.0, "max_speed": 0.6}
        state["speed"] = 0.6
        # Workers blocking the path
        if len(walking_humans) >= 2:
            walking_humans[0].pos = {"x": 14.0, "y": 20.5}
            walking_humans[0].paused_until = time.time() + SCENARIO_LOCK_SECS
            walking_humans[1].pos = {"x": 20.0, "y": 19.5}
            walking_humans[1].paused_until = time.time() + SCENARIO_LOCK_SECS
        # Pallet obstacle
        extra_obstacles.append({"x": 17.0, "y": 20.0, "r": 0.5})
        scenario_lock_until = time.time() + SCENARIO_LOCK_SECS
        return {
            "ok": True,
            "scenario": "loading_bay_rush",
            "robot": {"x": 8.0, "y": 20.0},
            "target": state["target"],
            "obstacle": {"x": 17.0, "y": 20.0},
        }

    elif body.scenario == "corridor_squeeze":
        # Robot in a narrow corridor section with obstacles on both sides and a
        # worker ahead.  Tests obstacle clearance + human proximity together.
        state["x"] = 20.0
        state["y"] = 7.0
        state["theta"] = 0.0
        state["target"] = {"x": 28.0, "y": 7.0, "max_speed": 0.5}
        state["speed"] = 0.5
        # Tight obstacles on both sides
        extra_obstacles.extend([
            {"x": 22.0, "y": 7.4, "r": 0.3},
            {"x": 22.0, "y": 6.6, "r": 0.3},
            {"x": 24.0, "y": 7.3, "r": 0.3},
            {"x": 24.0, "y": 6.7, "r": 0.3},
        ])
        # Worker at the end of the squeeze
        human_pos["x"] = 26.0
        human_pos["y"] = 7.0
        scenario_lock_until = time.time() + SCENARIO_LOCK_SECS
        return {
            "ok": True,
            "scenario": "corridor_squeeze",
            "robot": {"x": 20.0, "y": 7.0},
            "human": dict(human_pos),
            "extra_obstacles": 4,
        }

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown scenario: {body.scenario}. "
                   f"Valid: human_approach, human_too_close, path_blocked, clear, "
                   f"speed_violation, geofence_breach, low_confidence, "
                   f"multi_worker_congestion, loading_bay_rush, corridor_squeeze",
        )


# ---------------------------------------------------------------------------
# Scenario catalog & scripted sequences
# ---------------------------------------------------------------------------

SCENARIO_CATALOG = [
    {
        "id": "human_approach",
        "name": "Human Approaching",
        "description": "Place human ~2.5 m ahead of robot — triggers SLOW policy state",
        "policies_exercised": ["HUMAN_PROXIMITY_02"],
        "expected_state": "SLOW",
    },
    {
        "id": "human_too_close",
        "name": "Human Emergency Stop",
        "description": "Place human ~0.8 m ahead of robot — triggers full STOP",
        "policies_exercised": ["HUMAN_PROXIMITY_02"],
        "expected_state": "STOP",
    },
    {
        "id": "path_blocked",
        "name": "Path Blocked",
        "description": "Insert obstacle 1.5 m ahead — triggers REPLAN via OBSTACLE_CLEARANCE_03",
        "policies_exercised": ["OBSTACLE_CLEARANCE_03"],
        "expected_state": "REPLAN",
    },
    {
        "id": "speed_violation",
        "name": "Speed Violation in Loading Bay",
        "description": "Robot at 0.8 m/s in loading_bay (limit 0.4) — triggers SAFE_SPEED_01",
        "policies_exercised": ["SAFE_SPEED_01"],
        "expected_state": "SLOW",
    },
    {
        "id": "geofence_breach",
        "name": "Geofence Breach",
        "description": "Robot targets a point outside the geofence — triggers GEOFENCE_01",
        "policies_exercised": ["GEOFENCE_01"],
        "expected_state": "STOP",
    },
    {
        "id": "low_confidence",
        "name": "Low Perception Confidence",
        "description": "Human detected but confidence < 0.55 — triggers UNCERTAINTY_04",
        "policies_exercised": ["UNCERTAINTY_04", "HUMAN_PROXIMITY_02"],
        "expected_state": "SLOW",
    },
    {
        "id": "multi_worker_congestion",
        "name": "Worker Congestion",
        "description": "Three workers cluster around robot — multiple proximity hits",
        "policies_exercised": ["WORKER_PROXIMITY_06"],
        "expected_state": "STOP",
    },
    {
        "id": "loading_bay_rush",
        "name": "Loading Bay Rush",
        "description": "Busy bay with workers, obstacle, and excessive speed — multi-policy",
        "policies_exercised": ["SAFE_SPEED_01", "WORKER_PROXIMITY_06", "OBSTACLE_CLEARANCE_03"],
        "expected_state": "STOP",
    },
    {
        "id": "corridor_squeeze",
        "name": "Corridor Squeeze",
        "description": "Narrow passage with obstacles on both sides and a worker ahead",
        "policies_exercised": ["OBSTACLE_CLEARANCE_03", "HUMAN_PROXIMITY_02"],
        "expected_state": "STOP",
    },
    {
        "id": "clear",
        "name": "Reset / Clear",
        "description": "Reset human position, obstacles, and workers to defaults",
        "policies_exercised": [],
        "expected_state": "SAFE",
    },
]

SCRIPTED_SEQUENCES = {
    "governance_demo": {
        "name": "Governance Demo (5-step)",
        "description": "Walk through the five core governance reactions in order",
        "steps": [
            {"scenario": "clear", "hold_seconds": 2, "narration": "Start with a clean slate"},
            {"scenario": "human_approach", "hold_seconds": 5, "narration": "Human enters slow zone — speed reduced"},
            {"scenario": "human_too_close", "hold_seconds": 5, "narration": "Human enters stop zone — full halt"},
            {"scenario": "path_blocked", "hold_seconds": 5, "narration": "Obstacle injected — robot must replan"},
            {"scenario": "clear", "hold_seconds": 2, "narration": "Reset to safe operation"},
        ],
    },
    "policy_sweep": {
        "name": "Full Policy Sweep",
        "description": "Exercise every policy in the catalog sequentially",
        "steps": [
            {"scenario": "clear", "hold_seconds": 2, "narration": "Reset"},
            {"scenario": "speed_violation", "hold_seconds": 5, "narration": "Speed violation in loading bay"},
            {"scenario": "clear", "hold_seconds": 2, "narration": "Reset"},
            {"scenario": "geofence_breach", "hold_seconds": 5, "narration": "Geofence breach attempt"},
            {"scenario": "clear", "hold_seconds": 2, "narration": "Reset"},
            {"scenario": "low_confidence", "hold_seconds": 5, "narration": "Low perception confidence"},
            {"scenario": "clear", "hold_seconds": 2, "narration": "Reset"},
            {"scenario": "multi_worker_congestion", "hold_seconds": 5, "narration": "Worker congestion zone"},
            {"scenario": "clear", "hold_seconds": 2, "narration": "Reset"},
            {"scenario": "corridor_squeeze", "hold_seconds": 5, "narration": "Corridor squeeze — multi-policy"},
            {"scenario": "clear", "hold_seconds": 2, "narration": "Final reset"},
        ],
    },
    "stress_test": {
        "name": "Multi-Policy Stress Test",
        "description": "Rapidly trigger compound policy violations",
        "steps": [
            {"scenario": "clear", "hold_seconds": 1, "narration": "Reset"},
            {"scenario": "loading_bay_rush", "hold_seconds": 6, "narration": "Loading bay rush — 3 policies fire"},
            {"scenario": "clear", "hold_seconds": 1, "narration": "Reset"},
            {"scenario": "corridor_squeeze", "hold_seconds": 6, "narration": "Corridor squeeze — obstacle + human"},
            {"scenario": "clear", "hold_seconds": 1, "narration": "Reset"},
            {"scenario": "multi_worker_congestion", "hold_seconds": 6, "narration": "Worker congestion"},
            {"scenario": "clear", "hold_seconds": 1, "narration": "Final reset"},
        ],
    },
}


@app.get("/scenarios")
def list_scenarios(request: Request):
    """Return the full scenario catalog with metadata."""
    _require_sim_token(request)
    return {"scenarios": SCENARIO_CATALOG}


@app.get("/scenarios/sequences")
def list_sequences(request: Request):
    """Return available scripted scenario sequences."""
    _require_sim_token(request)
    return {
        "sequences": {
            k: {"name": v["name"], "description": v["description"], "step_count": len(v["steps"])}
            for k, v in SCRIPTED_SEQUENCES.items()
        }
    }


@app.get("/scenarios/sequences/{sequence_id}")
def get_sequence(request: Request, sequence_id: str):
    """Return the full step list for a scripted sequence."""
    _require_sim_token(request)
    seq = SCRIPTED_SEQUENCES.get(sequence_id)
    if not seq:
        raise HTTPException(status_code=404, detail=f"Unknown sequence: {sequence_id}")
    return seq


# ---------------------------------------------------------------------------
# Bezier path smoothing (#6)
# ---------------------------------------------------------------------------

def _quadratic_bezier(p0: Dict[str, float], p1: Dict[str, float], p2: Dict[str, float], t: float) -> Dict[str, float]:
    """Evaluate a quadratic Bezier curve at parameter t ∈ [0,1]."""
    u = 1 - t
    return {
        "x": u * u * p0["x"] + 2 * u * t * p1["x"] + t * t * p2["x"],
        "y": u * u * p0["y"] + 2 * u * t * p1["y"] + t * t * p2["y"],
    }


def _smooth_path(waypoints: List[Dict[str, float]], resolution: int = 20) -> List[Dict[str, float]]:
    """Generate a smooth path through waypoints using quadratic Bezier curves.

    For each pair of consecutive waypoints, we use the midpoints as
    on-curve points and the waypoints themselves as control points.
    The resulting path is C1 continuous and passes near all waypoints.
    """
    if len(waypoints) < 2:
        return waypoints

    if len(waypoints) == 2:
        # Simple linear interpolation
        pts = []
        for i in range(resolution + 1):
            t = i / resolution
            pts.append({
                "x": round(waypoints[0]["x"] + t * (waypoints[1]["x"] - waypoints[0]["x"]), 4),
                "y": round(waypoints[0]["y"] + t * (waypoints[1]["y"] - waypoints[0]["y"]), 4),
            })
        return pts

    # Compute midpoints between consecutive waypoints
    midpoints = []
    for i in range(len(waypoints) - 1):
        midpoints.append({
            "x": (waypoints[i]["x"] + waypoints[i + 1]["x"]) / 2,
            "y": (waypoints[i]["y"] + waypoints[i + 1]["y"]) / 2,
        })

    result = [{"x": round(waypoints[0]["x"], 4), "y": round(waypoints[0]["y"], 4)}]

    # First segment: from first waypoint to first midpoint, control = first waypoint
    for j in range(1, resolution + 1):
        t = j / resolution
        pt = _quadratic_bezier(waypoints[0], waypoints[0], midpoints[0], t)
        result.append({"x": round(pt["x"], 4), "y": round(pt["y"], 4)})

    # Middle segments: from midpoint[i-1] to midpoint[i], control = waypoint[i]
    for i in range(1, len(midpoints)):
        for j in range(1, resolution + 1):
            t = j / resolution
            pt = _quadratic_bezier(midpoints[i - 1], waypoints[i], midpoints[i], t)
            result.append({"x": round(pt["x"], 4), "y": round(pt["y"], 4)})

    # Last segment: from last midpoint to last waypoint
    last_mid = midpoints[-1]
    last_wp = waypoints[-1]
    for j in range(1, resolution + 1):
        t = j / resolution
        pt = _quadratic_bezier(last_mid, last_wp, last_wp, t)
        result.append({"x": round(pt["x"], 4), "y": round(pt["y"], 4)})

    return result


@app.post("/path/smooth")
def smooth_path(request: Request, body: PathSmoothRequest):
    """Generate a Bezier-smoothed path from waypoints (#6).

    Input: array of {x, y} waypoints.
    Output: dense array of smooth points following quadratic Bezier curves.
    """
    _require_sim_token(request)
    if len(body.waypoints) < 2:
        return {"waypoints": body.waypoints, "smoothed": body.waypoints, "count": len(body.waypoints)}

    smoothed = _smooth_path(body.waypoints, resolution=body.resolution)
    return {
        "waypoints": body.waypoints,
        "smoothed": smoothed,
        "count": len(smoothed),
        "resolution": body.resolution,
    }
