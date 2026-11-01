from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from app.services import operator_approval as approval_svc
from app.utils.hashing import sha256_canonical
from app.auth.jwt import get_current_user

router = APIRouter(prefix="/operator", tags=["operator"])


class ApproveRequest(BaseModel):
    run_id: str
    proposal: dict
    notes: Optional[str] = None


class OverrideRequest(BaseModel):
    run_id: str
    action: str  # "resume"|"force_approve"|"replan"
    reason: str


def _require_operator(current_user: str):
    if current_user != "operator":
        raise HTTPException(status_code=403, detail="Insufficient role")


@router.post("/approve")
def approve(req: ApproveRequest, current_user: str | None = Depends(get_current_user)):
    actor = current_user or "operator"
    try:
        ph = sha256_canonical({"proposal": req.proposal})
        approval_svc.approve(req.run_id, ph, approved_by=actor, notes=req.notes)
        return {"ok": True, "run_id": req.run_id, "proposal_hash": ph}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/override")
async def operator_override(req: OverrideRequest, current_user: str | None = Depends(get_current_user)):
    """Operator override — allows resuming paused runs, force-approving, or triggering replan.

    All overrides are logged as INTERVENTION events in the audit trail.
    """
    actor = current_user or "operator"

    if req.action not in ("resume", "force_approve", "replan"):
        raise HTTPException(status_code=400, detail=f"Invalid override action: {req.action}")

    if not req.reason or len(req.reason) < 5:
        raise HTTPException(status_code=400, detail="Override reason must be at least 5 characters")

    # Import run_svc from routes_runs (shared singleton)
    import app.api.routes_runs as routes_runs_module
    run_svc = routes_runs_module.run_svc
    if not run_svc:
        raise HTTPException(status_code=500, detail="RunService not initialized")

    from app.db.session import SessionLocal
    from app.db.models import Run
    db = SessionLocal()
    try:
        run = db.query(Run).filter(Run.id == req.run_id).first()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        # Record the override as an INTERVENTION event
        run_svc._append_event(db, req.run_id, "INTERVENTION", {
            "type": f"OPERATOR_OVERRIDE:{req.action.upper()}",
            "actor": actor,
            "reason": req.reason,
            "action": req.action,
        })
        db.commit()

        if req.action == "resume" and run.status == "paused":
            await run_svc.resume_run(db, req.run_id)
            return {"ok": True, "action": "resumed", "run_id": req.run_id}

        return {"ok": True, "action": req.action, "run_id": req.run_id, "note": "Override recorded"}
    finally:
        db.close()


@router.get("/approvals/{run_id}")
def list_approvals(run_id: str, current_user: str | None = Depends(get_current_user)):
    return {"run_id": run_id, "approvals": approval_svc.list_for_run(run_id)}

