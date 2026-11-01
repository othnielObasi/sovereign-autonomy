"""Active policy parameters — the one place the gate reads its thresholds from.

The defaults are the constants in rules_python / world_model. The active set
starts as the defaults and changes only through the governed proposal
workflow (app/policies/proposals.py), which records every activation in the
append-only `policy_activations` table. On startup the latest activation is
reloaded, so an approved rule change survives restarts.

Parameter paths are dotted ("ZONE_SPEED_LIMITS.aisle") so a proposal can name
exactly one threshold. PARAM_SPEC gives each changeable path hard bounds: no
proposal, approved or not, can move a threshold past them. The bounds are code,
reviewed like code, not data.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import threading
from typing import Any, Dict, Optional

from app.world_model import GEOFENCE as _WM_GEOFENCE
from app.world_model import ZONE_SPEED_LIMITS as _WM_ZONE_SPEED_LIMITS

logger = logging.getLogger("app.policies.params")

DEFAULT_PARAMS: Dict[str, Any] = {
    "GEOFENCE": dict(_WM_GEOFENCE),
    "ZONE_SPEED_LIMITS": dict(_WM_ZONE_SPEED_LIMITS),
    "MIN_OBSTACLE_CLEARANCE_M": 0.5,
    "MIN_HUMAN_CONF": 0.65,
    "MAX_SPEED_NEAR_HUMAN": 0.4,
    "MIN_CONF_FOR_MOVE": 0.55,
    "HUMAN_SLOW_RADIUS_M": 3.0,
    "HUMAN_STOP_RADIUS_M": 1.0,
    "REVIEW_RISK_THRESHOLD": 0.75,
}

# Changeable paths and their hard bounds. `tighter` says which direction is safer.
PARAM_SPEC: Dict[str, Dict[str, Any]] = {
    "ZONE_SPEED_LIMITS.aisle":       {"min": 0.1, "max": 0.8, "tighter": "lower", "unit": "m/s"},
    "ZONE_SPEED_LIMITS.corridor":    {"min": 0.1, "max": 1.0, "tighter": "lower", "unit": "m/s"},
    "ZONE_SPEED_LIMITS.loading_bay": {"min": 0.1, "max": 0.6, "tighter": "lower", "unit": "m/s"},
    "ZONE_SPEED_LIMITS.staging":     {"min": 0.1, "max": 0.5, "tighter": "lower", "unit": "m/s"},
    "MAX_SPEED_NEAR_HUMAN":          {"min": 0.05, "max": 0.5, "tighter": "lower", "unit": "m/s"},
    "HUMAN_STOP_RADIUS_M":           {"min": 1.0, "max": 3.0, "tighter": "higher", "unit": "m"},
    "HUMAN_SLOW_RADIUS_M":           {"min": 2.0, "max": 10.0, "tighter": "higher", "unit": "m"},
    "MIN_OBSTACLE_CLEARANCE_M":      {"min": 0.5, "max": 3.0, "tighter": "higher", "unit": "m"},
    "MIN_HUMAN_CONF":                {"min": 0.5, "max": 0.95, "tighter": "higher", "unit": ""},
    "REVIEW_RISK_THRESHOLD":         {"min": 0.5, "max": 0.85, "tighter": "lower", "unit": ""},
}

_lock = threading.Lock()
_active: Dict[str, Any] = copy.deepcopy(DEFAULT_PARAMS)


def active_params() -> Dict[str, Any]:
    """A copy of the parameters the gate is enforcing right now."""
    with _lock:
        return copy.deepcopy(_active)


def params_hash(params: Dict[str, Any]) -> str:
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def get_path(params: Dict[str, Any], path: str) -> Any:
    node: Any = params
    for part in path.split("."):
        node = node[part]
    return node


def with_changes(params: Dict[str, Any], changes: Dict[str, float]) -> Dict[str, Any]:
    """Return a copy of `params` with dotted-path values replaced."""
    out = copy.deepcopy(params)
    for path, value in changes.items():
        parts = path.split(".")
        node = out
        for part in parts[:-1]:
            node = node[part]
        node[parts[-1]] = value
    return out


def validate(params: Dict[str, Any]) -> list[str]:
    """Problems with a parameter set: out-of-bounds values or inconsistent thresholds."""
    problems: list[str] = []
    for path, spec in PARAM_SPEC.items():
        try:
            v = float(get_path(params, path))
        except (KeyError, TypeError, ValueError):
            problems.append(f"{path}: missing or not a number")
            continue
        if not spec["min"] <= v <= spec["max"]:
            problems.append(f"{path}={v} outside hard bounds [{spec['min']}, {spec['max']}]")
    try:
        if float(params["HUMAN_STOP_RADIUS_M"]) >= float(params["HUMAN_SLOW_RADIUS_M"]):
            problems.append("HUMAN_STOP_RADIUS_M must be smaller than HUMAN_SLOW_RADIUS_M")
    except (KeyError, TypeError, ValueError):
        pass
    return problems


def _set_active(params: Dict[str, Any]) -> None:
    global _active
    with _lock:
        _active = copy.deepcopy(params)


def load_active_from_db(db) -> Optional[str]:
    """Reload the latest recorded activation (called at startup). Returns its version hash."""
    from app.db.models import PolicyActivation

    row = db.query(PolicyActivation).order_by(PolicyActivation.id.desc()).first()
    if row is None:
        _set_active(DEFAULT_PARAMS)
        return None
    params = json.loads(row.parameters_json)
    problems = validate(params)
    if problems:  # never enforce an invalid set; fall back to the defaults loudly
        logger.error("Stored activation %s is invalid (%s); enforcing defaults", row.version_hash, problems)
        _set_active(DEFAULT_PARAMS)
        return None
    _set_active(params)
    logger.info("Active policy version %s (activation #%s)", row.version_hash, row.id)
    return row.version_hash


def reset_to_defaults_for_tests() -> None:
    _set_active(DEFAULT_PARAMS)
