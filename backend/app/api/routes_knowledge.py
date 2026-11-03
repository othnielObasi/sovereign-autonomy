"""Curated operational graph queries; no caller-supplied Cypher."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.auth.roles import require_role_user, OPERATOR_ALWAYS
from app.deps import get_db
from app.services.operational_graph import graph, GraphUnavailable

router = APIRouter(prefix='/knowledge', tags=['operational knowledge'])
VIEWER = require_role_user('viewer')


class Context(BaseModel):
    site_id: str = Field(min_length=1, max_length=128)
    map_version: str = Field(min_length=1, max_length=128)
    policy_version: str = Field(min_length=1, max_length=128)
    capability_profile_version: str = Field(min_length=1, max_length=128)


class HistoryQuery(BaseModel):
    context: Context
    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)
    radius: float = Field(5., gt=0, le=10, allow_inf_nan=False)
    limit: int = Field(30, ge=1, le=50)


@router.get('/status')
def status(user=Depends(VIEWER)):
    return graph.status()


@router.post('/sync')
def sync(db: Session = Depends(get_db), user=Depends(OPERATOR_ALWAYS)):
    try:
        return graph.sync_recent(db)
    except GraphUnavailable:
        raise HTTPException(503, 'Operational graph unavailable') from None


@router.post('/runs/{run_id}/sync')
def sync_run(run_id: str, db: Session = Depends(get_db), user=Depends(OPERATOR_ALWAYS)):
    try:
        return graph.project_run(db, run_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    except Exception:
        raise HTTPException(503, 'Operational graph unavailable') from None


@router.get('/runs/{run_id}')
def run_history(run_id: str, limit: int = Query(30, ge=1, le=50),
                db: Session = Depends(get_db), user=Depends(VIEWER)):
    try:
        return graph.history(db, run_id=run_id, limit=limit)
    except Exception:
        raise HTTPException(503, 'Operational graph unavailable') from None


@router.post('/history')
def history(body: HistoryQuery, db: Session = Depends(get_db), user=Depends(VIEWER)):
    try:
        return graph.history(db, context=body.context.model_dump(), x=body.x, y=body.y,
                             radius=body.radius, limit=body.limit)
    except Exception:
        raise HTTPException(503, 'Operational graph unavailable') from None
