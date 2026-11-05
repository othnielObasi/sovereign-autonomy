"""CPU skill lab: authenticated, bounded work outside the navigation event loop."""
import importlib.util
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.auth.roles import OPERATOR_ALWAYS, require_role_user
from app.config import settings
from app.services.memory_ledger import MemoryIntegrityError
from app.skills.service import get_skill_lab, SkillConflict

router = APIRouter(prefix='/skills', tags=['CPU skill lab'])
VIEWER = require_role_user('viewer')


def available():
    if not settings.skill_lab_enabled:
        raise HTTPException(503, 'CPU skill lab is disabled; enable SKILL_LAB_ENABLED after installing the skills extra')
    if not importlib.util.find_spec('mujoco') or not importlib.util.find_spec('numpy'):
        raise HTTPException(503, 'Install backend[skills] for CPU physics')
    try:
        return get_skill_lab()
    except MemoryIntegrityError as exc:
        raise HTTPException(503, 'Skill integrity verification failed') from exc


async def work(method, *args, **kwargs):
    try:
        return await run_in_threadpool(method, *args, **kwargs)
    except SkillConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except MemoryIntegrityError as exc:
        raise HTTPException(503, 'Skill integrity verification failed') from exc
    except OSError as exc:
        raise HTTPException(503, 'Skill artifact unavailable') from exc
    except ValueError as exc:
        raise HTTPException(409, 'Skill operation failed: ' + str(exc)[:200]) from exc


class Version(BaseModel):
    digest: str = Field(pattern=r'^[0-9a-f]{64}$')


class Recipient(Version):
    robot_id: str = Field(min_length=1, max_length=64)


class Grant(Recipient):
    seed: int = Field(12001, ge=12001, le=12100)


class Execution(BaseModel):
    permit: dict[str, Any]
    signature: str = Field(pattern=r'^[0-9a-f]{64}$')


@router.get('')
async def overview(user=Depends(VIEWER)):
    if not settings.skill_lab_enabled:
        return dict(enabled=False, available=bool(importlib.util.find_spec('mujoco')),
                    scope='Optional CPU manipulation lab; navigation remains available')
    return await work(available().overview)


@router.post('/train')
async def train(user=Depends(OPERATOR_ALWAYS)):
    return await work(available().train, user)


@router.post('/stop')
async def stop(user=Depends(VIEWER)):
    return await work(available().stop, user)


@router.post('/reset')
async def reset(user=Depends(OPERATOR_ALWAYS)):
    return await work(available().stop, user, reset=True)


@router.post('/execute')
async def execute(body: Execution, user=Depends(OPERATOR_ALWAYS)):
    return await work(available().execute, body.model_dump(), user)


@router.post('/{version}/install')
async def install(version: int, body: Recipient, user=Depends(OPERATOR_ALWAYS)):
    return await work(available().install, version, body.digest, body.robot_id, user)


@router.post('/{version}/grant')
async def grant(version: int, body: Grant, user=Depends(OPERATOR_ALWAYS)):
    return await work(available().grant, version, body.digest, body.robot_id, user, seed=body.seed)


@router.post('/{version}/{action}')
async def transition(version: int, action: str, body: Version, user=Depends(OPERATOR_ALWAYS)):
    return await work(available().transition, version, action, body.digest, user)
