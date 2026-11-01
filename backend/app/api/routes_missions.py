from __future__ import annotations

"""Mission CRUD routes.

All endpoints require JWT auth (via ``get_current_user``) for mutations and
delegate business logic to ``MissionService``.  Read endpoints are
unauthenticated so the dashboard can freely poll without a token.

State machine: draft → executing → paused ↔ draft (resume) → completed.
"""

import json
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List

from app.deps import get_db
from app.auth.jwt import get_current_user
from app.services.mission_service import MissionService
from app.schemas.mission import MissionCreate, MissionUpdate, MissionOut, MissionAuditOut

router = APIRouter()
svc = MissionService()


def _to_out(m) -> MissionOut:
    return MissionOut(
        id=m.id,
        title=m.title,
        goal=json.loads(m.goal_json),
        status=getattr(m, "status", "draft") or "draft",
        created_at=m.created_at,
        updated_at=getattr(m, "updated_at", None),
    )


def _audit_to_out(a) -> MissionAuditOut:
    return MissionAuditOut(
        id=a.id,
        mission_id=a.mission_id,
        ts=a.ts,
        action=a.action,
        actor=a.actor,
        old_values=json.loads(a.old_values) if a.old_values else None,
        new_values=json.loads(a.new_values) if a.new_values else None,
        details=a.details,
    )


@router.post("/missions", response_model=MissionOut)
def create_mission(
    payload: MissionCreate,
    db: Session = Depends(get_db),
    user: str | None = Depends(get_current_user),
):
    m = svc.create(db, payload)
    return _to_out(m)


@router.get("/missions", response_model=List[MissionOut])
def list_missions(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    missions = svc.list(db, limit=limit, offset=offset)
    return [_to_out(m) for m in missions]


@router.get("/missions/{mission_id}", response_model=MissionOut)
def get_mission(mission_id: str, db: Session = Depends(get_db)):
    m = svc.get(db, mission_id)
    if not m:
        raise HTTPException(status_code=404, detail="mission not found")
    return _to_out(m)


@router.patch("/missions/{mission_id}", response_model=MissionOut)
def update_mission(
    mission_id: str,
    payload: MissionUpdate,
    db: Session = Depends(get_db),
    user: str | None = Depends(get_current_user),
):
    m = svc.update(db, mission_id, payload)
    if not m:
        raise HTTPException(status_code=404, detail="Mission not found or not editable (must be draft/paused)")
    return _to_out(m)


@router.post("/missions/{mission_id}/pause", response_model=MissionOut)
def pause_mission(
    mission_id: str,
    db: Session = Depends(get_db),
    user: str | None = Depends(get_current_user),
):
    m = svc.get(db, mission_id)
    if not m:
        raise HTTPException(status_code=404, detail="Mission not found")
    if m.status not in ("draft", "executing"):
        raise HTTPException(status_code=400, detail=f"Cannot pause mission in '{m.status}' state")
    m = svc.set_status(db, mission_id, "paused", details="Mission paused by operator")
    return _to_out(m)


@router.post("/missions/{mission_id}/resume", response_model=MissionOut)
def resume_mission(
    mission_id: str,
    db: Session = Depends(get_db),
    user: str | None = Depends(get_current_user),
):
    m = svc.get(db, mission_id)
    if not m:
        raise HTTPException(status_code=404, detail="Mission not found")
    if m.status != "paused":
        raise HTTPException(status_code=400, detail="Can only resume paused missions")
    m = svc.set_status(db, mission_id, "draft", details="Mission resumed by operator")
    return _to_out(m)


@router.post("/missions/{mission_id}/replay", response_model=MissionOut)
def replay_mission(
    mission_id: str,
    db: Session = Depends(get_db),
    user: str | None = Depends(get_current_user),
):
    """Reset a completed mission back to draft so it can be re-executed."""
    m = svc.replay(db, mission_id)
    if not m:
        raise HTTPException(status_code=400, detail="Mission not found or not in a replayable state (completed/failed/paused)")
    return _to_out(m)


@router.delete("/missions/{mission_id}")
def delete_mission(
    mission_id: str,
    db: Session = Depends(get_db),
    user: str | None = Depends(get_current_user),
):
    m = svc.get(db, mission_id)
    if not m:
        raise HTTPException(status_code=404, detail="mission not found")
    svc.soft_delete(db, mission_id)
    return {"ok": True, "deleted": mission_id}


# ── Audit Trail ────────────────────────────────────────────

@router.get("/missions/{mission_id}/audit", response_model=List[MissionAuditOut])
def get_mission_audit(
    mission_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Get the full audit trail for a specific mission."""
    m = svc.get(db, mission_id)
    if not m:
        raise HTTPException(status_code=404, detail="Mission not found")
    entries = svc.get_audit_trail(db, mission_id=mission_id, limit=limit, offset=offset)
    return [_audit_to_out(a) for a in entries]


@router.get("/audit/missions", response_model=List[MissionAuditOut])
def get_all_audit(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Get the global mission audit trail across all missions."""
    entries = svc.get_audit_trail(db, limit=limit, offset=offset)
    return [_audit_to_out(a) for a in entries]
