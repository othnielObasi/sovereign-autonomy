"""Operational human review and route replacement; no safety-limit overrides."""
import asyncio
import json
import math
import time
from datetime import datetime, timezone, timedelta

from app.autonomy.core import Rejected
from app.autonomy.permit import controller_context
from app.db.models import Event, GovernanceDecisionRecord, Mission, OperatorApproval
from app.policies.versioning import policy_version_hash
from app.schemas.governance import ActionProposal, GovernanceDecision
from app.services import operator_approval as approvals
from app.services.execution_authority import get_authority


def latest_review(db, run):
    event = db.query(Event).filter(Event.run_id == run.id, Event.type == 'DECISION').order_by(Event.ts.desc()).first()
    payload = json.loads(event.payload_json) if event else {}
    decision = GovernanceDecision.model_validate(payload.get('governance') or {'decision':'DENIED'})
    receipt = db.query(GovernanceDecisionRecord).filter(GovernanceDecisionRecord.run_id == run.id).order_by(GovernanceDecisionRecord.id.desc()).first()
    age = (datetime.now(timezone.utc) - event.ts.replace(tzinfo=timezone.utc)).total_seconds() if event else float('inf')
    reason = ('Run must be paused' if run.status != 'paused' else
              'No eligible uncertainty review' if not approvals.reviewable(decision) else
              'Review expired; request a fresh decision' if age > approvals.APPROVAL_TTL_S else
              'Review policy changed' if not receipt or receipt.policy_version != policy_version_hash() else None)
    return {'eligible': reason is None, 'reason': reason, 'decision_event_id': event.id if event else None,
            'proposal': payload.get('proposal'), 'governance': decision.model_dump(),
            'telemetry': payload.get('context',{}).get('telemetry'),
            'receipt_id': receipt.id if receipt else None}


def guard(svc, run_id, run):
    authority = get_authority()
    if not authority.enabled:
        raise Rejected('permit_secret_not_configured')
    from app.config import settings
    keys = {('global','*'), ('robot',svc.robot_for(run_id)), ('mission',run.mission_id),
            ('agent',f'planner:{settings.planner_provider}')}
    if keys.intersection(authority.kills.active()):
        raise Rejected('kill_switch_active')
    return authority


async def hold(db, svc, run):
    """Fence immediately, settle the prior tick, then verify the controller stop."""
    if run.status not in ('running','paused'):
        raise Rejected('run_not_active')
    svc._pause_flags.setdefault(run.id, asyncio.Event()).set()
    db.refresh(run)
    if run.status not in ('running','paused'):
        raise Rejected('run_not_active')
    run.status = 'paused'
    mission = db.query(Mission).filter(Mission.id == run.mission_id).one()
    mission.status = 'paused'
    db.commit()
    sim = svc.sim_for(run.id)
    result = await sim.send_command({'intent':'STOP','params':{}})
    if not (result.get('ok') or result.get('stopped')):
        raise Rejected('operator_stop_not_acknowledged')
    # Do not cancel a dispatcher awaiting a controller acknowledgement. STOP
    # fences its old generation; let it record the definite admission/refusal.
    task = svc._tasks.get(run.id)
    if task and not task.done():
        idle = svc._tick_idle.get(run.id)
        if idle is None:
            raise Rejected('operator_tick_state_missing')
        try:
            await asyncio.wait_for(idle.wait(),timeout=svc.AGENT_PROPOSAL_TIMEOUT+5)
        except asyncio.TimeoutError as exc:
            raise Rejected('operator_tick_not_settled') from exc
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        result = await sim.send_command({'intent':'STOP','params':{}})
        if not (result.get('ok') or result.get('stopped')):
            raise Rejected('operator_stop_not_acknowledged')
    svc._tasks.pop(run.id,None)
    deadline = time.monotonic() + 3.0
    while True:
        telemetry = await sim.get_telemetry()
        speed = telemetry.get('speed')
        if (isinstance(speed,(int,float)) and math.isfinite(speed)
                and abs(speed) <= .01 and not telemetry.get('target')):
            break
        if time.monotonic() >= deadline:
            raise Rejected('operator_stop_not_verified')
        await asyncio.sleep(.05)
    if telemetry.get('robot_id') != svc.robot_for(run.id) or controller_context(telemetry) is None:
        raise Rejected('operator_telemetry_context_missing')
    db.refresh(run)
    if run.status != 'paused':
        raise Rejected('operator_run_changed')
    from app.services.site_intel.service import site_intel
    from app.services.perception import perception
    telemetry = perception.apply(site_intel.observe(telemetry))
    authority = guard(svc, run.id, run)
    authority.reconcile_in_doubt(run.mission_id, telemetry)
    authority.observe(telemetry, robot_id=svc.robot_for(run.id))
    return telemetry, mission


