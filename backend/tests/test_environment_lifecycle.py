import asyncio
import json

import pytest

from app.services.environment_lifecycle import EnvironmentLifecycle, constraints_key
from app.services.route_learning import RouteMemory

CONTEXT = {"site_id": "test-site", "map_version": "v1", "capability_profile_version": "amr-v1",
           "policy_version": "rules-v1"}
SECRET = b"lifecycle-tests-secret-0123456789abcdef"


@pytest.fixture
def setup(tmp_path):
    now = [1000.0]
    mem = RouteMemory(str(tmp_path / "lifecycle.db"), SECRET, clock=lambda: now[0])
    lifecycle = EnvironmentLifecycle(mem, clock=lambda: now[0])
    return mem, lifecycle, now


def record(mem, run="acquired", context=CONTEXT):
    mem.record(run, [((1, 2), 4.0, "STOP")], context=context, source_robot_id="robot-A")
    mem.record(run + '-peer', [((1, 2), 4.0, "STOP")], context=context, source_robot_id="robot-B")


@pytest.mark.parametrize("key", ["map_version", "policy_version", "capability_profile_version", "site_id"])
def test_context_changes_invalidate_old_observations_and_survive_restart(setup, key):
    mem, lifecycle, now = setup
    record(mem)
    lifecycle.observe(CONTEXT, CONTEXT["policy_version"])
    changed = dict(CONTEXT, **{key: "changed"})
    now[0] += 1
    assert lifecycle.observe(changed, changed["policy_version"])
    assert not mem.load(context=CONTEXT)[0]
    restarted = EnvironmentLifecycle(mem, clock=lambda: now[0])
    assert restarted.observe(changed, changed["policy_version"]) == []
    assert len(restarted.status()["events"]) == 1


def test_constraint_change_has_a_cutoff_and_fresh_experience_can_be_reused(setup):
    mem, lifecycle, now = setup
    record(mem)
    state = dict(CONTEXT, site_constraints=[])
    lifecycle.observe(state, "rules-v1")
    now[0] += 10
    state["site_constraints"] = [{"id": "spill", "x": 5, "y": 5, "radius": 2}]
    assert lifecycle.observe(state, "rules-v1")
    assert mem.load(context=CONTEXT)[0] == {}
    now[0] += 1
    record(mem, "fresh")
    assert mem.load(context=CONTEXT)[0]
    assert lifecycle.observe(state, "rules-v1") == []
    # A raw telemetry read lacking constraints must not undo effective zones.
    assert lifecycle.observe(CONTEXT, "rules-v1") == []


def test_source_event_is_processed_even_when_backend_missed_the_old_snapshot(setup):
    mem, lifecycle, now = setup
    record(mem)
    current = dict(CONTEXT, map_version="v2")
    source_old = {k: v for k, v in CONTEXT.items() if k != "policy_version"}
    source_new = {k: v for k, v in current.items() if k != "policy_version"}
    state = dict(current, environment_changes=[{"id": "event-1", "at": 999, "reason": "scenario:spill",
                                               "previous": source_old, "current": source_new}])
    assert lifecycle.observe(state, "rules-v1")
    assert mem.load(context=CONTEXT)[0] == {}
    assert lifecycle.observe(state, "rules-v1") == []
    assert lifecycle.status()["events"][0]["propagation_ms"] == 1000


def test_actor_motion_and_reordered_constraints_do_not_invalidate_memory(setup):
    mem, lifecycle, _ = setup
    record(mem)
    zones = [{"id": "a", "x": 1}, {"id": "b", "x": 2}]
    lifecycle.observe(dict(CONTEXT, site_constraints=zones), "rules-v1")
    assert lifecycle.observe(dict(CONTEXT, site_constraints=list(reversed(zones)),
                                  walking_humans=[{"x": 12, "y": 3}]), "rules-v1") == []
    assert mem.load(context=CONTEXT)[0]


def test_run_replaces_obsolete_plan_and_holds_if_no_route(setup, monkeypatch):
    from unittest.mock import AsyncMock
    from app.services.run_service import RunService
    from app.services import site_router, route_learning
    from app.policies.versioning import policy_version_hash
    from bench.world import Layout
    mem, _, _ = setup
    monkeypatch.setattr(route_learning, "_memory", mem)
    layout = Layout()
    world = dict(layout.data, **layout.experience_identity)
    tel = dict(layout.experience_identity, robot_id="robot-1", x=3, y=3.5, site_constraints=[])
    svc = RunService()
    svc.sim = type("Sim", (), {"send_command": AsyncMock(return_value={"ok": True}),
                               "get_world": AsyncMock(return_value=world)})()
    events = []
    monkeypatch.setattr(svc, "_append_event", lambda db, rid, kind, payload: events.append((kind, payload)))
    svc._plans["run"] = [{"x": 999, "y": 999}]
    monkeypatch.setattr(site_router, "route_plan", lambda *a, **kw: None)
    assert asyncio.run(svc._refresh_environment_plan(None, "run", tel, {"x": 8, "y": 3.5}))
    assert svc._plans["run"] == [] and "run" in svc._environment_holds
    assert asyncio.run(svc._refresh_environment_plan(None, "run", tel, {"x": 8, "y": 3.5}))
    assert len([e for e in events if e[0] == "ENVIRONMENT_CHANGE"]) == 1
    monkeypatch.setattr(site_router, "route_plan", lambda *a, **kw: [{"x": 8, "y": 3.5, "max_speed": 0.2}])
    assert asyncio.run(svc._refresh_environment_plan(None, "run", tel, {"x": 8, "y": 3.5}))
    assert "run" not in svc._environment_holds
    assert not asyncio.run(svc._refresh_environment_plan(None, "run", tel, {"x": 8, "y": 3.5}))
    assert all(call.args[0]["intent"] == "STOP" for call in svc.sim.send_command.call_args_list)
    assert events[-2][1]["action"] == "replanned"
