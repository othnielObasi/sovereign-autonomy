from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

from app.config import settings
from app.utils.time import utc_now

logger = logging.getLogger("app.auth")

_bearer_scheme = HTTPBearer(auto_error=False)


def create_access_token(subject: str) -> str:
    now = utc_now()
    exp = now + timedelta(minutes=settings.access_token_expire_minutes)
    payload: Dict[str, Any] = {
        "sub": subject,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> Dict[str, Any]:
    """Decode and validate a JWT token. Raises JWTError on failure."""
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
    )


async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> Optional[str]:
    """Return the subject claim from a valid Bearer token, or None.

    This dependency is always *optional* — it never raises 401.
    Use it on routes where knowing the user is nice-to-have (audit logging)
    but the endpoint should work without authentication (dashboard, missions,
    runs, governance queries, etc.).

    For routes that **require** authentication (operator actions), use
    ``require_authenticated_user`` instead.
    """
    if creds is None or creds.credentials == "":
        return None

    try:
        payload = decode_token(creds.credentials)
        return payload.get("sub")
    except JWTError as exc:
        logger.warning("Invalid JWT ignored: %s", exc)
        return None


async def require_authenticated_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> str:
    """Return the subject claim from a valid Bearer token.

    Raises HTTP 401 if no token is provided or the token is invalid.
    Use this on operator-privileged routes that must be authenticated.
    """
    if creds is None or creds.credentials == "":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(creds.credentials)
        sub = payload.get("sub")
        if not sub:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing subject claim",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return sub
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )
