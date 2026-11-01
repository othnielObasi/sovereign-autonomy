from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from app.auth.jwt import create_access_token
from app.config import settings

router = APIRouter()


@router.post("/auth/dev-token")
def dev_token():
    """MVP helper endpoint: returns a dev token.

    In production, replace with real auth.
    """
    if not settings.dev_tokens_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return {"access_token": create_access_token("operator"), "token_type": "bearer"}
