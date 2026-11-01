from __future__ import annotations

"""Unified world model — single source of truth for geofence, zone limits, etc.

Loads constants from sim/mock_sim/world.json so that the policy engine,
planners, and simulator all share the same boundary definitions.
Falls back to hardcoded defaults if world.json is unavailable.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("app.world_model")

# Locate world.json: repo_root/sim/mock_sim/world.json
_HERE = Path(__file__).resolve().parent  # backend/app/
_REPO_ROOT = _HERE.parent.parent  # backend/../ = repo root
_WORLD_PATH = _REPO_ROOT / "sim" / "mock_sim" / "world.json"

# Defaults matching the hardcoded values that existed before unification
_DEFAULT_GEOFENCE = {"min_x": 0.0, "max_x": 40.0, "min_y": 0.0, "max_y": 25.0}
_DEFAULT_ZONES: List[Dict[str, Any]] = []
_DEFAULT_BAYS: List[Dict[str, Any]] = []

_world: Dict[str, Any] = {}
# Inside the backend image only backend/ is present, so fall back to the
# benchmark layout (same site, same zone speed limits) instead of bare defaults.
_LAYOUT_PATH = _HERE.parent / "bench" / "layout.json"

try:
    _path = _WORLD_PATH if _WORLD_PATH.exists() else _LAYOUT_PATH
    with _path.open("r", encoding="utf-8") as f:
        _world = json.load(f)
    logger.info("Loaded world model from %s", _path)
except Exception as e:
    logger.warning("Could not load world.json (%s), using defaults", e)

GEOFENCE: Dict[str, float] = {
    k: float(v) for k, v in (_world.get("geofence") or _DEFAULT_GEOFENCE).items()
}

ZONES: List[Dict[str, Any]] = _world.get("zones") or _DEFAULT_ZONES
BAYS: List[Dict[str, Any]] = _world.get("bays") or _DEFAULT_BAYS
OBSTACLES: List[Dict[str, Any]] = _world.get("obstacles") or []

# Zone speed limits — loaded from world.json, with hardcoded fallback (#24)
_DEFAULT_ZONE_SPEED_LIMITS = {
    "aisle": 0.5,
    "corridor": 0.7,
    "loading_bay": 0.4,
}
_raw_limits = _world.get("zone_speed_limits") or {}
ZONE_SPEED_LIMITS: Dict[str, float] = {
    k: float(v) for k, v in _raw_limits.items()
} if _raw_limits else dict(_DEFAULT_ZONE_SPEED_LIMITS)
