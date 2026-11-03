"""Mixed platforms use real telemetry, authority and controller checks."""
import asyncio
import importlib.util
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from app.autonomy.core import Rejected
from app.autonomy.robot_profiles import AMR, HUMANOID, move_violation
from app.services.execution_authority import ExecutionAuthority
from app.services.sim_adapter import SimAdapter
from app.services.run_service import RobotView
from app.services.site_router import route_plan, repair_plan
from bench.world import load_layout
from app.policies.versioning import policy_version_hash


@pytest.fixture
def mixed(monkeypatch, tmp_path, bind_redemption):
    monkeypatch.setenv('SITE_LAYOUT', 'pharma')
    monkeypatch.delenv('SIM_FLEET', raising=False)
    directory = Path(__file__).resolve().parents[2] / 'sim/warehouse_sim'
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location('mixed_sim_test', directory / 'server.py')
    server = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = server
    spec.loader.exec_module(server)
    from app.autonomy.controller import ControllerJournal
    import os
    server._journal = ControllerJournal(str(tmp_path / 'controller.db'))
    authority = ExecutionAuthority(secret=os.environ['PERMIT_SECRET'], db_path=str(tmp_path / 'authority.db'))
    bind_redemption(server, authority)
    adapter = SimAdapter(base_url='http://sim')
    adapter._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url='http://sim')
    with TestClient(server.app) as client:
        yield server, client, adapter, authority
    sys.modules.pop(spec.name, None)


def test_mixed_identity_controller_cap_and_independent_motion(mixed):
    server, client, adapter, authority = mixed
    fleet = client.get('/fleet').json()['robots']
    assert [r['robot_kind'] for r in fleet] == ['amr', 'amr', 'humanoid']
    assert fleet[2]['robot_profile']['max_speed_mps'] == .3
    positions={r['robot_id']:(r['x'],r['y']) for r in fleet}
    for selected in positions:
        tel=client.get('/telemetry',params={'robot_id':selected}).json()
        assert {r['robot_id']:(r['x'],r['y']) for r in tel['idle_robots']} == {
            rid:xy for rid,xy in positions.items() if rid!=selected}
    async def go():
        view = RobotView(adapter, 'robot-3')
        tel = await view.get_telemetry()
        assert tel['capability_profile_version'] == HUMANOID.version
        assert {r['robot_id'] for r in tel['idle_robots']} == {'robot-1','robot-2'}
        authority.observe(tel, robot_id='robot-3')
        before = [(r['x'],r['y']) for r in fleet[:2]]
        args=dict(run_id='mixed-run', mission_id='mixed-mission', intent='MOVE_TO', decision='APPROVED', policy_version=policy_version_hash(), robot_id='robot-3')
        with pytest.raises(Rejected, match='capability_speed_limit'):
            authority.authorize(**args, params=dict(x=18,y=8,max_speed=.5))
        # A payload cannot choose a faster profile at the controller.
        denied = client.post('/command', json=dict(intent='MOVE_TO',params=dict(x=18,y=8,max_speed=.5,robot_kind='amr'),action=dict(robot_id='robot-3')))
        assert denied.status_code==403 and denied.json()['detail']=='capability_speed_limit'
        action, token = authority.authorize(**args, params=dict(x=18,y=8,max_speed=.3))
        result = await authority.dispatch('mixed-run', action, token, view)
        assert result['ok'], result
        deadline=asyncio.get_running_loop().time()+3
        moved=await view.get_telemetry()
        while moved['y']>=tel['y'] and asyncio.get_running_loop().time()<deadline:
            await asyncio.sleep(.05)
            moved=await view.get_telemetry()
        assert moved['y'] < tel['y'] and 0 < moved['speed'] <= .3
        assert moved['robot_contacts']==0
        after = client.get('/fleet').json()['robots']
        assert [(r['x'],r['y']) for r in after[:2]] == before
        await view.send_command(dict(intent='STOP',params={}))
        assert (await view.get_telemetry())['target'] is None
    asyncio.run(go())


def test_profile_bound_context_cannot_be_relaxed(mixed):
    _, _, adapter, authority = mixed
    async def go():
        view=RobotView(adapter,'robot-3')
        tel=await view.get_telemetry()
        tel['capability_profile_version']=AMR.version
        authority.observe(tel,robot_id='robot-3')
        a,k=authority.authorize(run_id='forged-profile',mission_id='forged-mission',intent='MOVE_TO',params=dict(x=18,y=8,max_speed=.3),decision='APPROVED',policy_version=policy_version_hash(),robot_id='robot-3')
        result=await authority.dispatch('forged-profile',a,k,view)
        assert not result.get('ok'), result
        assert 'context' in str(result).lower() or 'profile' in str(result).lower(), result
        assert (await view.get_telemetry())['target'] is None
    asyncio.run(go())


def test_humanoid_routes_and_repaired_legs_keep_platform_cap():
    site=load_layout(site='pharma')
    start=dict(x=18,y=9,capability_profile_version=HUMANOID.version)
    for bay in site['bays']:
        route=route_plan(site,start,bay,site['zone_speed_limits'])
        assert route and all(w['max_speed'] <= .3 for w in route)
        repaired,_=repair_plan(site,start,[dict(x=bay['x'],y=bay['y'],max_speed=.5)],site['zone_speed_limits'])
        assert all(w['max_speed'] <= .3 for w in repaired)
    assert not move_violation(AMR,dict(max_speed=.5))
    for speed in (.31,float('nan'),float('inf'),-1,'bad'):
        assert move_violation(HUMANOID,dict(max_speed=speed))


def test_gate_applies_humanoid_cap_before_authority():
    from app.policies.rules_python import evaluate_policies
    from app.schemas.governance import ActionProposal
    state=dict(x=3,y=3.5,zone='aisle',nearest_obstacle_m=10,human_detected=False,
               capability_profile_version=HUMANOID.version)
    fast=evaluate_policies(state,ActionProposal(intent='MOVE_TO',params=dict(x=4,y=3.5,max_speed=.5)))
    bounded=evaluate_policies(state,ActionProposal(intent='MOVE_TO',params=dict(x=4,y=3.5,max_speed=.3)))
    assert 'SAFE_SPEED_01' in fast.policy_hits
    assert 'SAFE_SPEED_01' not in bounded.policy_hits
