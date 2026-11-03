from __future__ import annotations

import asyncio
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.auth.roles import OPERATOR_ALWAYS
from app.deps import get_db
from app.db.models import Run
from app.autonomy.core import Rejected
from app.services import operator_approval as approval_svc
from app.services import operator_controls as controls

router = APIRouter(prefix='/operator', tags=['operator'])


class ApproveRequest(BaseModel):
    run_id: str
    proposal: dict
    decision_event_id: str
    notes: str = Field(min_length=5, max_length=1000)


class OverrideRequest(BaseModel):
    run_id: str
    action: str
    reason: str = Field(min_length=5, max_length=1000)
    decision_event_id: Optional[str] = None


def service():
    from app.api.routes_runs import get_run_svc
    return get_run_svc()


def require_run(db, run_id):
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail='Run not found')
    return run


@router.get('/review/{run_id}')
def review(run_id: str, db: Session = Depends(get_db)):
    """Latest recorded review; eligibility is rechecked with fresh sensors on approval."""
    result = controls.latest_review(db, require_run(db, run_id))
    result.pop('telemetry', None)
    return result


@router.post('/approve')
async def approve(req: ApproveRequest, actor: str = Depends(OPERATOR_ALWAYS), db: Session = Depends(get_db)):
    return await apply(db, req.run_id, 'approve', req.notes.strip(), actor,
                       req.decision_event_id, req.proposal)


@router.post('/override')
async def operator_override(req: OverrideRequest, actor: str = Depends(OPERATOR_ALWAYS), db: Session = Depends(get_db)):
    """Replace and hold a route, approve an eligible review and resume, or resume normally."""
    if req.action not in ('resume','replan','force_approve'):
        raise HTTPException(status_code=400, detail='Invalid override action')
    return await apply(db, req.run_id, req.action, req.reason.strip(), actor, req.decision_event_id)


async def apply(db, run_id, action, reason, actor, event_id=None, proposal=None):
    if len(reason) < 5:
        raise HTTPException(status_code=422, detail='Reason must contain at least five non-padding characters')
    svc = service()
    lock = svc._operator_locks.setdefault(run_id, asyncio.Lock())
    if lock.locked():
        raise HTTPException(status_code=409, detail='operator_action_in_progress')
    async with lock:
        svc._operator_busy.add(run_id)
        try:
            run = require_run(db, run_id)
            if action == 'replan':
                return await controls.replan(db, svc, run, actor, reason)
            if action in ('approve','force_approve'):
                result = await controls.approve_review(db,svc,run,actor,reason,event_id,proposal)
                if action == 'approve':
                    return result
            if run.status != 'paused':
                raise Rejected('run_not_paused')
            resumed = await svc.resume_run(db,run_id,operator_control=True)
            if resumed is None:
                raise Rejected('run_not_paused')
            svc._append_event(db,run_id,'INTERVENTION',{'type':'OPERATOR_OVERRIDE:'+action.upper(),
                'actor':actor,'reason':reason,'decision_event_id':event_id})
            db.commit()
            return {'ok':True,'action':'review_approved_and_resumed' if action=='force_approve' else 'resumed',
                    'run_id':run_id,'status':'running',**resumed,
                    **({'approval_id':result['approval_id'],'expires_at':result['expires_at']} if action=='force_approve' else {})}
        except Rejected as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=409, detail='operator_context_invalid') from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=503, detail='Operator action could not be verified; inspect the run before resuming') from exc
        finally:
            svc._operator_busy.discard(run_id)


@router.get('/approvals/{run_id}')
def list_approvals(run_id: str):
    return {'run_id':run_id, 'approvals':approval_svc.list_for_run(run_id)}
