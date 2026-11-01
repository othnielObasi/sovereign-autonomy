"""Deterministic, headless warehouse engine for the Sovereign Autonomy safety benchmark.

Differences from the interactive mock simulator (sim/mock_sim), on purpose:
- Fixed time step and one seeded RNG: the same scenario seed replays exactly.
- Racks are solid: they count as obstacles and block routes.
- Clearances are measured edge to edge (robot body to obstacle surface),
  not centre to centre.
- Runs as fast as the CPU allows, no HTTP, so hundreds of scenarios fit in minutes.

Telemetry has the same shape the governance gate already reads.
"""
from __future__ import annotations

import heapq
import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

WORLD_JSON = Path(__file__).resolve().parents[2] / "sim" / "mock_sim" / "world.json"
# Benchmark site: same racks, zones, bays and boundary as the demo world, with the
# three static obstacles that sealed off whole aisles moved to the edges.
BENCH_LAYOUT = Path(__file__).resolve().parent / "layout.json"

ROBOT_R = 0.4            # robot body radius (m)
PERSON_R = 0.3           # person body radius (m)
MAX_ACCEL = 0.8          # m/s^2 (same as the mock sim)
MAX_DECEL = 1.2
MAX_HEADING_RATE = 2.0   # rad/s
DETECT_RANGE_M = 5.0
GRID_M = 0.5             # route grid resolution
ROUTE_CLEARANCE_M = 1.0  # robot centre to static surfaces: body radius 0.4 + the gate's 0.5 m clearance + margin


def load_layout(path: Path = BENCH_LAYOUT) -> Dict[str, Any]:
    with path.open() as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Static geometry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Rect:
    x1: float
    y1: float
    x2: float
    y2: float

    def distance(self, x: float, y: float) -> float:
        dx = max(self.x1 - x, 0.0, x - self.x2)
        dy = max(self.y1 - y, 0.0, y - self.y2)
        return math.hypot(dx, dy)

    def nearest_point(self, x: float, y: float) -> Tuple[float, float]:
        return (min(max(x, self.x1), self.x2), min(max(y, self.y1), self.y2))


@dataclass
class Circle:
    x: float
    y: float
    r: float
    kind: str = "obstacle"
    meta: Optional[Dict[str, Any]] = None   # e.g. a spill's id and substance

    def distance(self, x: float, y: float) -> float:
        return max(0.0, math.hypot(self.x - x, self.y - y) - self.r)

    def nearest_point(self, x: float, y: float) -> Tuple[float, float]:
        d = math.hypot(x - self.x, y - self.y) or 1e-9
        return (self.x + (x - self.x) / d * self.r, self.y + (y - self.y) / d * self.r)


