"""Ed25519 signing for governance receipts.

The hash chain proves order and detects edits; a signature additionally proves
which deployment produced a decision. Third parties verify with the published
public key (GET /governance/signing-key).

Key source, in order:
1. RECEIPT_SIGNING_KEY env var: base64 of the 32-byte raw Ed25519 private key
   (generate one with: python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())")
2. A key file at RECEIPT_SIGNING_KEY_FILE (default ./data/receipt_signing.key),
   created on first use. Fine for development; set (1) in production so the
   key survives redeploys.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

logger = logging.getLogger("app.signing")

SIGNATURE_ALG = "Ed25519"
_lock = threading.Lock()
_key: Optional[Ed25519PrivateKey] = None


def _raw_public(pub: Ed25519PublicKey) -> bytes:
    return pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _load_key() -> Ed25519PrivateKey:
    env = os.environ.get("RECEIPT_SIGNING_KEY")
    if env:
        return Ed25519PrivateKey.from_private_bytes(base64.b64decode(env))
    path = Path(os.environ.get("RECEIPT_SIGNING_KEY_FILE", "./data/receipt_signing.key"))
    if path.exists():
        return Ed25519PrivateKey.from_private_bytes(base64.b64decode(path.read_text().strip()))
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                            serialization.NoEncryption())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(base64.b64encode(raw).decode())
        os.chmod(path, 0o600)
        logger.warning("Generated a new receipt signing key at %s; set RECEIPT_SIGNING_KEY in production", path)
    except OSError as e:
        logger.warning("Could not persist receipt signing key (%s); signatures will not survive a restart", e)
    return key


def _get_key() -> Ed25519PrivateKey:
    global _key
    with _lock:
        if _key is None:
            _key = _load_key()
        return _key


def key_id() -> str:
    return hashlib.sha256(_raw_public(_get_key().public_key())).hexdigest()[:16]


def public_key_info() -> Dict[str, str]:
    pub = _get_key().public_key()
    return {
        "algorithm": SIGNATURE_ALG,
        "key_id": key_id(),
        "public_key_b64": base64.b64encode(_raw_public(pub)).decode(),
        "public_key_pem": pub.public_bytes(serialization.Encoding.PEM,
                                           serialization.PublicFormat.SubjectPublicKeyInfo).decode(),
    }


def canonical_ts(ts: dt.datetime) -> str:
    """UTC, no tz suffix, microseconds — identical whether the DB returns aware or naive datetimes."""
    if ts.tzinfo is not None:
        ts = ts.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return ts.isoformat(timespec="microseconds")


def canonical_bytes(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign(payload: Dict[str, Any]) -> Tuple[str, str]:
    """Returns (signature_b64, key_id)."""
    sig = _get_key().sign(canonical_bytes(payload))
    return base64.b64encode(sig).decode(), key_id()


def verify(payload: Dict[str, Any], signature_b64: str, signed_key_id: str) -> Dict[str, Any]:
    if signed_key_id != key_id():
        return {"valid": False, "reason": f"signed by key {signed_key_id}, this deployment uses {key_id()}"}
    try:
        _get_key().public_key().verify(base64.b64decode(signature_b64), canonical_bytes(payload))
        return {"valid": True, "reason": "signature matches the decision content"}
    except (InvalidSignature, ValueError):
        return {"valid": False, "reason": "signature does not match the decision content (altered or corrupted)"}


def _reset_for_tests(key: Optional[Ed25519PrivateKey] = None) -> None:
    global _key
    with _lock:
        _key = key
