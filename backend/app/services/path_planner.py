from __future__ import annotations

"""Lightweight path planner for run preview and obstacle avoidance.

Uses simple computational-geometry helpers (segment–point distance,
line–circle intersection) to decide whether a straight-line path is
clear.  If an obstacle blocks the straight line, one detour waypoint
is added around it.  Intentionally kept simple for hackathon scope.
"""

import math
from typing import Dict, List, Tuple, Any


def _dist(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _segment_point_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    """Distance from point P to segment AB."""
    abx, aby = bx - ax, by - ay
    apx, apy = px - ax, py - ay
    ab2 = abx * abx + aby * aby
    if ab2 <= 1e-9:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, (apx * abx + apy * aby) / ab2))
    cx, cy = ax + t * abx, ay + t * aby
    return math.hypot(px - cx, py - cy)


def _line_hits_circle(a: Tuple[float, float], b: Tuple[float, float], c: Tuple[float, float], r: float) -> bool:
    return _segment_point_distance(c[0], c[1], a[0], a[1], b[0], b[1]) <= r


def plan_path(
    start: Dict[str, float],
    goal: Dict[str, float],
    obstacles: List[Dict[str, Any]],
    clearance_m: float = 0.75,
) -> Tuple[List[Dict[str, float]], str]:
    """Return a lightweight path preview polyline.

    This is intentionally simple for hackathon use:
    - Start with a straight line.
    - If it intersects an obstacle (circle), add one detour waypoint around it.

    Obstacles accepted:
      - {"x":..,"y":..,"r":..}  (circle)
      - {"x":..,"y":..} (point; treated as small circle)
    """
    sx, sy = float(start.get("x", 0.0)), float(start.get("y", 0.0))
    gx, gy = float(goal.get("x", 0.0)), float(goal.get("y", 0.0))

    a = (sx, sy)
    b = (gx, gy)

    # Find first blocking obstacle
    blocking = None
    for ob in obstacles or []:
        ox, oy = float(ob.get("x", 0.0)), float(ob.get("y", 0.0))
        r = float(ob.get("r", ob.get("radius", 0.4)))
        if _line_hits_circle(a, b, (ox, oy), r + clearance_m):
            blocking = (ox, oy, r)
            break

    if not blocking:
        return ([{"x": sx, "y": sy}, {"x": gx, "y": gy}], "straight")

    ox, oy, r = blocking
    # Compute a perpendicular detour point.
    dx, dy = gx - sx, gy - sy
    norm = math.hypot(dx, dy) or 1.0
    ux, uy = dx / norm, dy / norm
    # perpendicular
    px, py = -uy, ux

    # Choose detour direction that increases distance from obstacle
    # Try both sides, pick safer
    detour_dist = r + clearance_m + 1.0
    c1 = (ox + px * detour_dist, oy + py * detour_dist)
    c2 = (ox - px * detour_dist, oy - py * detour_dist)

    # pick candidate with larger min distance to obstacle along segments
    def score(c):
        d1 = _segment_point_distance(ox, oy, sx, sy, c[0], c[1])
        d2 = _segment_point_distance(ox, oy, c[0], c[1], gx, gy)
        return min(d1, d2)

    c = c1 if score(c1) >= score(c2) else c2

    return (
        [
            {"x": sx, "y": sy},
            {"x": float(c[0]), "y": float(c[1])},
            {"x": gx, "y": gy},
        ],
        "detour",
    )
