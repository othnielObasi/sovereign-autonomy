"""Aisle-aware routing for live runs (the same router the safety benchmark uses).

Without a model plan the live system used to head straight for the goal, which
runs through racking. This routes along aisles and cross-aisles instead, and
repairs any leg of a model's plan that would cut through racking, keeping the
model's waypoints as via-points.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
from typing import Any, Dict, List, Optional, Tuple

from app.policies.site_map import _racks_from_world, path_blocked

logger = logging.getLogger("app.site_router")

_cache: Dict[str, Any] = {}

Waypoint = Dict[str, float]


def _layout(world: Dict[str, Any]):
    from bench.world import Layout

    if not world or not world.get("racks"):
        return None
    static = [o for o in world.get("obstacles") or [] if o.get("type") not in ("forklift",)]
    data = {"geofence": world["geofence"], "zones": world.get("zones") or [], "bays": world.get("bays") or [],
            "racks": world["racks"], "obstacles": static}
    key = hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:16]
    if key not in _cache:
        if len(_cache) > 8:
            _cache.clear()
        _cache[key] = Layout(data)
    return _cache[key]


def hazard_circles(zones: Optional[List[Dict[str, Any]]]):
    """Exclusion zones as router obstacles: path centres stay >= radius + 0.3 m away
    (the router already keeps ROUTE_CLEARANCE_M from every obstacle edge)."""
    from bench.world import ROUTE_CLEARANCE_M, Circle

    out = []
    for z in zones or []:
        try:
            out.append(Circle(float(z["x"]), float(z["y"]), max(0.1, float(z["radius"]) + 0.3 - ROUTE_CLEARANCE_M), "hazard_zone"))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def capped_speed(x: float, y: float, speed: float, zones: Optional[List[Dict[str, Any]]]) -> float:
    for z in zones or []:
        try:
            if math.hypot(x - float(z["x"]), y - float(z["y"])) < float(z["slow_radius"]):
                speed = min(speed, float(z["max_speed"]))
        except (KeyError, TypeError, ValueError):
            continue
    return speed


def route_plan(world: Dict[str, Any], start: Dict[str, Any], goal: Dict[str, Any],
               speed_limits: Dict[str, float], avoid: Optional[Dict[str, Any]] = None,
               max_speed: float = 0.5, hazards: Optional[List[Dict[str, Any]]] = None) -> Optional[List[Waypoint]]:
    """Waypoints along the aisles from start to goal, each at its zone's limit; None if no route.
    `hazards` are site exclusion zones to route around (and slow down near)."""
    from bench.world import Circle, densify

    layout = _layout(world)
    if layout is None:
        return None
    extra = [Circle(float(avoid["x"]), float(avoid["y"]), 0.8, "blocked")] if avoid else []
    extra += hazard_circles(hazards)
    route = layout.route((float(start["x"]), float(start["y"])), (float(goal["x"]), float(goal["y"])), extra=extra)
    if not route:
        return None
    wps = []
    for x, y in densify(route, 2.0)[1:]:
        limit = float(speed_limits.get(layout.zone(x, y), 0.5))
        speed = capped_speed(x, y, min(limit, max_speed), hazards)
        wps.append({"x": round(x, 3), "y": round(y, 3), "max_speed": round(speed, 3)})
    return wps


def repair_plan(world: Dict[str, Any], start: Dict[str, Any], waypoints: List[Waypoint],
                speed_limits: Dict[str, float]) -> Tuple[List[Waypoint], int]:
    """Re-route any leg that runs through racking; keeps every original waypoint as a via-point."""
    racks = _racks_from_world(world or {})
    if not racks or not waypoints:
        return waypoints, 0
    out: List[Waypoint] = []
    repaired = 0
    prev = {"x": float(start["x"]), "y": float(start["y"])}
    for wp in waypoints:
        if path_blocked(prev["x"], prev["y"], float(wp["x"]), float(wp["y"]), racks):
            leg = route_plan(world, prev, wp, speed_limits, max_speed=float(wp.get("max_speed", 0.5)))
            if leg:
                out.extend(leg[:-1])
                repaired += 1
        out.append(wp)
        prev = wp
    return out, repaired


def distance(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    return math.hypot(float(a["x"]) - float(b["x"]), float(a["y"]) - float(b["y"]))


def crosses_hazard(start: Dict[str, Any], waypoints: List[Waypoint], zones: Optional[List[Dict[str, Any]]]) -> bool:
    """True if any leg of the plan passes through an exclusion zone."""
    from app.policies.rules_python import _segment_distance

    prev = (float(start["x"]), float(start["y"]))
    for wp in waypoints or []:
        cur = (float(wp["x"]), float(wp["y"]))
        for z in zones or []:
            try:
                if _segment_distance(float(z["x"]), float(z["y"]), *prev, *cur) < float(z["radius"]):
                    return True
            except (KeyError, TypeError, ValueError):
                continue
        prev = cur
    return False


def hazard_exit_point(world: Dict[str, Any], x: float, y: float, zone: Dict[str, Any], margin: float = 0.5):
    """Nearest point just outside `zone` reachable in a straight line that moves away
    from its centre and doesn't cross racking; None if there is none."""
    racks = _racks_from_world(world or {})
    g = (world or {}).get("geofence") or {"min_x": 0, "max_x": 40, "min_y": 0, "max_y": 25}
    cx, cy, r = float(zone["x"]), float(zone["y"]), float(zone["radius"])
    ax, ay = x - cx, y - cy
    n = math.hypot(ax, ay) or 1e-9
    dirs = [(ax / n, ay / n), (1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0)]
    best = None
    for dx, dy in dirs:
        if dx * ax + dy * ay <= 0:          # must move away from the centre
            continue
        # smallest t with |p - c| >= r + margin, p = (x, y) + t * d
        b = dx * ax + dy * ay
        c = ax * ax + ay * ay - (r + margin) ** 2
        t = -b + math.sqrt(max(0.0, b * b - c))
        px, py = x + dx * t, y + dy * t
        if not (g["min_x"] + 0.5 <= px <= g["max_x"] - 0.5 and g["min_y"] + 0.5 <= py <= g["max_y"] - 0.5):
            continue
        if racks and path_blocked(x, y, px, py, racks):
            continue
        if best is None or t < best[0]:
            best = (t, px, py)
    return (round(best[1], 3), round(best[2], 3)) if best else None
