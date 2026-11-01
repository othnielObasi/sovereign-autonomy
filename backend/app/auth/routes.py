from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.auth.jwt import create_access_token
from app.auth.roles import ROLE_RANK, authenticate, principal_from_token
from app.config import settings

router = APIRouter()


class LoginBody(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=200)


@router.post("/auth/login")
def login(body: LoginBody):
    """Sign in with an account from AUTH_ACCOUNTS; the token carries the account's role."""
    principal = authenticate(body.username, body.password)
    if principal is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong username or password")
    return {"access_token": create_access_token(principal.name, role=principal.role), "token_type": "bearer",
            "user": principal.name, "role": principal.role}


@router.post("/auth/dev-token")
def dev_token(role: str = "operator"):
    """Development only: a token for a test identity (never available in production)."""
    if not settings.dev_tokens_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if role not in ROLE_RANK:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown role")
    return {"access_token": create_access_token(f"dev-{role}", role=role), "token_type": "bearer",
            "user": f"dev-{role}", "role": role}


@router.get("/auth/me")
def me(creds: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False))):
    if creds is None or not creds.credentials:
        return {"signed_in": False, "auth_required": settings.require_auth}
    p = principal_from_token(creds.credentials)
    return {"signed_in": True, "user": p.name, "role": p.role, "auth_required": settings.require_auth}
