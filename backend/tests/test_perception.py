"""Vision cross-check: geometry, matching, and that vision can only add caution."""
import pytest

from app.policies.rules_python import evaluate_policies
from app.schemas.governance import ActionProposal
from app.services import perception as P


TEL = {"x": 10.0, "y": 5.0, "theta": 0.0}   # facing +x; "right" is -y


def test_image_geometry_round_trip():
    # Robot position in the image is (500, 720) on the 0-1000 grid
    assert P.image_to_robot(500, 720) == pytest.approx((0.0, 0.0))
    ahead, right = P.image_to_robot(500, 470)          # 250/1000 of 12 m above the robot
    assert ahead == pytest.approx(3.0) and right == pytest.approx(0.0)
    wx, wy = P.robot_to_world(TEL, ahead, right)
    assert (wx, wy) == pytest.approx((13.0, 5.0))
    assert P.world_to_robot(TEL, wx, wy) == pytest.approx((3.0, 0.0))
    # to the robot's right when facing +x is -y
    assert P.robot_to_world(TEL, 0.0, 1.0) == pytest.approx((10.0, 4.0))


def test_ground_truth_only_includes_what_is_in_view():
    tel = dict(TEL, walking_humans=[{"x": 13, "y": 5}, {"x": 30, "y": 5}],
               obstacles=[{"type": "spill", "x": 12, "y": 5}, {"type": "rack", "x": 11, "y": 5}])
    kinds = sorted(o["type"] for o in P.ground_truth(tel))
    assert kinds == ["person", "spill"]


def test_compare_flags_misses_and_unconfirmed_sightings():
    truth = [{"type": "person", "x": 13, "y": 5}, {"type": "spill", "x": 12, "y": 5}]
    seen = [{"type": "person", "x": 13.3, "y": 5.1}, {"type": "pallet", "x": 15, "y": 3}]
    out = P.compare(seen, truth, match_m=1.2)
    assert [m["type"] for m in out["matched"]] == ["person"]
    assert [m["type"] for m in out["missed"]] == ["spill"]
    assert [u["type"] for u in out["unconfirmed"]] == ["pallet"]
    assert out["verdict"] == "missed_hazard"


def test_two_people_close_together_seen_as_one_is_not_a_miss():
    truth = [{"type": "person", "x": 16.2, "y": 5}, {"type": "person", "x": 16.5, "y": 5}]
    seen = [{"type": "person", "x": 16.6, "y": 5}]
    assert P.compare(seen, truth, match_m=1.2)["verdict"] == "agree"


def test_parse_objects_rejects_bad_entries():
    obj = {"objects": [{"type": "person", "x": 500, "y": 470}, {"type": "rack", "x": 1, "y": 1},
                       {"type": "spill", "x": 5000, "y": 1}, {"type": "pallet"},
                       {"type": "pallet", "x": 500, "y": 720}]}   # the robot itself
    seen = P.parse_objects(obj, TEL)
    assert len(seen) == 1 and seen[0]["type"] == "person"
    assert (seen[0]["x"], seen[0]["y"]) == pytest.approx((13.0, 5.0))


def test_unconfirmed_sighting_can_only_slow_the_robot():
    p = P.Perception()
    p._add_caution({"id": "vis-t", "unconfirmed": [{"type": "person", "x": 13.0, "y": 5.0}]})
    tel = p.apply({"x": 10.0, "y": 5.0, "zone": "corridor", "nearest_obstacle_m": 5.0,
                   "human_detected": False, "human_distance_m": 999})
    zone = tel["site_constraints"][0]
    assert zone["radius"] == 0.0           # never a no-entry zone
    fast = evaluate_policies(tel, ActionProposal(intent="MOVE_TO", params={"x": 16, "y": 5, "max_speed": 0.6}))
    assert "HAZARD_SLOW_09" in fast.policy_hits and "HAZARD_EXCLUSION_08" not in fast.policy_hits
    slow = evaluate_policies(tel, ActionProposal(intent="MOVE_TO", params={"x": 16, "y": 5, "max_speed": 0.25}))
    assert "HAZARD_SLOW_09" not in slow.policy_hits


def test_caution_zones_expire(monkeypatch):
    p = P.Perception()
    p._add_caution({"id": "vis-e", "unconfirmed": [{"type": "spill", "x": 1, "y": 1}]})
    assert p.caution_zones()
    now = P.time.time()
    monkeypatch.setattr(P.time, "time", lambda: now + 3600)
    assert p.caution_zones() == []
