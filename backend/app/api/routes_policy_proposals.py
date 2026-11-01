"""Governed rule changes: propose, evaluate, approve, activate, roll back.

Identity: when a valid Bearer token is sent, its subject is the actor and any
name in the body is ignored. Without a token, the body name is used, which is
only allowed when authentication is not required (development).
"""
from __future__ import annotations

from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.jwt import get_current_user
from app.config import settings
from app.db.models import PolicyActivation, PolicyProposal
from app.deps import get_db
from app.policies import params as P
from app.policies import proposals as svc

router = APIRouter(prefix="/policies", tags=["policy-proposals"])


def _actor(body_name: Optional[str], token_user: Optional[str]) -> str:
    if token_user:
        return token_user
    if settings.require_auth:
        raise HTTPException(status_code=401, detail="Authentication required to change policy")
    if not (body_name or "").strip():
        raise HTTPException(status_code=400, detail="A name is required for the audit trail")
    return body_name.strip()


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except svc.ProposalError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from None


class CreateBody(BaseModel):
    changes: Dict[str, float] = Field(..., description='e.g. {"ZONE_SPEED_LIMITS.aisle": 0.45}')
    created_by: Optional[str] = None
    description: str = ""


class ActorBody(BaseModel):
    by: Optional[str] = None


class ApproveBody(BaseModel):
    approver: Optional[str] = None
    note: str = ""


class ReasonBody(BaseModel):
    by: Optional[str] = None
    reason: str = Field(..., min_length=5)


class EvaluateBody(BaseModel):
    limit: int = Field(svc.REPLAY_LIMIT, ge=10, le=50000)


@router.get("/active")
def get_active(db: Session = Depends(get_db)):
    """The rules the gate enforces now, the latest activation, and what may be changed."""
    latest = db.query(PolicyActivation).order_by(PolicyActivation.id.desc()).first()
    active = P.active_params()
    return {
        "version": P.params_hash(active),
        "is_default": P.params_hash(active) == P.params_hash(P.DEFAULT_PARAMS),
        "parameters": active,
        "activation": svc.activation_dict(latest) if latest else None,
        "changeable": P.PARAM_SPEC,
        "safety_floors": svc.SAFETY_FLOORS,
    }


@router.get("/activations")
def list_activations(db: Session = Depends(get_db)):
    rows = db.query(PolicyActivation).order_by(PolicyActivation.id.desc()).limit(100).all()
    return [svc.activation_dict(a) for a in rows]


@router.get("/proposals")
def list_proposals(status: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(PolicyProposal)
    if status:
        q = q.filter(PolicyProposal.status == status)
    return [svc.to_dict(r) for r in q.order_by(PolicyProposal.created_at.desc()).limit(100).all()]


@router.post("/proposals")
def create_proposal(body: CreateBody, db: Session = Depends(get_db), user: Optional[str] = Depends(get_current_user)):
    return svc.to_dict(_call(svc.create, db, body.changes, _actor(body.created_by, user), body.description))


@router.post("/proposals/from-tuning")
def create_from_tuning(body: ActorBody, db: Session = Depends(get_db), user: Optional[str] = Depends(get_current_user)):
    return svc.to_dict(_call(svc.create_from_tuning, db, _actor(body.by, user)))


@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str, db: Session = Depends(get_db)):
    return svc.to_dict(_call(svc._get, db, proposal_id))


@router.post("/proposals/{proposal_id}/evaluate")
def evaluate_proposal(proposal_id: str, body: EvaluateBody = EvaluateBody(), db: Session = Depends(get_db)):
    return svc.to_dict(_call(svc.evaluate, db, proposal_id, body.limit))


class BenchmarkBody(BaseModel):
    seeds: int = Field(svc.BENCHMARK_SEEDS, ge=5, le=200)


@router.post("/proposals/{proposal_id}/benchmark")
def benchmark_proposal(proposal_id: str, body: BenchmarkBody = BenchmarkBody(), db: Session = Depends(get_db)):
    """Drive seeded scenarios under the active and candidate rules (takes ~1 s per scenario)."""
    return svc.to_dict(_call(svc.benchmark, db, proposal_id, body.seeds))


@router.post("/proposals/{proposal_id}/approve")
def approve_proposal(proposal_id: str, body: ApproveBody, db: Session = Depends(get_db),
                     user: Optional[str] = Depends(get_current_user)):
    return svc.to_dict(_call(svc.approve, db, proposal_id, _actor(body.approver, user), body.note))


@router.post("/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: str, body: ReasonBody, db: Session = Depends(get_db),
                    user: Optional[str] = Depends(get_current_user)):
    return svc.to_dict(_call(svc.reject, db, proposal_id, _actor(body.by, user), body.reason))


@router.post("/proposals/{proposal_id}/activate")
def activate_proposal(proposal_id: str, body: ActorBody, db: Session = Depends(get_db),
                      user: Optional[str] = Depends(get_current_user)):
    return svc.activation_dict(_call(svc.activate, db, proposal_id, _actor(body.by, user)))


@router.post("/rollback")
def rollback(body: ReasonBody, db: Session = Depends(get_db), user: Optional[str] = Depends(get_current_user)):
    return svc.activation_dict(_call(svc.rollback, db, _actor(body.by, user), body.reason))