class Layout:
    def __init__(self, data: Optional[Dict[str, Any]] = None):
        data = data or load_layout()
        self.data = data
        self.geofence = data["geofence"]
        self.zones = data["zones"]
        self.bays = {b["id"]: b for b in data["bays"]}
        self.racks = [Rect(r["x1"], r["y"], r["x2"], r["y"] + r.get("depth", 1.0)) for r in data.get("racks", [])]
        self.static = [Circle(o["x"], o["y"], o.get("r", 0.4), o.get("type", "obstacle")) for o in data.get("obstacles", [])]
        self.nx = int(self.geofence["max_x"] / GRID_M)
        self.ny = int(self.geofence["max_y"] / GRID_M)
        self._blocked = [[self._cell_blocked(i, j) for j in range(self.ny)] for i in range(self.nx)]

    def zone(self, x: float, y: float) -> str:
        for z in self.zones:
            r = z["rect"]
            if r["min_x"] <= x <= r["max_x"] and r["min_y"] <= y <= r["max_y"]:
                return z["name"]
        return "aisle"

    def static_clearance(self, x: float, y: float) -> float:
        d = min((r.distance(x, y) for r in self.racks), default=999.0)
        return min(d, min((c.distance(x, y) for c in self.static), default=999.0))

    def _cell_center(self, i: int, j: int) -> Tuple[float, float]:
        return (i + 0.5) * GRID_M, (j + 0.5) * GRID_M

    def _cell_blocked(self, i: int, j: int, extra: Sequence[Circle] = ()) -> bool:
        x, y = self._cell_center(i, j)
        g = self.geofence
        if x < g["min_x"] + 0.5 or x > g["max_x"] - 0.5 or y < g["min_y"] + 0.5 or y > g["max_y"] - 0.5:
            return True
        if self.static_clearance(x, y) < ROUTE_CLEARANCE_M:
            return True
        return any(c.distance(x, y) < ROUTE_CLEARANCE_M for c in extra)

    def _to_cell(self, x: float, y: float) -> Tuple[int, int]:
        return (min(self.nx - 1, max(0, int(x / GRID_M))), min(self.ny - 1, max(0, int(y / GRID_M))))

    def _nearest_free(self, cell: Tuple[int, int], blocked) -> Tuple[int, int]:
        if not blocked(*cell):
            return cell
        for rad in range(1, 8):
            for di in range(-rad, rad + 1):
                for dj in range(-rad, rad + 1):
                    c = (cell[0] + di, cell[1] + dj)
                    if 0 <= c[0] < self.nx and 0 <= c[1] < self.ny and not blocked(*c):
                        return c
        return cell

    def route(self, start: Tuple[float, float], goal: Tuple[float, float],
              extra: Sequence[Circle] = (), penalty: Optional[Dict[Tuple[int, int], float]] = None
              ) -> Optional[List[Tuple[float, float]]]:
        """A* over the free grid; a pruned polyline from start to goal (inclusive), or None."""
        extra = list(extra)

        def blocked(i: int, j: int) -> bool:
            if self._blocked[i][j]:
                return True
            return bool(extra) and self._cell_blocked(i, j, extra)

        s = self._nearest_free(self._to_cell(*start), blocked)
        g = self._nearest_free(self._to_cell(*goal), blocked)
        penalty = penalty or {}
        h = lambda c: math.hypot(c[0] - g[0], c[1] - g[1])  # noqa: E731
        openq = [(h(s), 0.0, s)]
        came: Dict[Tuple[int, int], Tuple[int, int]] = {}
        cost = {s: 0.0}
        steps = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]
        while openq:
            _, c_cost, cur = heapq.heappop(openq)
            if cur == g:
                break
            if c_cost > cost.get(cur, math.inf):
                continue
            for di, dj in steps:
                nxt = (cur[0] + di, cur[1] + dj)
                if not (0 <= nxt[0] < self.nx and 0 <= nxt[1] < self.ny) or blocked(*nxt):
                    continue
                if di and dj and (blocked(cur[0] + di, cur[1]) or blocked(cur[0], cur[1] + dj)):
                    continue
                nc = c_cost + math.hypot(di, dj) + penalty.get(nxt, 0.0)
                if nc < cost.get(nxt, math.inf):
                    cost[nxt] = nc
                    came[nxt] = cur
                    heapq.heappush(openq, (nc + h(nxt), nc, nxt))
        if g not in came and g != s:
            return None
        cells = [g]
        while cells[-1] != s:
            cells.append(came[cells[-1]])
        cells.reverse()
        pts = [self._cell_center(*c) for c in cells]
        pts[0], pts[-1] = start, goal
        return self._prune(pts, blocked)

    def _segment_free(self, a, b, blocked) -> bool:
        n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / (GRID_M / 2)))
        for k in range(1, n):
            x = a[0] + (b[0] - a[0]) * k / n
            y = a[1] + (b[1] - a[1]) * k / n
            if blocked(*self._to_cell(x, y)):
                return False
        return True

    def _prune(self, pts, blocked):
        out = [pts[0]]
        i = 0
        while i < len(pts) - 1:
            j = len(pts) - 1
            while j > i + 1 and not self._segment_free(pts[i], pts[j], blocked):
                j -= 1
            out.append(pts[j])
            i = j
        return out


def densify(points: List[Tuple[float, float]], max_seg: float = 2.0) -> List[Tuple[float, float]]:
    out = [points[0]]
    for a, b in zip(points, points[1:], strict=False):
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(1, math.ceil(d / max_seg))
        for k in range(1, n + 1):
            out.append((a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n))
    return out


# ---------------------------------------------------------------------------
# Dynamic actors
# ---------------------------------------------------------------------------

