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
import math
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
    if not math.isfinite(expires) or not isinstance(payload.get("id"), str):
        raise PermitError("malformed_permit")
    if (time.time() if now is None else now) >= expires:
        raise PermitError("permit_expired")
    return payload


CONTROLLER_FIELDS = ("boot_id", "generation", "site_id", "map_version", "capability_profile_version")


def controller_context(telemetry: dict) -> dict | None:
    context = {k: telemetry.get(k) for k in CONTROLLER_FIELDS}
    if (not all(isinstance(context[k], str) and context[k] for k in CONTROLLER_FIELDS if k != "generation")
            or type(context["generation"]) is not int or context["generation"] < 0):
        return None
    return context


def redemption_request(secret: bytes, token: str, action: dict, controller: dict, ttl_s: float = 2.0) -> str:
    return sign(secret, {"kind": "controller_redemption", "request_id": str(uuid.uuid4()),
                         "permit": token, "action": action, "controller": controller,
                         "expires": time.time() + ttl_s})


def verify_redemption_request(secret: bytes, envelope: str) -> dict:
    payload, _ = open_envelope(secret, envelope)
    try:
        expires = float(payload["expires"])
        if (payload["kind"] != "controller_redemption" or not payload["request_id"]
                or not isinstance(payload["action"], dict) or not isinstance(payload["permit"], str)
                or controller_context(payload["controller"]) != payload["controller"]):
            raise PermitError("malformed_redemption")
        if not math.isfinite(expires) or not time.time() < expires <= time.time() + 3:
            raise PermitError("redemption_expired")
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise PermitError("malformed_redemption") from exc
    return payload


def redemption_response(secret: bytes, request: str, expires: float) -> str:
    return sign(secret, {"kind": "controller_admission", "request_digest": hashlib.sha256(request.encode()).hexdigest(),
                         "expires": min(expires, time.time() + 1.0)})


def verify_redemption_response(secret: bytes, response: str, request: str) -> None:
    payload, _ = open_envelope(secret, response)
    try:
        expires = float(payload["expires"])
        if (payload["kind"] != "controller_admission"
                or payload["request_digest"] != hashlib.sha256(request.encode()).hexdigest()):
            raise PermitError("redemption_response_mismatch")
        if not math.isfinite(expires) or time.time() >= expires:
            raise PermitError("redemption_expired")
    except (KeyError, TypeError, ValueError) as exc:
        raise PermitError("malformed_redemption") from exc


def release_token(secret: bytes, robot_id: str, ttl_s: float = 10.0) -> str:
    """A signed, short-lived token that lets the backend release a controller e-stop."""
    return sign(secret, {"kind": "estop_release", "robot": robot_id, "id": str(uuid.uuid4()),
                         "expires": time.time() + ttl_s})


def verify_release(secret: bytes, token: str, robot_id: str) -> dict:
    payload, _ = open_envelope(secret, token)
    if payload.get("kind") != "estop_release" or payload.get("robot") != robot_id:
        raise PermitError("not_a_release_token")
    try:
        expires = float(payload.get("expires", 0))
        if not isinstance(payload.get("id"), str) or not math.isfinite(expires):
            raise PermitError("malformed_permit")
    except (TypeError, ValueError) as exc:
        raise PermitError("malformed_permit") from exc
    if time.time() >= expires:
        raise PermitError("permit_expired")
    return payload
