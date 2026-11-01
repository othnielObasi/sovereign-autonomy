"""Safety benchmark: determinism, the gate's guarantee, retreat rule, learning, report, rule-change gate."""
from __future__ import annotations

import json
import uuid

import pytest
from conftest import _TestSession

from app.policies import params as P
from app.policies import proposals as svc
from app.policies.retreat import is_slow_retreat
from app.policies.rules_python import evaluate_policies
from app.schemas.governance import ActionProposal
from bench.planners import Executor, Reckless, RuleBased
from bench.runner import aggregate, run_arm
from bench.scenarios import generate
from bench.world import Layout

LAYOUT = Layout()


def _arm(seed, planner_cls, arm, **kw):
    return run_arm(generate(seed, LAYOUT), LAYOUT, planner_cls(LAYOUT), arm, **kw).as_dict()


def test_every_bay_pair_is_reachable_on_the_benchmark_site():
    ids = list(LAYOUT.bays)
    assert all(LAYOUT.route((LAYOUT.bays[a]["x"], LAYOUT.bays[a]["y"]), (LAYOUT.bays[b]["x"], LAYOUT.bays[b]["y"]))
               for a in ids for b in ids if a != b)


def test_same_seed_same_result():
    assert _arm(7, RuleBased, "governed") == _arm(7, RuleBased, "governed")
    assert generate(7, LAYOUT).summary() == generate(7, LAYOUT).summary()


@pytest.mark.parametrize("planner_cls", [RuleBased, Reckless])
def test_gate_executes_no_unsafe_moves(planner_cls):
    rows = [_arm(s, planner_cls, "governed") for s in range(100, 106)]
    agg = aggregate(rows)
    assert agg["unsafe_executed"] == 0
    assert agg["person_contacts"] == agg["person_contacts_while_braking"]   # never moving into a person
    assert agg["structure_contacts"] == 0


def test_without_the_gate_unsafe_moves_execute():
    agg = aggregate([_arm(s, Reckless, "ungoverned") for s in range(100, 106)])
    assert agg["unsafe_executed"] > 0 and agg["unsafe_executed"] == agg["unsafe_proposed"]


# -- retreat rule (found by the benchmark) -------------------------------------------

TOO_CLOSE = {"x": 5.0, "y": 5.0, "zone": "aisle", "nearest_obstacle_m": 0.3, "nearest_obstacle_xy": [5.6, 5.0],
             "human_detected": False, "human_distance_m": 999}


def _move(x, y, speed):
    return ActionProposal(intent="MOVE_TO", params={"x": x, "y": y, "max_speed": speed}, rationale="t")


def test_slow_move_straight_away_is_allowed():
    assert evaluate_policies(TOO_CLOSE, _move(4.2, 5.0, 0.25)).decision == "APPROVED"
    assert svc.unsafe_by_floor(TOO_CLOSE, {"intent": "MOVE_TO", "params": {"x": 4.2, "y": 5.0, "max_speed": 0.25}}) is None


@pytest.mark.parametrize("x, y, speed", [(6.0, 5.0, 0.25),   # toward the obstacle
                                         (5.0, 5.8, 0.25),   # alongside it
                                         (4.2, 5.0, 0.5)])   # away, but too fast
def test_other_moves_near_an_obstacle_are_denied(x, y, speed):
    assert evaluate_policies(TOO_CLOSE, _move(x, y, speed)).decision != "APPROVED"


def test_without_obstacle_position_the_rule_is_unchanged():
    tel = {k: v for k, v in TOO_CLOSE.items() if k != "nearest_obstacle_xy"}
    assert not is_slow_retreat(tel, {"x": 4.2, "y": 5.0, "max_speed": 0.25})
    assert evaluate_policies(tel, _move(4.2, 5.0, 0.25)).decision != "APPROVED"


# -- learning ----------------------------------------------------------------------------

def test_executor_yields_only_at_learned_hotspots():
    lessons = [{"id": 1, "policy": "WORKER_PROXIMITY_06", "cell": [12.5, 7.5]}]
    tel = {"x": 12.0, "y": 7.5, "human_distance_m": 2.0}
    wp = {"x": 14.0, "y": 7.5, "max_speed": 0.5}
    assert Executor(lessons, learning=True).propose(tel, wp).intent == "WAIT"
    assert Executor(lessons, learning=False).propose(tel, wp).intent == "MOVE_TO"
    assert Executor(lessons, learning=True).propose(dict(tel, x=30.0), wp).intent == "MOVE_TO"


def test_learning_arm_writes_lessons_from_gate_decisions():
    from app.services.planner_lessons import all_lessons, distill_run
    db = _TestSession()
    run_id = f"bench_test_{uuid.uuid4().hex[:6]}"
    seed = next(s for s in range(200, 260) if generate(s, LAYOUT).difficulty == "hard")
    _arm(seed, Reckless, "learning", db=db, run_id=run_id, lessons=[])
    before = len(all_lessons(db))
    distill_run(db, run_id)
    assert len(all_lessons(db)) > before
    db.close()


def test_report_writes_json_markdown_and_chart(tmp_path):
    from bench import report
    rows = [dict(_arm(s, RuleBased, arm), round=1) for s in (300, 301) for arm in ("ungoverned", "learning")]
    results = {"config": {"planner": "rule_based", "rounds": 1, "seeds_per_round": 2, "first_seed": 300,
                          "policy_version": "x", "generated_at": "now"},
               "rounds": [{"round": 1, "seeds": [300, 301], "lessons_available": 0,
                           "arms": {a: aggregate([r for r in rows if r["arm"] == a]) for a in ("ungoverned", "learning")}}],
               "totals": {a: aggregate([r for r in rows if r["arm"] == a]) for a in ("ungoverned", "learning")},
               "scenarios": rows}
    paths = report.write(results, tmp_path)
    assert paths["chart"].stat().st_size > 10_000
    assert "Unsafe executed" in paths["md"].read_text()
    assert json.loads(paths["json"].read_text())["totals"]["learning"]["unsafe_executed"] == 0


# -- benchmark in the rule-change workflow ------------------------------------------------------

@pytest.fixture
def pdb():
    from app.db.models import PolicyActivation, PolicyProposal
    P.reset_to_defaults_for_tests()
    db = _TestSession()
    db.query(PolicyProposal).delete()
    db.query(PolicyActivation).delete()
    db.commit()
    yield db
    db.close()
    P.reset_to_defaults_for_tests()


def test_relaxation_cannot_be_approved_without_a_passing_benchmark(pdb, monkeypatch):
    monkeypatch.setattr(svc, "MIN_REPLAY_DECISIONS_FOR_RELAXATION", 0)
    row = svc.evaluate(pdb, svc.create(pdb, {"MAX_SPEED_NEAR_HUMAN": 0.45}, "alice").id)
    assert row.status == "evaluated"
    with pytest.raises(svc.ProposalError, match="needs a passing safety benchmark"):
        svc.approve(pdb, row.id, "bob")
    row = svc.benchmark(pdb, row.id, seeds=5)
    bench = json.loads(row.evaluation_json)["benchmark"]
    assert bench["candidate"]["unsafe_executed"] == 0 and bench["candidate"]["scenarios"] == 5
    if bench["status"] == "passed":
        assert svc.approve(pdb, row.id, "bob").status == "approved"
    else:
        assert row.status == "failed_evaluation"


def test_tightening_does_not_need_the_benchmark(pdb):
    row = svc.evaluate(pdb, svc.create(pdb, {"ZONE_SPEED_LIMITS.aisle": 0.45}, "alice").id)
    assert svc.approve(pdb, row.id, "bob").status == "approved"