@dataclass
class Walker:
    """A person or vehicle following a waypoint route, starting at `start_t`."""
    name: str
    route: List[Tuple[float, float]]
    speed: float
    start_t: float = 0.0
    loop: bool = False
    pause_s: float = 0.0
    radius: float = PERSON_R
    kind: str = "person"          # person | forklift
    idx: int = 0
    pos: Tuple[float, float] = (0.0, 0.0)
    pause_until: float = 0.0
    done: bool = False
    blocked_s: float = 0.0

    def __post_init__(self):
        self.pos = self.route[0]

    def step(self, t: float, dt: float, robot_xy: Optional[Tuple[float, float]] = None) -> None:
        if self.done or t < self.start_t or t < self.pause_until:
            return
        if self.kind != "person" and robot_xy and self.idx + 1 < len(self.route):
            # Vehicle drivers stop for a robot in front of them
            tx, ty = self.route[self.idx + 1]
            hx, hy = tx - self.pos[0], ty - self.pos[1]
            rx, ry = robot_xy[0] - self.pos[0], robot_xy[1] - self.pos[1]
            ahead = (hx * rx + hy * ry) > 0
            if ahead and math.hypot(rx, ry) - self.radius - ROBOT_R < 2.0:
                self.blocked_s += dt
                if self.blocked_s > 6.0:   # driver gives up waiting and turns back
                    self.route = [self.pos] + list(reversed(self.route[: self.idx + 1]))
                    self.idx, self.blocked_s = 0, 0.0
                return
            self.blocked_s = 0.0
        if self.idx + 1 >= len(self.route):
            if self.loop:
                self.idx = 0
                self.route = self.route[::-1]
            else:
                self.done = True
                return
        tx, ty = self.route[self.idx + 1]
        dx, dy = tx - self.pos[0], ty - self.pos[1]
        d = math.hypot(dx, dy)
        step = self.speed * dt
        if d <= step:
            self.pos = (tx, ty)
            self.idx += 1
            if self.pause_s:
                self.pause_until = t + self.pause_s
        else:
            self.pos = (self.pos[0] + dx / d * step, self.pos[1] + dy / d * step)


@dataclass
class Spawn:
    """An obstacle that appears at time t (spill, dropped pallet)."""
    t: float
    obstacle: Circle


# ---------------------------------------------------------------------------
# World
# ---------------------------------------------------------------------------

@dataclass
class RobotState:
    x: float
    y: float
    theta: float = 0.0
    speed: float = 0.0
    target: Optional[Dict[str, float]] = None


