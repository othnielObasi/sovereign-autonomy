"""Execution authority API: kill switches and permit status.

Stopping is always allowed (no login needed); lifting a kill switch requires an
authenticated operator, and permits issued before the switch stay void.
"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.jwt import get_current_user, require_authenticated_user
from app.services.execution_authority import get_authority

router = APIRouter(prefix="/authority", tags=["authority"])

Scope = Literal["global", "robot", "mission", "agent"]


class KillRequest(BaseModel):
    scope: Scope
    id: str = Field("*", description="robot id, mission id or agent id; ignored for global")
    reason: str = Field("operator stop", max_length=300)


class ResetRequest(BaseModel):
    scope: Scope
    id: str = "*"


def _sim():
    from app.api.routes_runs import get_run_svc
    return get_run_svc().sim


@router.get("/status")
def status():
    """Whether permits are enforced, active kill switches, and journal integrity."""
    return get_authority().status()


@router.post("/kill")
async def kill(req: KillRequest, user: Optional[str] = Depends(get_current_user)):
    """Revoke authority at once, stop the robot at the controller, and report measured times."""
    if req.scope != "global" and (not req.id or req.id == "*"):
        raise HTTPException(status_code=422, detail="id is required for robot, mission and agent scope")
    return await get_authority().kill(req.scope, req.id, reason=req.reason, actor=user, sim=_sim())


@router.post("/reset")
async def reset(req: ResetRequest, user: str = Depends(require_authenticated_user)):
    """Lift one kill switch. Requires an authenticated operator."""
    authority = get_authority()
    ident = "*" if req.scope == "global" else req.id
    if not any(s == req.scope and i == ident for s, i in authority.kills.active()):
        raise HTTPException(status_code=404, detail="no such kill switch is active")
    return await authority.reset(req.scope, req.id, actor=user, sim=_sim())


@router.get("/evidence")
def evidence(limit: int = 200):
    """Recent dispatch and kill-switch events (most recent last)."""
    return {"events": get_authority().evidence.events[-max(1, min(limit, 1000)):]}
