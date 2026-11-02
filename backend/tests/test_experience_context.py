"""Applicability and freshness regressions, with no model/network calls."""
import json
import math
import sqlite3
from copy import deepcopy

import pytest

from app.autonomy.experience import SIM_CAPABILITY, context_from_world, world_identity
from app.services.route_learning import RouteMemory

SECRET = b"context-tests-secret-0123456789abcdef"
CONTEXT = {"site_id": "warehouse", "map_version": "map-v1", "policy_version": "rules-v1",
           "capability_profile_version": SIM_CAPABILITY}


@pytest.fixture
def memory(tmp_path):
    now = [1000.0]
    mem = RouteMemory(str(tmp_path / "experience.db"), SECRET, clock=lambda: now[0], ttl_s=100, decay_s=10)
    return mem, now


def _record(mem, **kwargs):
    args = {"context": CONTEXT, "source_robot_id": "robot-A", **kwargs}
    return mem.record("run-A", [((10, 7), 4.0, "STOP")], **args)


@pytest.mark.parametrize("field", list(CONTEXT))
def test_context_mismatches_are_excluded_before_ranking(memory, field):
    mem, _ = memory
    _record(mem)
    assert mem.load(context=CONTEXT)[0] == {(10, 7): 4.0}
    current = dict(CONTEXT, **{field: "different"})
    assert mem.load(context=current)[0] == {}
    assert mem.last_retrieval[0]["reason"] == f"{field}_mismatch"
    # A mismatched retrieval must not poison a later compatible one.
    assert mem.load(context=CONTEXT)[0] == {(10, 7): 4.0}


def test_compatible_robots_share_experience_and_writes_are_idempotent(memory):
    mem, _ = memory
    assert _record(mem) == 1
    assert _record(mem) == 0
    assert _record(mem, source_robot_id="robot-B") == 1
    assert mem.load(context=CONTEXT)[0] == {(10, 7): 4.0}
    assert {d["source_robot_id"] for d in mem.last_retrieval} == {"robot-A", "robot-B"}


def test_missing_context_fails_closed(memory):
    mem, _ = memory
    assert _record(mem, context=None) == 0
    _record(mem)
    assert mem.load()[0] == {}
    assert mem.last_retrieval[0]["reason"] == "current_context_missing"


def test_age_decay_and_expiry_are_not_extended_by_cache_lifetime(memory):
    mem, now = memory
    _record(mem)
    now[0] += 10
    assert mem.load(context=CONTEXT, max_age_s=10000)[0][(10, 7)] == pytest.approx(4 / math.e)
    now[0] += 91
    assert mem.load(context=CONTEXT, max_age_s=10000)[0] == {}
    assert mem.last_retrieval[0]["reason"] == "experience_expired"


def test_valid_legacy_record_remains_inspectable_but_is_not_reused(memory):
    mem, _ = memory
    body = dict(id="legacy", run_id="old-run", i=10, j=7, delay_s=4.0, kind="STOP", observed_at=1000.0)
    conn = sqlite3.connect(mem.db_path)
    with conn:
        conn.execute("INSERT INTO experience VALUES (?,?,?,?,?,?,?,?)", (*body.values(), mem.sign(body)))
    conn.close()
    assert mem.load(context=CONTEXT) == ({}, [])
    assert mem.last_retrieval[0]["reason"] == "legacy_context_missing"
    assert mem.status(context=CONTEXT)["records"] == 1


@pytest.mark.parametrize("field", list(CONTEXT))
def test_signed_context_tampering_is_quarantined(memory, field):
    mem, _ = memory
    _record(mem)
    conn = sqlite3.connect(mem.db_path)
    with conn:
        metadata = json.loads(conn.execute("SELECT metadata FROM experience_context").fetchone()[0])
        metadata["context"][field] = "forged"
        conn.execute("UPDATE experience_context SET metadata=?", (json.dumps(metadata),))
    conn.close()
    costs, quarantined = mem.load(context=CONTEXT)
    assert costs == {} and len(quarantined) == 1


