"""Layout-aware traffic for the interactive site, separate from benchmark actors.

Furniture dimensions match Actors.tsx. Pedestrians work between destinations,
yield before entering vehicle traffic, and detour around blocked walking space.
Movement is checked over the whole tick, not just at its endpoint.
"""
from __future__ import annotations

import copy
import math
from typing import Sequence

from bench.world import Circle, GRID_M, Layout, ROBOT_R, Walker, World

# Actors.tsx extends from -1.245 m behind the origin to +1.8 m at
# the fork tips, and 0.61 m sideways: a 1.9 m disk encloses the model.
FORKLIFT_RADIUS = 1.9


def segment_distance(a, b, point):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = dx * dx + dy * dy
    t = max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length)) if length else 0.0
    return math.hypot(a[0] + t * dx - point[0], a[1] + t * dy - point[1])


def furniture_racks(data):
    """Navigation rectangles only; these must never be rendered as storage racks."""
    out = []
    for f in data.get("features", []):
        x, y = f["x"], f["y"]
        if f["type"] == "packing_station":
            out.append({"x1": x - 0.9, "x2": x + 0.9, "y": y + 0.25, "depth": 0.6})
        elif f["type"] == "charging_station":
            out.append({"x1": x - 0.25, "x2": x + 0.25, "y": y + 0.66, "depth": 0.18})
    return out


class ActorNavigation(Layout):
    def __init__(self, data, clearance=0.45):
        self.clearance = clearance
        nav_data = copy.deepcopy(data)
        nav_data["racks"] = nav_data.get("racks", []) + furniture_racks(data)
        super().__init__(nav_data)
        self.free_points = [self._cell_center(i, j) for i in range(self.nx) for j in range(self.ny) if not self._blocked[i][j]]

    def _cell_blocked(self, i, j, extra=()):
        return not self.walkable(self._cell_center(i, j), extra)

    def walkable(self, point, extra=()):
        x, y = point
        g, c = self.geofence, self.clearance
        return (g["min_x"] + c <= x <= g["max_x"] - c and g["min_y"] + c <= y <= g["max_y"] - c
                and self.static_clearance(x, y) >= c - 1e-8
                and all(ob.distance(x, y) >= c - 1e-8 for ob in extra))

    def segment_clear(self, a, b, extra=()):
        steps = max(1, math.ceil(math.dist(a, b) / 0.05))
        return all(self.walkable((a[0] + (b[0] - a[0]) * k / steps,
                                  a[1] + (b[1] - a[1]) * k / steps), extra) for k in range(steps + 1))

    def _segment_free(self, a, b, blocked):
        steps = max(1, math.ceil(math.dist(a, b) / 0.05))
        for k in range(steps + 1):
            point = (a[0] + (b[0] - a[0]) * k / steps, a[1] + (b[1] - a[1]) * k / steps)
            if blocked(*self._to_cell(*point)) or not self.walkable(point, getattr(self, "_routing_extra", ())):
                return False
        return True

    def safe_point(self, point, extra=()):
        return min((p for p in self.free_points if self.walkable(p, extra)), key=lambda p: math.dist(point, p), default=None)

    def _anchor(self, point, extra):
        candidates = sorted(self.free_points, key=lambda p: math.dist(point, p))
        return next((p for p in candidates[:64] if self.segment_clear(point, p, extra)), None)

    def route(self, start, goal, extra: Sequence[Circle] = (), penalty=None):
        if not self.walkable(start, extra):
            return None  # a route must not teleport a moving actor out of a collision
        if not self.walkable(goal, extra):
            goal = self.safe_point(goal, extra)
        if goal is None:
            return None
        a, b = self._anchor(start, extra), self._anchor(goal, extra)
        if a is None or b is None:
            return None
        # Navigation calls are serialized by the live world's lock.
        self._routing_extra = extra
        try:
            middle = super().route(a, b, extra=extra, penalty=penalty)
        finally:
            self._routing_extra = ()
        if not middle:
            return None
        points = [start]
        for p in [*middle, goal]:
            if math.dist(points[-1], p) > 1e-8:
                points.append(p)
        return points if all(self.segment_clear(a, b, extra) for a, b in zip(points, points[1:])) else None


