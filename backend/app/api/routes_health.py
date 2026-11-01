from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import settings
from app.db.session import engine

router = APIRouter()
logger = logging.getLogger("app.routes_health")


@router.get("/health")
async def health():
    """Health check endpoint with dependency status."""
    db_ok = False
    sim_ok = False
    sim_error = None

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:
        logger.warning("Health DB check failed: %s", exc)

    try:
        headers = {}
        if getattr(settings, "sim_token", ""):
            headers["X-Sim-Token"] = settings.sim_token
        async with httpx.AsyncClient(timeout=3.0, headers=headers) as client:
            r = await client.get(f"{settings.sim_base_url.rstrip('/')}/health")
            sim_ok = r.status_code == 200
    except Exception as exc:
        sim_error = str(exc)
        logger.warning("Health simulator check failed: %s", exc)

    payload = {
        "status": "ok" if db_ok and sim_ok else "degraded",
        "environment": settings.environment,
        "gemini_enabled": settings.gemini_configured,
        "nemotron_enabled": settings.nemotron_configured,
        "planner_provider": settings.planner_provider,
        "version": "0.1.0",
        "checks": {
            "database": "ok" if db_ok else "error",
            "simulator": "ok" if sim_ok else "error",
        },
    }
    if sim_error:
        payload["checks"]["simulator_detail"] = sim_error

    # Return 200 as long as the backend is alive — dependency failures
    # are reported in the payload but should NOT cause container restarts.
    return JSONResponse(status_code=200, content=payload)
