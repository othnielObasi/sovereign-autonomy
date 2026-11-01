"""Permanent site structure the gate checks paths against (racking).

The obstacle-clearance rule looks at where the robot is now. This adds where a
move would take it: a MOVE_TO whose straight line passes through racking is
refused before the robot starts, instead of being stopped once it is already
close. Only permanent structure is used here; moving hazards are covered by the
live clearance and proximity rules.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

ROBOT_RADIUS_M = 0.4
PATH_MARGIN_M = ROBOT_RADIUS_M + 0.2   # body within 0.2 m of racking along the path = blocked
SAMPLE_STEP_M = 0.1

Rect = Tuple[str, float, float, float, float]


def _racks_from_world(world: Dict[str, Any]) -> List[Rect]:
    out = []
    for r in world.get("racks") or []:
        try:
            y1 = float(r["y"])
            out.append((str(r.get("id", "rack")), float(r["x1"]), y1, float(r["x2"]), y1 + float(r.get("depth", 1.0))))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _load_default() -> List[Rect]:
    try:
        from app.world_model import _world
        return _racks_from_world(_world)
    except Exception:
        return []


RACKS: List[Rect] = _load_default()


def _rect_distance(x: float, y: float, r: Rect) -> float:
    _, x1, y1, x2, y2 = r
    dx = max(x1 - x, 0.0, x - x2)
    dy = max(y1 - y, 0.0, y - y2)
    return math.hypot(dx, dy)


def path_blocked(x: float, y: float, tx: float, ty: float, racks: Optional[List[Rect]] = None,
                 margin: float = PATH_MARGIN_M) -> Optional[str]:
    """Id of the first rack the straight path (x, y) -> (tx, ty) runs through, or None.

    The start point itself is ignored (a robot that is already close is handled by
    the clearance rule and the slow-retreat exception), so the check begins one
    robot radius along the path. If the reported position is inside racking the
    map is not trusted and the check is skipped.
    """
    racks = RACKS if racks is None else racks
    length = math.hypot(tx - x, ty - y)
    if not racks or length < 1e-6:
        return None
    if any(_rect_distance(x, y, r) < ROBOT_RADIUS_M for r in racks):
        # Telemetry puts the robot inside racking: the map and the robot disagree, so this
        # check cannot be trusted here; the live clearance rule still applies.
        return None
    ux, uy = (tx - x) / length, (ty - y) / length
    s = min(ROBOT_RADIUS_M, length)
    while s <= length + 1e-9:
        px, py = x + ux * s, y + uy * s
        for r in racks:
            if _rect_distance(px, py, r) < margin:
                return r[0]
        s += SAMPLE_STEP_M
    return None
