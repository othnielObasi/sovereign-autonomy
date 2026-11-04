"""Real API/gate/authority paths for scoped review and route replacement."""
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import routes_operator as api
from app.auth.jwt import create_access_token
from app.autonomy.core import Rejected
from app.autonomy.experience import world_identity, context_from_state
from app.autonomy.robot_profiles import AMR
from app.db.models import Event, Mission, Run, OperatorApproval
from app.db.session import Base
from app.deps import get_db
from app.policies.versioning import policy_version_hash
from app.schemas.governance import ActionProposal
from app.services import execution_authority as ea
from app.services import operator_controls as controls
from app.services.environment_lifecycle import constraints_key
from app.services.run_service import RunService
from app.utils.time import utc_now
from bench.world import load_layout


class Sim:
    def __init__(self):
        self.commands=[]
        self.world=load_layout(site='warehouse')
        self.world=dict(self.world,**world_identity(self.world),capability_profile_version=AMR.version)
        self.state=dict(self.world,robot_id='robot-1',x=3.,y=3.5,speed=0.,target=None,
            zone='aisle',nearest_obstacle_m=10.,human_detected=True,human_conf=.4,
            human_distance_m=10.,walking_humans=[],obstacles=[],site_constraints=[],
            boot_id='operator-test-boot',generation=0)
        self.state.pop('racks',None)
    async def get_world(self):return self.world
    async def get_telemetry(self):return dict(self.state)
    async def send_command(self,cmd):
        self.commands.append(cmd)
        if cmd['intent']=='STOP':self.state.update(speed=0.,target=None,generation=self.state['generation']+1)
        return {'ok':True}


