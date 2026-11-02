"""Context identity shared by the simulator, benchmark and learning services.

Standard library only. Context describes applicability; it never grants authority.
"""
from __future__ import annotations

import hashlib
from typing import Any

from .permit import canonical

CONTEXT_FIELDS = ("site_id", "map_version", "policy_version", "capability_profile_version")
SIM_CAPABILITY = "sim-amr-radius-0.4m-v1"


def world_identity(world: dict[str, Any]) -> dict[str, str]:
    """Fingerprint permanent geometry, including units and coordinate frame.

    Dynamic people/forklifts are deliberately excluded. The simulator emits this
    identity from its authoritative layout, rather than a moving world snapshot.
    """
    geometry = {k: world.get(k) for k in ("geofence", "racks", "zones", "bays", "features")}
    geometry["obstacles"] = [o for o in world.get("obstacles", [])
                             if o.get("type") not in ("forklift", "robot", "person", "worker")]
    geometry["units"] = world.get("units", "metres")
    geometry["coordinate_frame"] = world.get("coordinate_frame", "site-floor-v1")
    digest = hashlib.sha256(canonical(geometry).encode()).hexdigest()
    site = world.get("site") or {}
    return {"site_id": str(world.get("site_id") or site.get("id") or site.get("name")
                           or world.get("name") or f"layout:{digest}"),
            "map_version": digest}


def context_from_state(state: dict, policy_version: str) -> dict[str, str] | None:
    """No inferred current-site fallback: unknown context is ineligible for reuse."""
    context = {k: state.get(k) for k in CONTEXT_FIELDS}
    context["policy_version"] = policy_version
    if not all(isinstance(v, str) and v.strip() for v in context.values()):
        return None
    return context


def context_from_world(world: dict, policy_version: str) -> dict[str, str] | None:
    # Live worlds advertise the layout's stable identity; local benchmark layouts
    # can be fingerprinted directly. Do not hash moving live obstacles as a map.
    state = dict(world_identity(world), **{k: world[k] for k in
                 ("site_id", "map_version", "capability_profile_version") if k in world})
    return context_from_state(state, policy_version)


def context_key(context: dict) -> str:
    return hashlib.sha256(canonical(context).encode()).hexdigest()