class TrafficWorld(World):
    def __post_init__(self):
        super().__post_init__()
        self.pedestrian_nav = ActorNavigation(self.layout.data, 0.45)
        self.vehicle_nav = ActorNavigation(self.layout.data, FORKLIFT_RADIUS + 0.12)

    def _direction(self, actor):
        if actor.idx + 1 < len(actor.route):
            dx, dy = actor.route[actor.idx + 1][0] - actor.pos[0], actor.route[actor.idx + 1][1] - actor.pos[1]
            d = math.hypot(dx, dy)
            if d > 1e-8:
                return dx / d, dy / d
        return math.cos(getattr(actor, "heading", 0)), math.sin(getattr(actor, "heading", 0))

    def _yield_to_vehicle(self, person, candidate):
        for vehicle in self.vehicles():
            direction = self._direction(vehicle)
            offset = (person.pos[0] - vehicle.pos[0], person.pos[1] - vehicle.pos[1])
            along = offset[0] * direction[0] + offset[1] * direction[1]
            lateral = abs(offset[0] * direction[1] - offset[1] * direction[0])
            # Someone already crossing clears the lane; the driver waits for them.
            if -vehicle.radius <= along <= 5 and lateral < vehicle.radius + person.radius + 0.25:
                continue
            if self.t < vehicle.pause_until:
                continue
            future = (vehicle.pos[0] + direction[0] * vehicle.speed * 2.5,
                      vehicle.pos[1] + direction[1] * vehicle.speed * 2.5)
            if segment_distance(vehicle.pos, future, candidate) < vehicle.radius + person.radius + 0.65:
                return True
        return False

    def _replan(self, actor, extra):
        if self.t < getattr(actor, "replan_after", 0):
            return
        actor.replan_after = self.t + 2.0
        nav = self.pedestrian_nav if actor.kind == "person" else self.vehicle_nav
        goal = actor.route[-1]
        path = nav.route(actor.pos, goal, extra)
        if actor.activity in ("waiting_for_person", "waiting_for_forklift"):
            dx, dy = goal[0] - actor.pos[0], goal[1] - actor.pos[1]
            distance = math.hypot(dx, dy)
            if distance > 0.1:
                # Pass on one's own right: opposing walkers choose opposite sides.
                side = (actor.pos[0] + dy / distance + dx / distance * 0.3,
                        actor.pos[1] - dx / distance + dy / distance * 0.3)
                first, second = nav.route(actor.pos, side, extra), nav.route(side, goal, extra)
                if first and second:
                    path = first + second[1:]
        if path and len(path) > 1:
            # Retain the original task's start when the loop reverses at its end.
            actor.route = [actor.route[0], *path]
            actor.idx = 1
            actor.pause_until = self.t

    def _step_actors(self, dt):
        sweeps = {}
        actors = sorted(self.walkers, key=lambda w: (w.kind == "person", w.name))
        for actor in actors:
            if actor.kind == "forklift":
                actor.radius = max(actor.radius, FORKLIFT_RADIUS)
        for actor in actors:
            actor.actual_speed = 0.0
            actor.activity = "waiting_to_start"
            if actor.done or self.t < actor.start_t:
                continue
            nav = self.pedestrian_nav if actor.kind == "person" else self.vehicle_nav
            if not getattr(actor, "navigation_ready", False):
                # Initial placement is allowed to snap to open floor. Later ticks never teleport.
                start = actor.pos if nav.walkable(actor.pos) else nav.safe_point(actor.pos)
                path = nav.route(start, actor.route[-1]) if start else None
                if not path:
                    actor.activity = "no_walkable_route"
                    continue
                actor.pos, actor.route, actor.idx = start, path, 0
                actor.navigation_ready = True
            if self.t < actor.pause_until:
                actor.activity = getattr(actor, "pause_activity", "working" if actor.kind == "person" else "loading")
                continue
            if len(actor.route) < 2:
                actor.activity = "standing"
                continue
            previous = vars(actor).copy()
            origin = actor.pos
            actor.step(self.t, dt, (self.robot.x, self.robot.y))
            candidate = actor.pos
            # Work pauses happen at destinations, not at every navigation corner.
            if actor.idx < len(actor.route) - 1:
                actor.pause_until = 0.0
            reason = None
            static = self.active_spawns
            if not nav.segment_clear(origin, candidate, static):
                reason = "blocked_by_obstacle"
            if not reason and actor.kind != "person":
                direction = self._direction(actor)
                for person in self.people():
                    offset = (person.pos[0] - origin[0], person.pos[1] - origin[1])
                    along = offset[0] * direction[0] + offset[1] * direction[1]
                    lateral = abs(offset[0] * direction[1] - offset[1] * direction[0])
                    if 0 < along < actor.radius + person.radius + 0.6 + actor.speed * 1.2 and lateral < actor.radius + person.radius + 0.25:
                        reason = "waiting_for_person"
                        break
            if not reason and actor.kind == "person" and self._yield_to_vehicle_proxy(actor, origin, candidate):
                reason = "waiting_for_forklift"
            if not reason:
                margin = 0.02 if actor.name == "Injected worker" else 0.15
                if segment_distance(origin, candidate, (self.robot.x, self.robot.y)) < actor.radius + ROBOT_R + margin:
                    reason = "waiting_for_robot"
            for other in actors:
                if reason or other is actor or not self._present(other):
                    continue
                a, b = sweeps.get(id(other), (other.pos, other.pos))
                relative_start = (origin[0] - a[0], origin[1] - a[1])
                relative_end = (candidate[0] - b[0], candidate[1] - b[1])
                if segment_distance(relative_start, relative_end, (0, 0)) < actor.radius + other.radius + 0.12:
                    reason = "waiting_for_person" if other.kind == "person" else "waiting_for_forklift"
            if reason:
                vars(actor).update(previous)
                actor.activity = reason
                actor.traffic_wait_s = getattr(actor, "traffic_wait_s", 0) + dt
                stopped_traffic = all(getattr(v, "actual_speed", 0) < 0.05 for v in self.vehicles())
                if actor.kind == "person" and actor.traffic_wait_s >= 1.5 and (reason != "waiting_for_forklift" or stopped_traffic):
                    extra = [*static, Circle(self.robot.x, self.robot.y, ROBOT_R)]
                    extra += [Circle(o.pos[0], o.pos[1], o.radius) for o in actors if o is not actor and self._present(o)]
                    self._replan(actor, extra)
            else:
                moved = math.dist(origin, candidate)
                actor.actual_speed = moved / dt if dt else 0
                if moved > 1e-8:
                    actor.heading = math.atan2(candidate[1] - origin[1], candidate[0] - origin[0])
                actor.activity = ("walking" if actor.kind == "person" else "driving") if moved else (
                    "working" if actor.kind == "person" else "loading")
                actor.traffic_wait_s = 0.0
            sweeps[id(actor)] = (origin, actor.pos)

    def _yield_to_vehicle_proxy(self, actor, origin, candidate):
        # Predict from the pre-step position; actor.step has already proposed a move.
        actor.pos = origin
        try:
            return self._yield_to_vehicle(actor, candidate)
        finally:
            actor.pos = candidate
