"""Task-drift guard: plans must end at the mission destination without wandering."""
from app.services.task_guard import check_plan, guard
from app.world_model import ZONE_SPEED_LIMITS
from bench.world import load_layout

FENCE = {"min_x": 0, "max_x": 40, "min_y": 0, "max_y": 25}
START = {"x": 3.0, "y": 3.5}
GOAL = {"x": 16.0, "y": 23.0}
SITE = load_layout()


def test_plan_to_the_goal_is_on_task():
    out = check_plan(START, GOAL, [{"x": 12.5, "y": 3.5}, {"x": 12.5, "y": 23}, {"x": 16, "y": 23}], FENCE)
    assert out["verdict"] == "ON_TASK" and out["reasons"] == []


def test_plan_to_another_bay_is_drift():
    out = check_plan(START, GOAL, [{"x": 12.5, "y": 3.5}, {"x": 30, "y": 23}], FENCE)
    assert out["verdict"] == "DRIFT"
    assert "from the mission destination" in out["reasons"][0]


def test_wandering_detour_is_drift():
    reference = [{"x": 12.5, "y": 3.5}, {"x": 12.5, "y": 23}, {"x": 16, "y": 23}]
    wander = [{"x": 38, "y": 1}, {"x": 38, "y": 24}, {"x": 1, "y": 24}, {"x": 1, "y": 1}, {"x": 38, "y": 12}, {"x": 16, "y": 23}]
    out = check_plan(START, GOAL, wander, FENCE, reference)
    assert out["verdict"] == "DRIFT" and any("long" in r for r in out["reasons"])


def test_outside_boundary_is_drift():
    out = check_plan(START, GOAL, [{"x": 45, "y": 3}, {"x": 16, "y": 23}], FENCE)
    assert out["verdict"] == "DRIFT"


def test_guard_replaces_drift_with_aisle_route_to_the_same_goal():
    g = guard({"waypoints": [{"x": 30, "y": 23}], "model_used": "nvidia/ultra"}, START, GOAL, SITE, ZONE_SPEED_LIMITS)
    assert g["replaced"] and g["check"]["action"] == "replaced_with_aisle_route"
    last = g["plan"]["waypoints"][-1]
    assert abs(last["x"] - GOAL["x"]) < 0.01 and abs(last["y"] - GOAL["y"]) < 0.01
    assert g["plan"]["model_used"] == "site_router" and g["plan"]["rejected_plan"]["model_used"] == "nvidia/ultra"


def test_guard_keeps_an_on_task_plan():
    plan = {"waypoints": [{"x": 12.5, "y": 3.5}, {"x": 12.5, "y": 23}, {"x": 16, "y": 23}], "model_used": "nvidia/ultra"}
    g = guard(plan, START, GOAL, SITE, ZONE_SPEED_LIMITS)
    assert not g["replaced"] and g["plan"] is plan
