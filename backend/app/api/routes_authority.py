"""Execution authority API: kill switches and permit status.

Stopping is always allowed (no login needed); lifting a kill switch requires an
authenticated operator, and permits issued before the switch stay void.
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
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


_STOP_WORDS = re.compile(r"\b(stop|halt|freeze|abort|emergency|e-?stop)\b", re.I)
_ALL_WORDS = re.compile(r"\b(everything|everyone|all|global|whole site|every robot)\b", re.I)


def voice_intent(transcript: str, robot_id: str) -> Optional[dict]:
    """Map speech to a kill switch. Voice can only ever stop: anything else is ignored."""
    if not transcript or not _STOP_WORDS.search(transcript):
        return None
    if _ALL_WORDS.search(transcript):
        return {"scope": "global", "id": "*"}
    return {"scope": "robot", "id": robot_id}


@router.post("/voice")
async def voice_stop(audio: UploadFile = File(..., description="WAV, mono 16-bit PCM, 16 or 24 kHz"),
                     user: Optional[str] = Depends(get_current_user)):
    """Spoken stop (Muse Voice Transcribe). A stop phrase fires a kill switch; nothing
    spoken can start, resume or reset the robot."""
    from app.config import settings
    from app.services import meta_models
    if not settings.voice_configured:
        raise HTTPException(status_code=503, detail="voice needs MODEL_API_KEY (Muse Voice Transcribe)")
    wav = await audio.read()
    if len(wav) > 32 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="audio too large")
    transcript, call = await meta_models.transcribe(wav)
    if transcript is None:
        raise HTTPException(status_code=502, detail="transcription failed")
    authority = get_authority()
    intent = voice_intent(transcript, authority.robot_id)
    if intent is None:
        return {"transcript": transcript, "action": "none",
                "note": "No stop phrase heard. Voice can only stop the robot.", "latency_ms": call.get("latency_ms")}
    report = await authority.kill(intent["scope"], intent["id"], reason=f'voice: "{transcript[:120]}"',
                                  actor=user or "voice", sim=_sim())
    return {"transcript": transcript, "action": "kill", "transcribe_ms": call.get("latency_ms"), **report}


@router.get("/evidence")
def evidence(limit: int = 200):
    """Recent dispatch and kill-switch events (most recent last)."""
    return {"events": get_authority().evidence.events[-max(1, min(limit, 1000)):]}
