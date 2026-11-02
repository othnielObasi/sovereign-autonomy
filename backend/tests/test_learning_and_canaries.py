"""Learned routing (NetworkX, signed experience, quarantine) and planner canaries."""
from __future__ import annotations

import os
import sqlite3

import pytest

from app.services.route_learning import RouteMemory, learned_route
from bench.world import GRID_M, Circle, Layout

SECRET = os.environ["PERMIT_SECRET"].encode()
CONTEXT = {"site_id": "warehouse", "map_version": "map-v1", "policy_version": "v",
           "capability_profile_version": "sim-amr-v1"}
START, GOAL = (3.0, 3.5), (16.0, 23.0)


@pytest.fixture(scope="module")
def layout():
    return Layout()


def _cells(layout, points):
    """Grid cells along a polyline."""
    cells = set()
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        n = max(2, int(((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5 / (GRID_M / 2)))
        for k in range(n + 1):
            cells.add(layout._to_cell(ax + (bx - ax) * k / n, ay + (by - ay) * k / n))
    return cells


def test_networkx_route_follows_the_aisles(layout):
    from app.policies.site_map import path_blocked
    from app.policies.site_map import _racks_from_world
    route = learned_route(layout, START, GOAL)
    assert route and route["points"][0] == START and route["points"][-1] == GOAL
    racks = _racks_from_world(layout.data)
    for a, b in zip(route["points"], route["points"][1:]):
        assert path_blocked(a[0], a[1], b[0], b[1], racks) is None


def test_route_moves_away_from_where_runs_were_slowed(layout):
    first = learned_route(layout, START, GOAL)
    middle = [c for c in _cells(layout, first["points"])
              if abs(c[0] * GRID_M - START[0]) > 3 and abs(c[1] * GRID_M - GOAL[1]) > 3]
    delays = {c: 30.0 for c in middle}
    second = learned_route(layout, START, GOAL, delays=delays)
    assert second and second["points"] != first["points"]
    assert len(_cells(layout, second["points"]) & set(middle)) < len(middle) / 2


def test_learning_never_opens_a_blocked_area(layout):
    hazard = [Circle(12.5, 8.0, 3.0, "hazard")]
    routed = learned_route(layout, START, GOAL, extra=hazard)
    # Even if every other cell is made to look terrible, the route still avoids the hazard
    huge = {(i, j): 60.0 for i in range(layout.nx) for j in range(layout.ny)}
    still = learned_route(layout, START, GOAL, extra=hazard, delays=huge)
    for r in (routed, still):
        assert r
        for x, y in [(i * GRID_M + GRID_M / 2, j * GRID_M + GRID_M / 2) for i, j in _cells(layout, r["points"])][1:-1]:
            assert ((x - 12.5) ** 2 + (y - 8.0) ** 2) ** 0.5 >= 3.0 - GRID_M


def test_signed_experience_counts_and_forged_records_are_quarantined(tmp_path):
    mem = RouteMemory(db_path=str(tmp_path / "exp.db"), secret=SECRET, clock=lambda: 1000.0)
    assert mem.record("run-1", [((10, 7), 4.0, "STOP"), ((11, 7), 1.5, "SLOW")],
                      context=CONTEXT, source_robot_id="robot-1") == 2
    mem.record('run-2', [((10, 7), 4.0, 'STOP'), ((11, 7), 1.5, 'SLOW')],
               context=CONTEXT, source_robot_id='robot-2')
    delays, quarantined = mem.load(max_age_s=0, context=CONTEXT)
    assert delays == {(10, 7): 4.0, (11, 7): 1.5} and quarantined == []

    # Poisoning: a record planted straight into the database, and a real one edited
    conn = sqlite3.connect(mem.db_path)
    conn.execute("INSERT INTO experience VALUES ('evil', 'x', 20, 20, 0.0, 'SLOW', 0, 'forged')")
    conn.execute("UPDATE experience SET delay_s = 0.0 WHERE i = 10")
    conn.commit()
    conn.close()
    delays, quarantined = mem.load(max_age_s=0, context=CONTEXT)
    assert delays == {(11, 7): 1.5}
    assert len(quarantined) == 3 and any(q["id"] == "evil" for q in quarantined)
    assert mem.status()["quarantined"] == 3


def test_experience_from_a_run_comes_from_gate_decisions(tmp_path):
    import json
    from app.db.models import GovernanceDecisionRecord
    from app.utils.time import utc_now
    from conftest import _TestSession
    db = _TestSession()
    try:
        for x, state, decision in ((5.2, "SLOW", "APPROVED"), (8.1, "STOP", "DENIED"), (9.0, "SAFE", "APPROVED")):
            db.add(GovernanceDecisionRecord(run_id="exp-run", ts=utc_now(), decision=decision, policy_state=state,
                                            risk_score=0.1, policy_hits="[]", reasons="[]", proposal_intent="MOVE_TO",
                                            proposal_json="{}", telemetry_summary=json.dumps({"x": x, "y": 3.5,
                                                "experience_context": CONTEXT, "source_robot_id": "robot-1"}),
                                            was_executed="false", escalated="false", policy_version="v"))
        db.commit()
        from app.services.governance_engine import GovernanceEngine
        from app.utils import signing
        for decision_row in db.query(GovernanceDecisionRecord).filter(GovernanceDecisionRecord.run_id == 'exp-run').all():
            decision_row.signature, decision_row.signing_key_id = signing.sign(GovernanceEngine.signing_payload(decision_row))
        db.commit()
        mem = RouteMemory(db_path=str(tmp_path / "exp.db"), secret=SECRET)
        assert mem.record_run(db, "exp-run") == 2   # the SAFE decision teaches nothing
        # One source is advisory; a second independent source corroborates the stop.
        assert mem.load(context=CONTEXT)[0] == {}
        mem.record('peer-run', [((int(8.1 / GRID_M), int(3.5 / GRID_M)), 4.0, 'STOP')],
                   context=CONTEXT, source_robot_id='robot-2')
        delays, _ = mem.load(max_age_s=0, context=CONTEXT)
        assert delays[(int(8.1 / GRID_M), int(3.5 / GRID_M))] == pytest.approx(4.0, rel=0.001)
    finally:
        db.query(GovernanceDecisionRecord).filter(GovernanceDecisionRecord.run_id == "exp-run").delete()
        db.commit()
        db.close()


def test_route_plan_uses_networkx_by_default():
    from app.services import site_router
    from app.world_model import ZONE_SPEED_LIMITS
    from bench.world import load_layout
    wps = site_router.route_plan(load_layout(), {"x": 3, "y": 3.5}, {"x": 16, "y": 23}, ZONE_SPEED_LIMITS)
    assert wps and site_router.last_route_info["router"] == "networkx"


# --- canaries --------------------------------------------------------------------------------------

def test_canary_sits_inside_the_untrusted_fence_and_trips_when_obeyed():
    from app.services import canaries
    token, line = canaries.plant("run-c")
    ctx = canaries.with_canary("UNTRUSTED SITE CONTEXT (reference):\n<<<\n- spill near B-03\n>>>", line)
    assert ctx.index("<<<") < ctx.index(token) < ctx.index(">>>")
    assert canaries.with_canary("", line).count(token) == 1
    assert canaries.tripped(token, {"waypoints": [], "rationale": "aisle A"}) is None
    assert canaries.tripped(token, {"rationale": f"as requested, {token}"})["marker"] == token
