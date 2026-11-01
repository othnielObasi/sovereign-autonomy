"""Execution authority (app.autonomy): permits, kill switches, world state,
checkpoints, path checks, routing, experience memory and dispatch."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time

import pytest

from app.autonomy import (Action, Budget, CanaryRegistry, CheckpointStore, CorridorReservations,
                          EvidenceLog, Experience, KillSwitch, MissionIntegrity, PermitStore,
                          Rejected, RouteGraph, SafeDispatcher, TrajectoryValidator,
                          TrustedExperience, Watchdog, WorldState)

SECRET = b"0123456789abcdef0123456789abcdef"


@pytest.fixture
def env(tmp_path):
    world = WorldState()
    world.update("r", 1, {"x": 0})
    kills = KillSwitch()
    permits = PermitStore(str(tmp_path / "permits.db"), SECRET, kills, world)
    checkpoints = CheckpointStore(str(tmp_path / "missions.db"))
    action = Action("r", "m", "a1", "MOVE_TO", {"x": 1}, 1, "v1")
    return world, kills, permits, checkpoints, action


# --- permits -----------------------------------------------------------------

def test_permit_is_single_use(env):
    _, _, permits, _, action = env
    token = permits.issue(action, approved=True)
    permits.consume(token, action)
    with pytest.raises(Rejected, match="replayed"):
        permits.consume(token, action)


def test_tampered_permit_rejected(env):
    _, _, permits, _, action = env
    token = json.loads(permits.issue(action, approved=True))
    token["payload"]["robot"] = "other"
    with pytest.raises(Rejected, match="signature"):
        permits.consume(json.dumps(token), action)


def test_malformed_permit_rejected(env):
    _, _, permits, _, action = env
    for bad in ("not json", "{}", json.dumps({"payload": {}, "signature": 5})):
        with pytest.raises(Rejected):
            permits.consume(bad, action)


def test_permit_bound_to_exact_action(env):
    _, _, permits, _, action = env
    token = permits.issue(action, approved=True)
    altered = Action("r", "m", "a1", "MOVE_TO", {"x": 99}, 1, "v1")
    with pytest.raises(Rejected, match="mismatch"):
        permits.consume(token, altered)


def test_denied_action_gets_no_permit(env):
    _, _, permits, _, action = env
    with pytest.raises(Rejected, match="denied"):
        permits.issue(action, approved=False)


def test_expired_permit_rejected(env):
    _, _, permits, _, action = env
    token = permits.issue(action, approved=True, ttl_s=0.001)
    time.sleep(0.01)
    with pytest.raises(Rejected, match="expired"):
        permits.consume(token, action)


def test_permit_used_concurrently_succeeds_once(env):
    _, _, permits, _, action = env
    token = permits.issue(action, approved=True)
    wins, losses = [], []

    def attempt():
        try:
            permits.consume(token, action)
            wins.append(1)
        except Rejected:
            losses.append(1)

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(wins) == 1 and len(losses) == 7


# --- kill switch ---------------------------------------------------------------

def test_kill_switch_revokes_outstanding_permit(env):
    _, kills, permits, _, action = env
    token = permits.issue(action, approved=True)
    kills.activate("robot", "r")
    with pytest.raises(Rejected, match="kill"):
        permits.consume(token, action)
    with pytest.raises(Rejected):
        kills.reset("robot", "r", authorized=False)


def test_kill_switch_blocks_new_permits_in_every_scope(env):
    _, kills, permits, _, action = env
    for scope, ident in (("global", "*"), ("robot", "r"), ("mission", "m")):
        kills.activate(scope, ident)
        with pytest.raises(Rejected, match="kill"):
            permits.issue(action, approved=True)
        kills.reset(scope, ident, authorized=True)
    kills.activate("agent", "planner-1")
    with pytest.raises(Rejected, match="kill"):
        permits.issue(action, approved=True, agent_id="planner-1")
    permits.issue(action, approved=True, agent_id="planner-2")


def test_reset_does_not_revive_old_permits(env):
    _, kills, permits, _, action = env
    token = permits.issue(action, approved=True)
    kills.activate("robot", "r")
    kills.reset("robot", "r", authorized=True)
    with pytest.raises(Rejected, match="epoch"):
        permits.consume(token, action)


def test_invalid_kill_scope():
    with pytest.raises(ValueError):
        KillSwitch().activate("planet")


# --- world state ---------------------------------------------------------------

def test_permit_rejected_after_world_changes(env):
    world, _, permits, _, action = env
    token = permits.issue(action, approved=True)
    world.update("r", 2, {"x": 2})
    with pytest.raises(Rejected, match="world"):
        permits.consume(token, action)


def test_stale_and_backward_world_state():
    world = WorldState(max_age_s=0.1)
    world.update("r", 1, {}, observed_at=time.time() - 2)
    with pytest.raises(Rejected, match="stale"):
        world.require("r", 1)
    with pytest.raises(Rejected, match="monotonic"):
        world.update("r", 1, {})
    assert world.current_version("r") == 1 and world.current_version("nobody") is None


# --- checkpoints ---------------------------------------------------------------

def test_checkpoint_versions_and_chain(env):
    *_, checkpoints, _ = env
    assert checkpoints.checkpoint("m", {"step": 1}) == 1
    with pytest.raises(Rejected, match="conflict"):
        checkpoints.checkpoint("m", {"step": 2}, expected_version=0)
    assert checkpoints.checkpoint("m", {"step": 2}, expected_version=1) == 2
    assert checkpoints.load("m") == (2, {"step": 2})
    assert checkpoints.load("unknown") is None
    assert checkpoints.verify_chain()


def test_checkpoint_tamper_detected(env):
    *_, checkpoints, _ = env
    checkpoints.checkpoint("m", {"step": 1})
    conn = sqlite3.connect(checkpoints.path)
    conn.execute("UPDATE events SET event='{}' WHERE seq=1")
    conn.commit()
    conn.close()
    assert not checkpoints.verify_chain()


def test_ambiguous_action_must_be_reconciled(env):
    *_, checkpoints, action = env
    checkpoints.begin_action(action)
    assert checkpoints.in_doubt("m") == ["a1"]
    with pytest.raises(Rejected, match="unreconciled"):
        checkpoints.require_reconciled("m")
    with pytest.raises(Rejected, match="duplicate"):
        checkpoints.begin_action(action)
    with pytest.raises(Rejected, match="verification"):
        checkpoints.reconcile("a1", controller_verified=False, executed=True)
    checkpoints.reconcile("a1", controller_verified=True, executed=True)
    checkpoints.require_reconciled("m")
    with pytest.raises(Rejected, match="unknown"):
        checkpoints.reconcile("nope", controller_verified=True, executed=False)


def test_database_files_are_released(tmp_path):
    """Connections are closed after every call, so the files can be deleted (Windows locks open files)."""
    world = WorldState()
    world.update("r", 1, {})
    permits = PermitStore(str(tmp_path / "p.db"), SECRET, KillSwitch(), world)
    checkpoints = CheckpointStore(str(tmp_path / "c.db"))
    action = Action("r", "m", "a1", "MOVE_TO", {}, 1, "v1")
    permits.consume(permits.issue(action, approved=True), action)
    checkpoints.checkpoint("m", {})
    checkpoints.begin_action(action)
    checkpoints.verify_chain()
    os.remove(tmp_path / "p.db")
    os.remove(tmp_path / "c.db")


# --- path checks ---------------------------------------------------------------

def test_trajectory_checks_the_whole_path():
    v = TrajectoryValidator()
    bounds = (0, -2, 11, 2)
    with pytest.raises(Rejected, match="restricted"):
        v.validate([(0, 0), (10, 0)], bounds, [], [(4, -1, 6, 1)])
    with pytest.raises(Rejected, match="obstacle"):
        v.validate([(0, 0), (10, 0)], bounds, [(5, 0, 0.3)])
    with pytest.raises(Rejected, match="bounds"):
        v.validate([(0, 0), (12, 0)], bounds, [])
    with pytest.raises(Rejected, match="empty"):
        v.validate([], bounds, [])
    assert v.validate([(0, 0), (10, 0)], bounds, [])


# --- routing and experience ------------------------------------------------------

def test_routing_learns_but_never_crosses_a_blocked_edge():
    g = RouteGraph()
    g.add_edge("A", "B", distance=10, predicted_delay=20)
    g.add_edge("A", "C", distance=12)
    g.add_edge("C", "B", distance=12)
    assert g.plan("A", "B")["path"] == ["A", "C", "B"]
    g.learn_delay("A", "B", 0, alpha=1)
    assert g.plan("A", "B")["path"] == ["A", "B"]
    g.add_edge("A", "B", distance=10, allowed=False)
    assert g.plan("A", "B")["path"] == ["A", "C", "B"]
    with pytest.raises(Rejected, match="invalid"):
        g.learn_delay("A", "C", float("nan"))
    with pytest.raises(Rejected, match="no_permitted_route"):
        g.plan("A", "Z")


def test_forged_experience_is_quarantined():
    mem = TrustedExperience(SECRET)
    body = dict(record_id="e1", mission_id="m", route=("A", "B"), duration_s=5, outcome="ok",
                source="sim", observed_at=time.time())
    record = Experience(**body, signature=mem.sign(body))
    mem.ingest(record)
    assert mem.relevant("A", "B") == [record]
    forged = Experience(**{**body, "record_id": "evil", "duration_s": 0}, signature="forged")
    with pytest.raises(Rejected, match="untrusted"):
        mem.ingest(forged)
    assert mem.quarantine["evil"] == "invalid_signature"
    with pytest.raises(Rejected, match="duplicate"):
        mem.ingest(record)


def test_canary_and_mission_scope(env):
    *_, action = env
    canaries = CanaryRegistry()
    canaries.register("CANARY-TEST-123", "memory")
    assert canaries.scan("…CANARY-TEST-123…")[0]["owner"] == "memory"
    assert canaries.scan("clean text") == []
    mission = MissionIntegrity("m", "deliver", {"MOVE_TO"})
    mission.require(action)
    with pytest.raises(Rejected):
        mission.require(Action("r", "m", "b", "ERASE", {}, 1, "v1"))


# --- operations and dispatch -------------------------------------------------------

def test_budget_watchdog_and_corridors():
    budget = Budget(1)
    budget.consume()
    with pytest.raises(Rejected):
        budget.consume()
    dog = Watchdog(1)
    dog.require_healthy()
    dog.last_heartbeat -= 5
    with pytest.raises(Rejected):
        dog.require_healthy()
    corridors = CorridorReservations()
    corridors.reserve("c", "r1")
    with pytest.raises(Rejected):
        corridors.reserve("c", "r2")
    corridors.release("c", "r1")
    corridors.reserve("c", "r2")


def test_corridor_reservation_has_one_winner_under_contention():
    corridors = CorridorReservations()
    winners = []

    def grab(robot):
        try:
            corridors.reserve("aisle-3", robot)
            winners.append(robot)
        except Rejected:
            pass

    threads = [threading.Thread(target=grab, args=(f"r{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(winners) == 1


def test_dispatch_success_path(env):
    _, _, permits, checkpoints, action = env

    class Controller:
        def send(self, a):
            return {"accepted": True, "action_id": a.action_id}

    log = EvidenceLog()
    dispatcher = SafeDispatcher(permits, checkpoints, Controller(), Budget(5), Watchdog(10), log)
    assert dispatcher.dispatch(permits.issue(action, approved=True), action)["accepted"]
    assert [e["kind"] for e in log.events] == ["command_dispatched", "controller_acknowledged"]
    assert checkpoints.in_doubt("m") == ["a1"]   # an ACK is not proof of completion


def test_lost_acknowledgement_is_never_retried(env):
    _, _, permits, checkpoints, action = env

    class FailingController:
        def send(self, a):
            raise TimeoutError()

    dispatcher = SafeDispatcher(permits, checkpoints, FailingController(), Budget(2), Watchdog(10), EvidenceLog())
    token = permits.issue(action, approved=True)
    with pytest.raises(Rejected, match="unknown"):
        dispatcher.dispatch(token, action)
    with pytest.raises(Rejected, match="unreconciled"):
        checkpoints.require_reconciled("m")
    with pytest.raises(Rejected):
        dispatcher.dispatch(token, action)


def test_dispatch_blocked_when_watchdog_expired(env):
    _, _, permits, checkpoints, action = env
    dog = Watchdog(1)
    dog.last_heartbeat -= 5

    class Controller:
        def send(self, a):
            raise AssertionError("must not be called")

    dispatcher = SafeDispatcher(permits, checkpoints, Controller(), Budget(5), dog, EvidenceLog())
    token = permits.issue(action, approved=True)
    with pytest.raises(Rejected, match="watchdog"):
        dispatcher.dispatch(token, action)
    permits.consume(token, action)   # the permit was not used up by the blocked attempt