@pytest.fixture
def ops(monkeypatch,tmp_path):
    from app.policies import site_map
    monkeypatch.setattr(site_map,'RACKS',site_map.RACKS)
    monkeypatch.setattr(site_map,'SITE_NAME',site_map.SITE_NAME)
    engine=create_engine('sqlite:///'+str(tmp_path/'app.db'),connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    factory=sessionmaker(bind=engine,autoflush=False)
    db=factory()
    authority=ea.ExecutionAuthority(secret=os.environ['PERMIT_SECRET'],db_path=str(tmp_path/'authority.db'))
    monkeypatch.setattr(ea,'_authority',authority)
    import app.db.session as ds
    monkeypatch.setattr(ds,'SessionLocal',factory)
    svc=RunService();svc.sim=Sim();svc._run_robot['op-run']='robot-1'
    launches=[];monkeypatch.setattr(svc,'_launch_loop',lambda rid:launches.append(rid))
    monkeypatch.setattr(api,'service',lambda:svc)
    db.add(Mission(id='op-mission',title='Operator test',goal_json=json.dumps({'x':12,'y':8,'robot_id':'robot-1'}),status='paused',created_at=utc_now()))
    db.add(Run(id='op-run',mission_id='op-mission',status='paused',started_at=utc_now(),planning_mode='fallback'));db.commit()
    svc._plans['op-run']=[{'x':6.,'y':3.5,'max_speed':.3}]
    app=FastAPI();app.include_router(api.router)
    def session():
        s=factory()
        try:yield s
        finally:s.close()
    app.dependency_overrides[get_db]=session
    with TestClient(app) as client:
        yield db,svc,authority,client,launches,factory
    db.close();engine.dispose()


def headers(role='operator'):
    return {'Authorization':'Bearer '+create_access_token('reviewer',role=role)}


def record_review(db,svc,state=None,params=None):
    state=state or dict(svc.sim.state)
    proposal=ActionProposal(intent='MOVE_TO',params=params or {'x':6.,'y':3.5,'max_speed':.3},rationale='Review uncertainty')
    decision=svc.gov.evaluate_and_record(db,'op-run',state,proposal)
    event=svc._append_event(db,'op-run','DECISION',{'context':{'telemetry':state},'proposal':proposal.model_dump(),'governance':decision.model_dump()});db.commit()
    return event,proposal


def request(client,action,event=None):
    return client.post('/operator/override',headers=headers(),json={'run_id':'op-run','action':action,'reason':'Checked the current situation','decision_event_id':event.id if event else None})


def test_replan_replaces_and_persists_route_without_resuming(ops):
    db,svc,_,client,launches,_=ops
    svc._plans['op-run']=[{'x':99,'y':99,'max_speed':.9}]
    result=request(client,'replan');assert result.status_code==200,result.text
    assert result.json()['status']=='paused' and result.json()['waypoints']>1
    assert svc.sim.commands[0]['intent']=='STOP' and not launches
    assert svc._plans['op-run'][-1]['x']==12 and svc._plans['op-run'][-1]['y']==8
    restored=RunService();restored._restore_plan(db,'op-run')
    assert restored._plans['op-run']==svc._plans['op-run']
    assert db.query(Event).filter_by(type='PLAN').count()==1


def test_no_route_discards_old_plan_and_holds(ops,monkeypatch):
    db,svc,_,client,launches,_=ops
    monkeypatch.setattr('app.services.site_router.route_plan',lambda *a,**k:None)
    result=request(client,'replan');assert result.status_code==200,result.text
    assert result.json()['action']=='holding_no_route' and svc._plans['op-run']==[]
    assert 'op-run' in svc._environment_holds and not launches
    plan=json.loads(db.query(Event).filter_by(type='PLAN').one().payload_json)
    assert plan['plan']['waypoints']==[] and plan['holding']


def test_replan_failure_preserves_hold_and_discards_plan(ops,monkeypatch):
    db,svc,_,client,launches,_=ops
    async def unavailable():raise ConnectionError()
    monkeypatch.setattr(svc.sim,'get_world',unavailable)
    result=request(client,'replan');assert result.status_code==503
    assert svc._plans['op-run']==[] and not launches
    db.expire_all();assert db.get(Run,'op-run').status=='paused'


def test_force_review_resumes_only_exact_fresh_eligible_action(ops):
    db,svc,_,client,launches,_=ops
    event,proposal=record_review(db,svc)
    assert client.get('/operator/review/op-run').json()['eligible']
    result=request(client,'force_approve',event);assert result.status_code==200,result.text
    assert launches==['op-run'] and result.json()['status']=='running'
    fresh=asyncio.run(svc.sim.get_telemetry())
    decision=svc.gov.evaluate_and_record(db,'op-run',fresh,proposal)
    assert decision.decision=='APPROVED' and any('Operator review' in r for r in decision.reasons)
    changed=proposal.model_copy(update={'params':dict(proposal.params,x=7.)})
    assert svc.gov.evaluate_and_record(db,'op-run',fresh,changed).decision!='APPROVED'


@pytest.mark.parametrize('change',[{'generation':99},{'boot_id':'new-boot'},{'map_version':'new-map'}, {'capability_profile_version':'other'}, {'site_constraints':[{'id':'new','x':20,'y':20,'radius':1}]}])
def test_approval_is_bound_to_controller_and_environment(ops,change):
    db,svc,_,client,_,_=ops;event,proposal=record_review(db,svc)
    assert request(client,'force_approve',event).status_code==200
    fresh=dict(svc.sim.state,**change)
    assert svc.gov.evaluate_and_record(db,'op-run',fresh,proposal).decision!='APPROVED'


def test_approval_expiry_and_revocation_are_effective(ops):
    db,svc,authority,client,_,_=ops;event,proposal=record_review(db,svc)
    assert request(client,'force_approve',event).status_code==200
    state=dict(svc.sim.state)
    authority.kills.activate('mission','op-mission');authority.kills.reset('mission','op-mission',authorized=True)
    assert svc.gov.evaluate_and_record(db,'op-run',state,proposal).decision!='APPROVED'
    row=db.query(OperatorApproval).one();row.expires_at=utc_now()-timedelta(seconds=1);db.commit()
    assert svc.gov.evaluate_and_record(db,'op-run',state,proposal).decision!='APPROVED'


@pytest.mark.parametrize('change',[{'nearest_obstacle_m':.1},{'human_distance_m':.2,'human_conf':.95},{'x':-1}])
def test_new_hard_failure_cannot_be_reviewed(ops,change):
    db,svc,_,client,launches,_=ops;event,_=record_review(db,svc)
    svc.sim.state.update(change)
    result=request(client,'force_approve',event);assert result.status_code==409,result.text
    assert not launches and db.query(OperatorApproval).count()==0


def test_speed_violation_is_not_eligible_even_when_soft(ops):
    db,svc,_,client,_,_=ops;event,_=record_review(db,svc,params={'x':6,'y':3.5,'max_speed':2.})
    assert not client.get('/operator/review/op-run').json()['eligible']
    assert request(client,'force_approve',event).status_code==409


def test_old_changed_and_duplicate_review_requests_are_refused(ops):
    db,svc,_,client,_,_=ops;event,proposal=record_review(db,svc)
    assert request(client,'force_approve').status_code==409
    # /approve grants a lease but leaves the robot paused.
    body={'run_id':'op-run','proposal':proposal.model_dump(),'decision_event_id':event.id,'notes':'Reviewed uncertainty'}
    assert client.post('/operator/approve',headers=headers(),json=body).status_code==200
    assert client.post('/operator/approve',headers=headers(),json=body).status_code==409
    assert len(svc.sim.commands)==1


@pytest.mark.parametrize('scope,ident',[('global','*'),('robot','robot-1'),('mission','op-mission'),('agent','planner:fallback')])
def test_kill_locks_block_operator_actions(ops,scope,ident,monkeypatch):
    from app.config import settings
    if scope=='agent':ident=f'planner:{settings.planner_provider}'
    _,svc,authority,client,_,_=ops;authority.kills.activate(scope,ident)
    assert request(client,'replan').status_code==409
    assert not svc.sim.commands


def test_roles_states_and_in_progress_guards(ops):
    db,svc,_,client,_,_=ops
    body={'run_id':'op-run','action':'replan','reason':'Reviewed route'}
    assert client.post('/operator/override',json=body).status_code==401
    assert client.post('/operator/override',headers=headers('viewer'),json=body).status_code==403
    svc._operator_busy.add('op-run')
    with pytest.raises(Rejected,match='operator_action_in_progress'):
        asyncio.run(svc.resume_run(db,'op-run'))
    svc._operator_busy.clear()
    for state in ('completed','stopped','failed','planning'):
        db.get(Run,'op-run').status=state;db.commit()
        assert request(client,'replan').status_code==409
    assert not svc.sim.commands


def test_expired_recorded_review_never_grants_a_new_lease(ops):
    db,svc,_,client,_,_=ops;event,_=record_review(db,svc)
    event.ts=utc_now()-timedelta(seconds=121);db.commit()
    assert request(client,'force_approve',event).status_code==409
    assert not svc.sim.commands


def test_expired_lease_stops_approving_the_same_action(ops):
    db,svc,_,client,_,_=ops;event,proposal=record_review(db,svc)
    assert request(client,'force_approve',event).status_code==200
    state=dict(svc.sim.state)
    assert svc.gov.evaluate_and_record(db,'op-run',state,proposal).decision=='APPROVED'
    db.query(OperatorApproval).one().expires_at=utc_now()-timedelta(seconds=1);db.commit()
    assert svc.gov.evaluate_and_record(db,'op-run',state,proposal).decision=='NEEDS_REVIEW'


def test_lease_cannot_clear_new_hard_failure_or_changed_policy(ops):
    from app.policies.params import active_params
    db,svc,_,client,_,_=ops;event,proposal=record_review(db,svc)
    assert request(client,'force_approve',event).status_code==200
    state=dict(svc.sim.state,nearest_obstacle_m=.01)
    decision=svc.gov.evaluate_and_record(db,'op-run',state,proposal)
    assert decision.hard_fail and decision.decision!='APPROVED'
    assert svc.gov.evaluate_and_record(db,'op-run',dict(svc.sim.state),proposal,
        params=dict(active_params(),MIN_HUMAN_CONF=.7)).decision!='APPROVED'


def test_in_flight_tick_settles_before_it_is_cancelled(ops):
    db,svc,_,_,_,_=ops
    async def go():
        entered=asyncio.Event();stopped=asyncio.Event();cancelled=[]
        idle=asyncio.Event();svc._tick_idle['op-run']=idle
        async def old_tick():
            try:
                entered.set();await stopped.wait();idle.set()
                await asyncio.Event().wait()
            finally:cancelled.append(True)
        svc._tasks['op-run']=asyncio.create_task(old_tick());await entered.wait()
        original=svc.sim.send_command
        async def command(cmd):
            result=await original(cmd)
            stopped.set()
            return result
        svc.sim.send_command=command
        result=await controls.replan(db,svc,db.get(Run,'op-run'),'reviewer','Replace blocked route')
        assert cancelled and result['status']=='paused' and svc._tasks.get('op-run') is None
        assert svc.sim.commands[0]['intent']=='STOP'
    asyncio.run(go())


# A real controller callback admits a reviewed move; test-only uncertain sensor
# observations exercise the review branch without introducing a production bypass.
from test_mixed_fleet import mixed


def test_review_to_real_permit_motion_and_replan_hold(ops,mixed,monkeypatch):
    import time
    db,svc,_,client,_,factory=ops
    server,_,adapter,authority=mixed
    monkeypatch.setattr(ea,'_authority',authority)
    svc.sim=adapter;svc._run_robot['op-run']='robot-3'
    original=adapter.get_telemetry
    async def uncertain(robot_id=None):
        tel=await original(robot_id=robot_id)
        tel.update(human_detected=True,human_conf=.4,human_distance_m=10.,walking_humans=[],human=None)
        return tel
    monkeypatch.setattr(adapter,'get_telemetry',uncertain)
    mission=db.get(Mission,'op-mission');mission.goal_json=json.dumps({'x':18,'y':2.5,'robot_id':'robot-3'});db.commit()
    state=asyncio.run(uncertain('robot-3'))
    # A short move from wherever robot-3 parks, so the test does not depend on the parking coordinate
    event,proposal=record_review(db,svc,state,{'x':float(state['x']),'y':float(state['y'])-1.,'max_speed':.3})
    assert json.loads(event.payload_json)['governance']['decision']=='NEEDS_REVIEW'
    svc._plans['op-run']=[dict(proposal.params),{'x':18.,'y':2.5,'max_speed':.3}]
    svc._plan_contexts['op-run']={'context':context_from_state(state,policy_version_hash()),'constraints':constraints_key(state)}
    svc._launch_loop=RunService._launch_loop.__get__(svc)
    result=request(client,'force_approve',event);assert result.status_code==200,result.text
    deadline=time.monotonic()+8;moved=False
    try:
        while time.monotonic()<deadline:
            t=asyncio.run(uncertain('robot-3'))
            if t['y'] < state['y']-.05:
                assert 0<t['speed']<=.3;moved=True;break
            time.sleep(.1)
        assert moved,'Reviewed move never reached the real controller'
        session=factory()
        try:
            events=[json.loads(e.payload_json) for e in session.query(Event).filter_by(run_id='op-run',type='AUTHORITY')]
            assert any(e.get('event')=='permit_used' for e in events)
        finally:session.close()
    finally:
        held=request(client,'replan');assert held.status_code==200,held.text
    assert held.json()['status']=='paused'
    t=asyncio.run(uncertain('robot-3'));assert t['speed']==0 and t['target'] is None
    assert svc._plans['op-run'] and all(p['max_speed']<=.3 for p in svc._plans['op-run'])


def test_candidate_replay_ignores_live_operator_approval(ops):
    from app.policies.params import active_params
    db,svc,_,client,_,_=ops;event,proposal=record_review(db,svc)
    assert request(client,'force_approve',event).status_code==200
    state=dict(svc.sim.state)
    assert svc.gov.evaluate_and_record(db,'op-run',state,proposal).decision=='APPROVED'
    assert svc.gov.evaluate_and_record(db,'op-run',state,proposal,params=active_params()).decision=='NEEDS_REVIEW'


@pytest.mark.parametrize('field,value',[
    ('approved_by','forged-reviewer'),('notes','unsigned fake approval'),('notes','[]'),
    ('expires_at',datetime.now(timezone.utc)+timedelta(days=2)),
])
def test_stored_approval_tampering_cannot_authorize_motion(ops,field,value):
    db,svc,_,client,_,_=ops;event,proposal=record_review(db,svc)
    assert request(client,'force_approve',event).status_code==200
    state=dict(svc.sim.state)
    assert svc.gov.evaluate_and_record(db,'op-run',state,proposal).decision=='APPROVED'
    setattr(db.query(OperatorApproval).one(),field,value);db.commit()
    assert svc.gov.evaluate_and_record(db,'op-run',state,proposal).decision=='NEEDS_REVIEW'


def test_unsigned_row_with_correct_context_is_not_a_review_lease(ops):
    from app.services.operator_approval import review_key
    db,svc,_,_,_,_=ops;_,proposal=record_review(db,svc)
    state=dict(svc.sim.state);decision=svc.gov.evaluate(state,proposal)
    key=review_key(state,proposal,decision,policy_version_hash())
    db.add(OperatorApproval(run_id='op-run',proposal_hash=key,approved_by='forged',approved_at=utc_now(),expires_at=utc_now()+timedelta(seconds=120),notes='forged'));db.commit()
    assert svc.gov.evaluate_and_record(db,'op-run',state,proposal).decision=='NEEDS_REVIEW'


def test_replan_settles_a_delayed_controller_ack_without_losing_outcome(ops,mixed,monkeypatch):
    import threading
    db,svc,_,client,_,_=ops
    server,_,adapter,authority=mixed
    monkeypatch.setattr(ea,'_authority',authority)
    svc.sim=adapter;svc._run_robot['op-run']='robot-3'
    base_telemetry=adapter.get_telemetry
    async def clear(robot_id=None):
        tel=await base_telemetry(robot_id=robot_id)
        tel.update(human_detected=False,human_distance_m=10.,walking_humans=[],human=None)
        return tel
    monkeypatch.setattr(adapter,'get_telemetry',clear)
    # The controller has redeemed authority but has not yet admitted the action.
    redeemed=threading.Event();release=threading.Event();callback=server._post_redemption
    def delayed(envelope):
        result=callback(envelope);redeemed.set()
        assert release.wait(8),'Operator STOP did not release delayed acknowledgement'
        return result
    monkeypatch.setattr(server,'_post_redemption',delayed)
    send=adapter.send_command
    async def command(cmd):
        result=await send(cmd)
        if cmd['intent']=='STOP':release.set()
        return result
    monkeypatch.setattr(adapter,'send_command',command)
    mission=db.get(Mission,'op-mission');mission.goal_json=json.dumps({'x':18,'y':2.5,'robot_id':'robot-3'})
    db.get(Run,'op-run').status='running';db.commit()
    state=asyncio.run(clear('robot-3'))
    svc._plans['op-run']=[{'x':float(state['x']),'y':float(state['y'])-1.,'max_speed':.3}]   # short move from robot-3's parking
    svc._plan_contexts['op-run']={'context':context_from_state(state,policy_version_hash()),'constraints':constraints_key(state)}
    svc._launch_loop=RunService._launch_loop.__get__(svc)
    client.portal.call(svc._launch_loop,'op-run')
    try:
        assert redeemed.wait(8),'Dispatch never reached redemption'
        result=request(client,'replan')
        assert result.status_code==200,result.text
        assert result.json()['status']=='paused'
        assert authority.checkpoints.in_doubt('op-mission')==[]
        tel=asyncio.run(clear('robot-3'));assert tel['target'] is None and tel['speed']==0
    finally:release.set()


def test_resume_cannot_overtake_an_unsettled_paused_tick(ops):
    from types import SimpleNamespace
    db,svc,_,_,_,_=ops
    svc._tasks['op-run']=SimpleNamespace(done=lambda:False)
    svc._tick_idle['op-run']=asyncio.Event()
    svc._pause_flags['op-run']=asyncio.Event();svc._pause_flags['op-run'].set()
    with pytest.raises(Rejected,match='operator_tick_not_settled'):
        asyncio.run(svc.resume_run(db,'op-run'))
