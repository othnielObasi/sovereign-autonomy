"""Roles and accounts.

    viewer   < operator < admin

- Anyone may stop the robot (kill switches): stopping is always the safe direction.
- operator: start, stop, pause and resume missions; approve and override; reset a
  kill switch; run security drills; propose, approve or reject rule changes.
- admin: everything an operator can do, plus activate or roll back safety rules.

Accounts come from AUTH_ACCOUNTS ("name:role:pbkdf2_sha256$iterations$salt$hash;...";
create entries with scripts/add_account.py). In production every protected action
needs a valid token with a sufficient role. In development a request without a
token is allowed (local work and tests), but a token that is sent must carry the
role, and some actions (kill-switch reset) always need one.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Dict, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from app.config import settings

ROLE_RANK = {"viewer": 0, "operator": 1, "admin": 2}
_bearer = HTTPBearer(auto_error=False)
PBKDF2_ITERATIONS = 310_000


@dataclass(frozen=True)
class Principal:
    name: str
    role: str
    authenticated: bool = True


ANONYMOUS_DEV = Principal("dev-anonymous", "viewer", authenticated=False)


# --- passwords and accounts ---------------------------------------------------------------------

def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS, salt: Optional[bytes] = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, digest_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def accounts() -> Dict[str, tuple[str, str]]:
    """name -> (role, password hash), from AUTH_ACCOUNTS."""
    out: Dict[str, tuple[str, str]] = {}
    for entry in (settings.auth_accounts or "").split(";"):
        parts = entry.strip().split(":", 2)
        if len(parts) == 3 and parts[1] in ROLE_RANK and parts[0]:
            out[parts[0]] = (parts[1], parts[2])
    return out


_DUMMY_HASH = hash_password("timing-equaliser", iterations=1000)


def authenticate(username: str, password: str) -> Optional[Principal]:
    account = accounts().get(username)
    if account is None:
        verify_password(password, _DUMMY_HASH)   # similar work whether or not the name exists
        return None
    role, stored = account
    return Principal(username, role) if verify_password(password, stored) else None


# --- tokens -> principal ------------------------------------------------------------------------

def principal_from_token(token: str) -> Principal:
    from app.auth.jwt import decode_token
    try:
        payload = decode_token(token)
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}",
                            headers={"WWW-Authenticate": "Bearer"})
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing subject claim")
    role = payload.get("role", "viewer")
    return Principal(sub, role if role in ROLE_RANK else "viewer")


def require_role(minimum: str, *, always: bool = False):
    """Dependency: the caller must hold `minimum` (or higher).

    always=True enforces it in development too."""
    need = ROLE_RANK[minimum]

    async def dep(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> Principal:
        if creds is None or not creds.credentials:
            if settings.require_auth or always:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                    detail=f"Sign in as {minimum} or higher", headers={"WWW-Authenticate": "Bearer"})
            return ANONYMOUS_DEV
        principal = principal_from_token(creds.credentials)
        if ROLE_RANK[principal.role] < need:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail=f"Role '{principal.role}' cannot do this; needs {minimum}")
        return principal

    return dep


def actor_name(principal: Principal, fallback: Optional[str] = None) -> Optional[str]:
    """The name to record in the audit trail."""
    return principal.name if principal.authenticated else fallback


def require_role_user(minimum: str, *, always: bool = False):
    """Like require_role, but returns the actor name for the audit trail (None for an
    anonymous development request), so existing `user` parameters keep working."""
    inner = require_role(minimum, always=always)

    async def dep(principal: Principal = Depends(inner)) -> Optional[str]:
        return actor_name(principal)

    return dep


OPERATOR = require_role_user("operator")
ADMIN = require_role_user("admin")
OPERATOR_ALWAYS = require_role_user("operator", always=True)
