"""Slow retreat: the one move allowed when the robot is already too close to an obstacle.

Found by the safety benchmark: the obstacle-clearance rule refused every move once
the robot was within the minimum clearance, including moving away. A robot that
ended up close to something (for example a forklift whose driver stopped for it)
could never leave, and both waited forever. The exception is narrow: the move must
point within 60 degrees of straight away from the nearest obstacle, at no more
than 0.3 m/s, and telemetry must say where that obstacle is. Without that
position the rule behaves exactly as before. (A wider "away or alongside"
version was tried and rejected: the benchmark measured robots sweeping into
racks while turning.)
"""
from __future__ import annotations

import math
from typing import Any, Dict

RETREAT_MAX_SPEED = 0.3
RETREAT_MIN_COS = 0.5   # within 60 degrees of directly away


def is_slow_retreat(telemetry: Dict[str, Any], params: Dict[str, Any]) -> bool:
    xy = telemetry.get("nearest_obstacle_xy")
    if not xy or len(xy) != 2:
        return False
    try:
        speed = float(params.get("max_speed", 0.0) or 0.0)
        x, y = float(telemetry.get("x", 0.0)), float(telemetry.get("y", 0.0))
        tx, ty = float(params.get("x", x)), float(params.get("y", y))
        ox, oy = float(xy[0]), float(xy[1])
    except (TypeError, ValueError):
        return False
    if speed > RETREAT_MAX_SPEED:
        return False
    mv = (tx - x, ty - y)
    away = (x - ox, y - oy)
    n1, n2 = math.hypot(*mv), math.hypot(*away)
    if n1 < 1e-6 or n2 < 1e-6:
        return False
    return (mv[0] * away[0] + mv[1] * away[1]) / (n1 * n2) >= RETREAT_MIN_COS