def test_invalidation_is_durable_idempotent_and_visible_to_other_instances(memory):
    mem, now = memory
    _record(mem)
    other = RouteMemory(mem.db_path, SECRET, clock=lambda: now[0], ttl_s=100, decay_s=10)
    assert other.load(context=CONTEXT)[0]
    assert mem.invalidate("layout-change-1", {"site_id": "warehouse", "map_version": "map-v1"}, "layout replaced")
    assert not mem.invalidate("layout-change-1", {"site_id": "warehouse", "map_version": "map-v1"}, "layout replaced")
    with pytest.raises(ValueError, match="conflict"):
        mem.invalidate("layout-change-1", {"site_id": "factory"}, "different event")
    assert other.load(context=CONTEXT)[0] == {}
    assert other.last_retrieval[0]["reason"] == "invalidated:layout-change-1"
    restarted = RouteMemory(mem.db_path, SECRET, clock=lambda: now[0])
    assert restarted.load(context=CONTEXT)[0] == {}
    assert restarted.status(context=CONTEXT)["records"] == 1
    # Fresh records under the same invalidated generation cannot restore reuse.
    _record(mem, source_robot_id="robot-C")
    assert mem.load(context=CONTEXT)[0] == {}


def test_unrelated_invalidation_does_not_exclude_current_experience(memory):
    mem, _ = memory
    _record(mem)
    mem.invalidate("other-site", {"site_id": "factory"}, "maintenance")
    assert mem.load(context=CONTEXT)[0]


def test_concurrent_invalidation_delivery_is_idempotent(memory):
    from concurrent.futures import ThreadPoolExecutor
    mem, _ = memory
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: mem.invalidate("same-event", {"site_id": "warehouse"}, "changed"), range(4)))
    assert results.count(True) == 1
    assert len(mem.invalidations()) == 1


def test_postrun_learning_uses_original_decision_time_and_context(memory):
    from datetime import datetime, timezone
    from conftest import _TestSession
    from app.db.models import GovernanceDecisionRecord
    mem, _ = memory
    db = _TestSession()
    try:
        for suffix, telemetry in (("known", {"experience_context": CONTEXT, "source_robot_id": "robot-A"}),
                                  ("legacy", {})):
            db.add(GovernanceDecisionRecord(
                run_id=f"context-capture-{suffix}", ts=datetime.fromtimestamp(800, timezone.utc),
                decision="DENIED", policy_state="STOP", risk_score=0.1, policy_hits="[]", reasons="[]",
                proposal_intent="MOVE_TO", proposal_json="{}",
                telemetry_summary=json.dumps(dict(telemetry, x=5.2, y=3.5)),
                was_executed="false", escalated="false", policy_version=CONTEXT["policy_version"]))
        db.commit()
        assert mem.record_run(db, "context-capture-known") == 1
        assert mem.record_run(db, "context-capture-legacy") == 0
        # Distilling at t=1000 must not refresh an observation made at t=800.
        assert mem.load(context=CONTEXT)[0] == {}
        assert mem.last_retrieval[0]["reason"] == "experience_expired"
        assert mem.last_retrieval[0]["age_s"] == 200
    finally:
        db.query(GovernanceDecisionRecord).filter(GovernanceDecisionRecord.run_id.like("context-capture-%")).delete()
        db.commit()
        db.close()


def test_corrupt_invalidation_cannot_silently_restore_reuse(memory):
    mem, _ = memory
    _record(mem)
    mem.invalidate("event", {"site_id": "warehouse"}, "maintenance")
    conn = sqlite3.connect(mem.db_path)
    with conn:
        conn.execute("UPDATE experience_invalidations SET signature='forged'")
    conn.close()
    with pytest.raises(ValueError, match="invalid_invalidation_record"):
        mem.load(context=CONTEXT)


def test_layout_fingerprint_changes_with_geometry_and_frame_but_not_dynamic_people():
    from bench.world import load_layout
    world = load_layout()
    original = world_identity(world)
    dynamic = deepcopy(world)
    dynamic["walking_humans"] = [{"x": 1, "y": 2}]
    dynamic["obstacles"].append({"type": "forklift", "x": 9, "y": 9})
    assert world_identity(dynamic) == original
    moved = deepcopy(world)
    moved["racks"][0]["x1"] += 0.1
    assert world_identity(moved)["map_version"] != original["map_version"]
    assert world_identity(dict(world, coordinate_frame="new-origin"))["map_version"] != original["map_version"]
    assert world_identity(dict(world, name="another-site"))["site_id"] != original["site_id"]
    assert context_from_world(world, "rules-v1") is None  # unknown robot capabilities


def test_live_world_and_telemetry_have_the_same_stable_layout_identity():
    from bench.world import Layout, World, RobotState
    layout = Layout()
    world = World(layout, RobotState(3, 3.5), [], [], 42)
    telemetry = world.telemetry()
    live = dict(layout.data, **layout.experience_identity)
    live["obstacles"] = [{"x": 20, "y": 10, "type": "forklift"}]
    assert context_from_world(live, "rules-v1") == {k: telemetry[k] for k in CONTEXT if k != "policy_version"} | {
        "policy_version": "rules-v1"}
