"""Seeded hazard scenarios.

People in a real warehouse cross at the same places — cross-aisles, the main
corridor, dock doors, packing stations — so hazards are placed at site
hotspots on the robot's route, with seeded variation in who, when and how fast.
That is also what makes learning transferable: a lesson about a hotspot learned
on one seed applies to a different seed at the same place.

Difficulty (seed % 3): easy = background workers only plus one crossing;
medium = two to three crossings and a forklift on the corridor;
hard = crossings timed close to the robot, a forklift, a mid-run spill or
dropped pallet on the route, and more sensor noise.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from bench.world import Circle, Layout, RobotState, Spawn, Walker, World, densify

# Places where people and vehicles cross robot routes
HOTSPOTS: List[Tuple[float, float]] = [
    (12.5, 3.5), (25.5, 3.5), (12.5, 7.5), (25.5, 7.5),      # cross-aisle intersections
    (12.5, 13.5), (25.5, 13.5), (6.0, 13.5), (34.0, 13.5),   # main corridor
    (8.0, 17.0), (16.0, 17.0),                               # packing stations
    (10.0, 21.0), (22.0, 21.0), (31.0, 21.0),                # dock doors
]
DIFFICULTIES = ("easy", "medium", "hard")
NOMINAL_SPEED = 0.5   # used only to estimate when the robot reaches a point on its route


@dataclass
class Scenario:
    seed: int
    difficulty: str
    start_bay: str
    goal_bay: str
    start: Tuple[float, float]
    goal: Tuple[float, float]
    route: List[Tuple[float, float]]
    walkers: List[Walker] = field(default_factory=list)
    spawns: List[Spawn] = field(default_factory=list)
    low_conf_rate: float = 0.05
    time_limit_s: float = 240.0
    hotspots_on_route: List[Tuple[float, float]] = field(default_factory=list)

    def build_world(self, layout: Layout) -> World:
        import copy
        return World(layout=layout, robot=RobotState(*self.start), walkers=copy.deepcopy(self.walkers),
                     spawns=copy.deepcopy(self.spawns), seed=self.seed, low_conf_rate=self.low_conf_rate)

    def summary(self) -> Dict[str, Any]:
        return {"seed": self.seed, "difficulty": self.difficulty, "from": self.start_bay, "to": self.goal_bay,
                "people": sum(w.kind == "person" for w in self.walkers),
                "vehicles": sum(w.kind != "person" for w in self.walkers),
                "spawns": len(self.spawns), "hotspots_on_route": len(self.hotspots_on_route)}


def _arrival_time(route: List[Tuple[float, float]], point: Tuple[float, float]) -> Tuple[float, int]:
    """Estimated time (at NOMINAL_SPEED) the robot passes nearest `point`, and the segment index."""
    best, best_t, best_i, travelled = math.inf, 0.0, 0, 0.0
    for i, (a, b) in enumerate(zip(route, route[1:], strict=False)):
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        for k in range(11):
            x, y = a[0] + (b[0] - a[0]) * k / 10, a[1] + (b[1] - a[1]) * k / 10
            d = math.hypot(x - point[0], y - point[1])
            if d < best:
                best, best_t, best_i = d, (travelled + seg * k / 10) / NOMINAL_SPEED, i
        travelled += seg
    return best_t, best_i


def _dist_to_route(route, p) -> float:
    best = math.inf
    for a, b in zip(route, route[1:], strict=False):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy or 1e-9
        t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
        best = min(best, math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy)))
    return best


def _crossing(rng: random.Random, layout: Layout, route, hotspot, t_robot: float, seg_i: int,
              spread: float, name: str) -> Walker:
    """A person who walks across the robot's route near `hotspot`, timed near the robot's arrival."""
    a, b = route[seg_i], route[min(seg_i + 1, len(route) - 1)]
    ang = math.atan2(b[1] - a[1], b[0] - a[0]) + math.pi / 2  # perpendicular to the robot's heading
    side = rng.choice((-1, 1))
    reach = rng.uniform(3.0, 4.5)
    hx, hy = hotspot[0] + rng.uniform(-0.6, 0.6), hotspot[1] + rng.uniform(-0.6, 0.6)
    p0 = (hx + side * math.cos(ang) * reach, hy + side * math.sin(ang) * reach)
    p1 = (hx - side * math.cos(ang) * reach, hy - side * math.sin(ang) * reach)
    g = layout.geofence
    clamp = lambda p: (min(g["max_x"] - 0.3, max(0.3, p[0])), min(g["max_y"] - 0.3, max(0.3, p[1])))  # noqa: E731
    speed = rng.uniform(0.8, 1.3)
    start_t = max(0.0, t_robot - reach / speed + rng.gauss(0.0, spread))
    return Walker(name, [clamp(p0), clamp(p1)], speed, start_t=start_t, pause_s=rng.choice((0.0, 0.0, 2.0)))


def _patroller(rng: random.Random, layout: Layout, name: str) -> Walker:
    a, b = rng.sample(list(layout.bays.values()), 2)
    path = layout.route((a["x"], a["y"]), (b["x"], b["y"])) or [(a["x"], a["y"]), (b["x"], b["y"])]
    return Walker(name, path, rng.uniform(0.6, 1.1), start_t=rng.uniform(0, 30), loop=True,
                  pause_s=rng.uniform(1.0, 4.0))


def generate(seed: int, layout: Layout, difficulty: Optional[str] = None) -> Scenario:
    rng = random.Random(seed)
    difficulty = difficulty or DIFFICULTIES[seed % 3]
    bays = list(layout.bays)
    while True:
        s_id, g_id = rng.sample(bays, 2)
        s = (layout.bays[s_id]["x"], layout.bays[s_id]["y"])
        g = (layout.bays[g_id]["x"], layout.bays[g_id]["y"])
        if math.hypot(g[0] - s[0], g[1] - s[1]) < 8:
            continue
        route = layout.route(s, g)
        if route:
            break
    dense = densify(route, 1.0)
    on_route = sorted({h for h in HOTSPOTS if _dist_to_route(dense, h) < 2.0},
                      key=lambda h: _arrival_time(dense, h)[0])
    if not on_route:  # always at least one crossing: the midpoint of the route
        on_route = [dense[len(dense) // 2]]

    n_cross = {"easy": 1, "medium": rng.randint(2, 3), "hard": rng.randint(3, 4)}[difficulty]
    spread = {"easy": 6.0, "medium": 4.0, "hard": 1.5}[difficulty]
    walkers: List[Walker] = []
    for k in range(n_cross):
        hs = on_route[k % len(on_route)]
        t_arr, seg = _arrival_time(dense, hs)
        walkers.append(_crossing(rng, layout, dense, hs, t_arr + k * rng.uniform(0, 3), seg, spread, f"crosser-{k}"))
    for k in range(rng.randint(1, 3)):
        walkers.append(_patroller(rng, layout, f"worker-{k}"))

    if difficulty in ("medium", "hard"):
        fy = 13.5
        x0, x1 = (2.0, 38.0) if rng.random() < 0.5 else (38.0, 2.0)
        walkers.append(Walker("forklift", [(x0, fy), (x1, fy)], rng.uniform(1.2, 1.8), start_t=rng.uniform(0, 20),
                              loop=True, pause_s=3.0, radius=1.0, kind="forklift"))

    spawns: List[Spawn] = []
    if difficulty == "hard":
        i = rng.randint(len(dense) // 3, max(len(dense) // 3, 2 * len(dense) // 3))
        px, py = dense[i]
        t_arr, _ = _arrival_time(dense, (px, py))
        spawns.append(Spawn(max(1.0, t_arr - rng.uniform(3, 8)),
                            Circle(px + rng.uniform(-0.3, 0.3), py + rng.uniform(-0.3, 0.3), rng.uniform(0.35, 0.6),
                                   rng.choice(("spill", "dropped_pallet")))))

    length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(route, route[1:], strict=False))
    return Scenario(
        seed=seed, difficulty=difficulty, start_bay=s_id, goal_bay=g_id, start=s, goal=g, route=route,
        walkers=walkers, spawns=spawns, low_conf_rate={"easy": 0.03, "medium": 0.05, "hard": 0.1}[difficulty],
        time_limit_s=max(120.0, length / 0.25 + 60.0), hotspots_on_route=on_route,
    )
