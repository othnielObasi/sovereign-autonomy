"""Human learning release. Anyone the site lets in may look; every write needs a signed-in operator."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.roles import OPERATOR_ALWAYS, require_role_user
from app.autonomy.experience import context_from_state
from app.policies.versioning import policy_version_hash
from app.services.learning_release import get_learning_release, ReleaseConflict
from app.services.memory_ledger import MemoryIntegrityError
from app.services.route_learning import get_memory

router = APIRouter(prefix='/learning', tags=['governed learning'])
# Reading follows the site's sign-in setting (open on the public demo); approval never does.
VIEWER = require_role_user('viewer')


class Candidate(BaseModel):
    robot_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=120)
    notice: str = Field('', max_length=700)
    source_url: str = Field('', max_length=400)
    evidence_ids: list[str] = Field(min_length=1, max_length=100)
    ttl_s: float = Field(3600, ge=60, le=86400, allow_inf_nan=False)
    lesson_id: str | None = Field(None, max_length=64)
    expected_digest: str | None = Field(None, max_length=64)


class Transition(BaseModel):
    robot_id: str = Field(min_length=1, max_length=128)
    expected_digest: str = Field(min_length=64, max_length=64)


async def current(robot_id=None):
    from app.api.routes_authority import _sim
    try:
        telemetry = await _sim().get_telemetry(robot_id=robot_id)
        world = await _sim().get_world()
        if robot_id and telemetry.get('robot_id') != robot_id:
            raise ValueError('recipient_identity_mismatch')
        context = context_from_state(telemetry, policy_version_hash())
        if not context or any(world.get(k) != context[k] for k in ('site_id', 'map_version')):
            raise ValueError('current_context_unavailable')
        return context, world, telemetry
    except Exception as exc:
        raise HTTPException(503, 'Current simulator context unavailable') from exc


def unavailable(exc):
    if isinstance(exc, MemoryIntegrityError):
        raise HTTPException(503, 'Learning integrity verification failed; sharing unavailable') from exc
    raise HTTPException(409, str(exc)) from exc


@router.get('')
async def overview(robot_id: str | None = None, user=Depends(VIEWER)):
    context, world, telemetry = await current(robot_id)
    try:
        service, memory = get_learning_release(), get_memory()
        evidence = memory.release_evidence(context)
        eligibility = service.retrieve(context, telemetry['robot_id'], memory)
        return dict(context=context, robot_id=telemetry['robot_id'], lessons=service.list(),
                    evidence=evidence, eligibility={k: v for k, v in eligibility.items() if k != 'penalties'},
                    memory_integrity_error=memory.integrity_error)
    except (ValueError, MemoryIntegrityError) as exc:
        unavailable(exc)


@router.post('/candidates')
async def propose(body: Candidate, user=Depends(OPERATOR_ALWAYS)):
    context, _, _ = await current(body.robot_id)
    try:
        values = body.model_dump()
        values.pop('robot_id')
        return get_learning_release().propose(actor=user, context=context, origin_robot_id=body.robot_id, **values)
    except (ValueError, MemoryIntegrityError) as exc:
        unavailable(exc)


@router.post('/{lesson_id}/{version}/{action}')
async def transition(lesson_id: str, version: int, action: str, body: Transition,
                     user=Depends(OPERATOR_ALWAYS)):
    if action not in ('evaluate', 'approve', 'release', 'withdraw'):
        raise HTTPException(404, 'Unknown learning action')
    # Withdrawal must remain possible even if the simulator is offline.
    context, world = None, None
    if action != 'withdraw':
        context, world, _ = await current(body.robot_id)
    try:
        return get_learning_release().transition(lesson_id, version, action, body.expected_digest, user,
                                                 context=context, world=world, memory=get_memory())
    except (ValueError, MemoryIntegrityError) as exc:
        unavailable(exc)
