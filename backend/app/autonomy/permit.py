"""Permit wire format, shared by the backend (which issues permits) and the
simulator/controller (which checks them before moving).

Standard library only, so the controller side can import it without the rest of
the backend. A permit is a JSON envelope {"payload": {...}, "signature": hex},
where the signature is HMAC-SHA256 over the canonical payload.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from typing import Any

# The fields that identify one exact action. The controller rebuilds this dict
# from the command it receives, so a permit cannot authorize different values.
ACTION_FIELDS = ("robot_id", "mission_id", "action_id", "kind", "params", "world_version", "policy_version")


class PermitError(RuntimeError):
    """A permit failed verification. The message is a short reason code."""


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def action_digest(action: dict) -> str:
    missing = [f for f in ACTION_FIELDS if f not in action]
    if missing:
        raise PermitError("action_fields_missing")
    return hashlib.sha256(canonical({f: action[f] for f in ACTION_FIELDS}).encode()).hexdigest()


def _sign(secret: bytes, raw: str) -> str:
    return hmac.new(secret, raw.encode(), hashlib.sha256).hexdigest()


def sign(secret: bytes, payload: dict) -> str:
    """Return a permit envelope for `payload`."""
    return canonical({"payload": payload, "signature": _sign(secret, canonical(payload))})


def open_envelope(secret: bytes, token: str) -> tuple[dict, str]:
    """Check the signature and return (payload, canonical payload). Raises PermitError."""
    try:
        envelope = json.loads(token)
        payload, signature = envelope["payload"], envelope["signature"]
        raw = canonical(payload)
    except (ValueError, KeyError, TypeError) as exc:
        raise PermitError("malformed_permit") from exc
    if not isinstance(payload, dict) or not isinstance(signature, str):
        raise PermitError("malformed_permit")
    if not hmac.compare_digest(signature, _sign(secret, raw)):
        raise PermitError("invalid_signature")
    return payload, raw


def verify_for_action(secret: bytes, token: str, action: dict, now: float | None = None) -> dict:
    """Controller-side check: signature, exact action match and expiry.

    Single-use tracking is the caller's job (keep the returned payload's "id").
    """
    payload, _ = open_envelope(secret, token)
    try:
        digest, robot, expires = payload["digest"], payload["robot"], float(payload["expires"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PermitError("malformed_permit") from exc
    if digest != action_digest(action) or robot != action["robot_id"]:
        raise PermitError("action_mismatch")
    if (time.time() if now is None else now) >= expires:
        raise PermitError("permit_expired")
    return payload


def release_token(secret: bytes, robot_id: str, ttl_s: float = 10.0) -> str:
    """A signed, short-lived token that lets the backend release a controller e-stop."""
    return sign(secret, {"kind": "estop_release", "robot": robot_id, "id": str(uuid.uuid4()),
                         "expires": time.time() + ttl_s})


def verify_release(secret: bytes, token: str, robot_id: str) -> dict:
    payload, _ = open_envelope(secret, token)
    if payload.get("kind") != "estop_release" or payload.get("robot") != robot_id:
        raise PermitError("not_a_release_token")
    if time.time() >= float(payload.get("expires", 0)):
        raise PermitError("permit_expired")
    return payload
