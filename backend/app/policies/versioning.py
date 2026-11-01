from __future__ import annotations

"""Policy versioning — compute a deterministic hash of the active policy set.

Used to tag every governance decision with the exact policy configuration
that was in effect, enabling reproducibility and regulatory traceability.
"""

import hashlib
import json
from typing import Any, Dict

from app.policies.params import active_params

# Singleton cache
_cached_version: str | None = None
_cached_params: Dict[str, Any] | None = None


def _policy_params() -> Dict[str, Any]:
    """The ACTIVE policy parameters (defaults until a governed change is activated)."""
    return active_params()


def policy_version_hash() -> str:
    """Return a short SHA256 hex digest of the active policy parameters.

    This is deterministic for a given set of constants — changing any
    parameter changes the hash, making it trivial to detect drift.
    """
    global _cached_version, _cached_params
    params = _policy_params()
    if _cached_params == params and _cached_version is not None:
        return _cached_version
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"))
    _cached_version = hashlib.sha256(canonical.encode()).hexdigest()[:16]
    _cached_params = params
    return _cached_version


def policy_version_info() -> Dict[str, Any]:
    """Return the full version info: hash + all active parameters."""
    return {
        "version_hash": policy_version_hash(),
        "parameters": _policy_params(),
    }