async def replan(db, svc, run, actor, reason):
    guard(svc, run.id, run)
    try:
        telemetry, mission = await hold(db, svc, run)
    except Exception:
        if run.status == 'paused':
            svc._plans[run.id] = []
            svc._environment_holds.add(run.id)
            svc._append_event(db,run.id,'PLAN',{'source':'operator_replan',
                'plan':{'waypoints':[]},'holding':True,'reason':'Stop could not be verified; old plan discarded'})
            db.commit()
        raise
    # Discard before doing I/O: failure must never leave a usable obsolete route.
    svc._plans[run.id] = []
    svc._environment_holds.add(run.id)
    svc._review_proposals.pop(run.id, None)
    db.query(OperatorApproval).filter(OperatorApproval.run_id == run.id).delete()
    svc._append_event(db, run.id, 'INTERVENTION', {'type':'OPERATOR_REPLAN', 'actor':actor,
        'reason':reason, 'status':'paused', 'old_plan_discarded':True})
    db.commit()
    try:
        await svc._refresh_environment_plan(db, run.id, telemetry, json.loads(mission.goal_json), force=True)
    except Exception:
        svc._plans[run.id] = []
        svc._environment_holds.add(run.id)
        svc._append_event(db, run.id, 'PLAN', {'source':'operator_replan', 'plan':{'waypoints':[]},
            'holding':True, 'reason':'Route replacement failed; old plan discarded'})
        db.commit()
        raise
    count = len(svc._plans.get(run.id, []))
    return {'ok':True, 'action':'replanned' if count else 'holding_no_route',
            'run_id':run.id, 'status':'paused', 'waypoints':count, 'resume_required':True}


async def approve_review(db, svc, run, actor, reason, event_id, expected_proposal=None):
    guard(svc, run.id, run)
    review = latest_review(db, run)
    if not event_id or event_id != review['decision_event_id']:
        raise Rejected('review_decision_changed_or_missing')
    if not review['eligible']:
        raise Rejected(review['reason'])
    for entry in db.query(Event).filter(Event.run_id == run.id, Event.type == 'INTERVENTION'):
        body = json.loads(entry.payload_json)
        if body.get('type') == 'OPERATOR_REVIEW_APPROVED' and body.get('decision_event_id') == event_id:
            raise Rejected('review_already_approved')
    proposal = ActionProposal.model_validate(review['proposal'])
    if expected_proposal is not None:
        expected = ActionProposal.model_validate(expected_proposal)
        if (expected.intent, expected.params) != (proposal.intent, proposal.params):
            raise Rejected('review_proposal_mismatch')
    receipt = db.get(GovernanceDecisionRecord, review['receipt_id'])
    if not svc.gov.verify_receipt(db, run.id, receipt.id).get('valid'):
        raise Rejected('review_receipt_invalid')
    recorded = ActionProposal.model_validate(json.loads(receipt.proposal_json))
    if (recorded.intent,recorded.params) != (proposal.intent,proposal.params):
        raise Rejected('review_receipt_mismatch')
    telemetry, _ = await hold(db, svc, run)
    # Nothing may supersede the decision the operator selected while STOP was pending.
    current = latest_review(db, run)
    if current['decision_event_id'] != event_id or not current['eligible']:
        raise Rejected('review_decision_changed')
    original = review.get('telemetry') or {}
    for key in ('robot_id','site_id','map_version','capability_profile_version','boot_id'):
        if original.get(key) != telemetry.get(key):
            raise Rejected('review_environment_changed')
    if math.hypot(float(original.get('x',1e9))-telemetry['x'],float(original.get('y',1e9))-telemetry['y']) > .2:
        raise Rejected('review_robot_moved')
    decision = svc.gov.evaluate(telemetry, proposal)
    if not approvals.reviewable(decision):
        raise Rejected('review_no_longer_eligible')
    key = approvals.review_key(telemetry,proposal,decision,policy_version_hash())
    if key is None:
        raise Rejected('review_context_missing')
    # Repeated clicks cannot extend an existing approval lease.
    row = approvals.matching_review(db,run.id,telemetry,proposal,decision,policy_version_hash())
    if row is None:
        now = datetime.now(timezone.utc)
        row = OperatorApproval(run_id=run.id,proposal_hash=key,approved_by=actor,
            approved_at=now,expires_at=now+timedelta(seconds=approvals.APPROVAL_TTL_S),notes=reason)
        db.add(row)
        db.flush()
        approvals.seal_review(row,event_id,reason)
    svc._append_event(db,run.id,'INTERVENTION',{'type':'OPERATOR_REVIEW_APPROVED','actor':actor,
        'reason':reason,'decision_event_id':event_id,'approval_id':row.id,'proposal_hash':key,
        'proposal':proposal.model_dump(),'fresh_governance':decision.model_dump(),
        'expires_at':row.expires_at.isoformat(),'context':controller_context(telemetry)})
    db.commit()
    svc._review_proposals[run.id] = proposal
    return {'ok':True,'action':'review_approved','run_id':run.id,'status':'paused',
            'approval_id':row.id,'proposal_hash':key,'expires_at':row.expires_at.isoformat()}
