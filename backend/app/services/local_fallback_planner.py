from __future__ import annotations

from typing import Dict, Any

from app.config import settings


def generate_fallback_waypoint(telemetry: Dict[str, Any], goal: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a conservative single-waypoint plan toward the goal.

    - Moves a short step toward the goal (max 0.5m) at a low speed.
    - Intended as a safe local fallback when the LLM planner is unavailable.
    """
    try:
        tx, ty = float(telemetry.get("x", 0.0)), float(telemetry.get("y", 0.0))
        gx, gy = float(goal.get("x", 0.0)), float(goal.get("y", 0.0))
        dx, dy = gx - tx, gy - ty
        dist = (dx * dx + dy * dy) ** 0.5
        if dist <= 0.01:
            # already at goal
            nx, ny = tx, ty
        else:
            step = min(0.5, dist)
            nx = tx + (dx / dist) * step
            ny = ty + (dy / dist) * step
    except Exception:
        nx, ny = telemetry.get("x", 0.0), telemetry.get("y", 0.0)

    waypoint = {
        "x": float(nx),
        "y": float(ny),
        # Use conservative slow speed near humans
        "max_speed": float(min(settings.max_speed_near_human, 0.3)),
    }
    return waypoint