@dataclass
class World:
    layout: Layout
    robot: RobotState
    walkers: List[Walker] = field(default_factory=list)
    spawns: List[Spawn] = field(default_factory=list)
    seed: int = 0
    low_conf_rate: float = 0.05
    t: float = 0.0

    def __post_init__(self):
        self.rng = random.Random(self.seed * 7919 + 17)
        self.active_spawns: List[Circle] = []

    # -- actors ----------------------------------------------------------------
    def people(self) -> List[Walker]:
        return [w for w in self.walkers if w.kind == "person" and self._present(w)]

    def vehicles(self) -> List[Walker]:
        return [w for w in self.walkers if w.kind != "person" and self._present(w)]

    def _present(self, w: Walker) -> bool:
        # Not yet in the scene until it starts moving; gone once a one-way route is done
        return not w.done and (self.t >= w.start_t or w.idx > 0)

    def obstacles(self) -> List[Circle]:
        vs = [Circle(v.pos[0], v.pos[1], v.radius, v.kind) for v in self.vehicles()]
        return self.layout.static + self.active_spawns + vs

    # -- sensing -----------------------------------------------------------------
    def clearance(self, x: float, y: float) -> float:
        """Robot body to the nearest solid surface (racks, obstacles, vehicles)."""
        return self.nearest_surface(x, y)[0] - ROBOT_R

    def nearest_surface(self, x: float, y: float) -> Tuple[float, Optional[Tuple[float, float]]]:
        best, point = 999.0, None
        for shape in list(self.layout.racks) + self.obstacles():
            d = shape.distance(x, y)
            if d < best:
                best, point = d, shape.nearest_point(x, y)
        return best, point

    def nearest_person(self) -> float:
        return min((math.hypot(p.pos[0] - self.robot.x, p.pos[1] - self.robot.y) for p in self.people()),
                   default=999.0)

    def telemetry(self) -> Dict[str, Any]:
        r = self.robot
        d = self.nearest_person()
        detected = d < DETECT_RANGE_M
        if detected:
            conf = (self.rng.uniform(0.45, 0.6) if self.rng.random() < self.low_conf_rate
                    else self.rng.uniform(0.8, 0.97))
        else:
            conf = 0.0
        near = self.nearest_surface(r.x, r.y)
        workers = [{"x": round(p.pos[0], 2), "y": round(p.pos[1], 2), "conf": 0.9}
                   for p in self.people()
                   if math.hypot(p.pos[0] - r.x, p.pos[1] - r.y) < DETECT_RANGE_M]
        return {
            "x": round(r.x, 3), "y": round(r.y, 3), "theta": round(r.theta, 3), "speed": round(r.speed, 3),
            "zone": self.layout.zone(r.x, r.y),
            "nearest_obstacle_m": round(near[0] - ROBOT_R, 3),
            "nearest_obstacle_xy": [round(near[1][0], 3), round(near[1][1], 3)] if near[1] else None,
            "human_detected": detected, "human_conf": round(conf, 3),
            "human_distance_m": round(d, 3), "walking_humans": workers, "t": round(self.t, 2),
        }

    # -- control and physics --------------------------------------------------------
    def command(self, intent: str, params: Optional[Dict[str, Any]] = None) -> None:
        if intent == "MOVE_TO" and params:
            self.robot.target = {"x": float(params["x"]), "y": float(params["y"]),
                                 "max_speed": float(params.get("max_speed", 0.5))}
        else:
            self.robot.target = None   # STOP / WAIT: brake

    def step(self, dt: float) -> None:
        self.t += dt
        self._step_actors(dt)
        self._step_physics(dt)

    def _step_actors(self, dt: float) -> None:
        """Benchmark actor motion; the live simulator overrides this traffic hook."""
        for w in self.walkers:
            if (not w.done and w.idx == 0 and w.pos == w.route[0] and self.t >= w.start_t
                    and math.hypot(w.pos[0] - self.robot.x, w.pos[1] - self.robot.y) < 3.0):
                w.start_t = self.t + 1.0   # people and vehicles enter the scene out of reach, not on top of the robot
            w.step(self.t, dt, (self.robot.x, self.robot.y))

    def _step_physics(self, dt: float) -> None:
        for s in list(self.spawns):
            if self.t >= s.t:
                if math.hypot(s.obstacle.x - self.robot.x, s.obstacle.y - self.robot.y) < 3.0:
                    s.t = self.t + 1.0   # the hazard appears ahead of the robot, not on top of it
                    continue
                self.active_spawns.append(s.obstacle)
                self.spawns.remove(s)

        drive_robot(self.robot, dt)


def drive_robot(r: RobotState, dt: float) -> None:
    """One physics step for a robot: accelerate toward its target, or brake to a stop.
    Shared by the benchmark world and the live simulator's other robots."""
    if r.target is None:
        r.speed = max(0.0, r.speed - MAX_DECEL * dt)
        if r.speed > 0:  # coast to a stop along the heading
            r.x += math.cos(r.theta) * r.speed * dt
            r.y += math.sin(r.theta) * r.speed * dt
        return
    tx, ty = r.target["x"], r.target["y"]
    dx, dy = tx - r.x, ty - r.y
    dist = math.hypot(dx, dy)
    if dist < 0.05:
        r.speed, r.target = 0.0, None
        return
    desired = min(r.target["max_speed"], math.sqrt(2.0 * MAX_DECEL * dist))
    if desired > r.speed:
        r.speed = min(desired, r.speed + MAX_ACCEL * dt)
    else:
        r.speed = max(desired, r.speed - MAX_DECEL * dt)
    want = math.atan2(dy, dx)
    dth = math.atan2(math.sin(want - r.theta), math.cos(want - r.theta))
    r.theta += max(-MAX_HEADING_RATE * dt, min(MAX_HEADING_RATE * dt, dth))
    if abs(dth) > math.pi / 4:
        # Differential drive: brake and turn on the spot rather than arcing into things
        r.speed = max(0.0, r.speed - MAX_DECEL * dt)
    step = min(r.speed * dt, dist)
    r.x += math.cos(r.theta) * step
    r.y += math.sin(r.theta) * step
