import asyncio
import time

from app.autonomy.experience import context_from_state
from app.policies.versioning import policy_version_hash
from app.services.route_learning import RouteMemory
from app.services.environment_lifecycle import get_lifecycle, constraints_key
from app.services.run_service import RunService
from test_execution_authority import sim_module, sim, authority, _issue, _raw_command
from test_controller_redemption import prepare


def run(coro):
    return asyncio.run(coro)


def test_scenario_change_stops_fences_invalidates_and_replans(authority, sim, monkeypatch):
    from app.services import route_learning
    mem = RouteMemory(authority.db_path, authority.secret)
    monkeypatch.setattr(route_learning, "_memory", mem)
    before = run(sim.get_telemetry())
    old_context = context_from_state(before, policy_version_hash())
    mem.record("robot-A", [((6, 7), 3.0, "STOP")], context=old_context, source_robot_id="robot-A")
    action, token = run(_issue(authority, sim, {"x": 6, "y": 3.5}))
    prepare(authority, action, token)
    run(sim.post_scenario("clear"))
    current = run(sim.get_telemetry())
    context = context_from_state(current, policy_version_hash())
    assert current["target"] is None
    assert context["map_version"] != old_context["map_version"]
    assert run(sim.send_command(_raw_command(action, token)))["reason"] == "controller_context_changed"
    assert mem.load(context=old_context)[0] == {}
    assert any(e["reason"] == "scenario:clear" for e in get_lifecycle().status()["events"])
    mem.record("fresh", [((6, 7), 1.0, "SLOW")], context=context, source_robot_id="robot-B")
    mem.record("fresh-peer", [((6, 7), 1.0, "SLOW")], context=context, source_robot_id="robot-A")
    assert mem.load(context=context)[0]
    events = []
    svc = RunService()
    svc.sim = sim
    svc._plans["run"] = [{"x": 999, "y": 999}]
    svc._plan_contexts["run"] = {"context": old_context, "constraints": constraints_key(before)}
    monkeypatch.setattr(svc, "_append_event", lambda db, rid, kind, data: events.append((kind, data)))
    assert run(svc._refresh_environment_plan(None, "run", current, {"x": 6, "y": 3.5}))
    assert svc._plans["run"] and svc._plans["run"][-1]["x"] == 6
    assert events[0][0] == "ENVIRONMENT_CHANGE" and events[0][1]["action"] == "replanned"
