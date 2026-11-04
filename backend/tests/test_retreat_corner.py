"""A robot too close to one obstacle, with a partition directly behind it, must still find a slow retreat."""
from app.policies.retreat import is_slow_retreat, retreat_target
from app.policies.site_map import path_blocked

# Seen live: robot 0.42 m from a partition corner at (18.1, 10.4); straight back was refused.
TEL = {"x": 17.32, "y": 10.59, "nearest_obstacle_m": 0.42, "nearest_obstacle_xy": [18.12, 10.38]}
WALL_BEHIND = [("partition-behind", 15.6, 10.4, 16.1, 11.2)]   # just behind the straight-back target


def blocked(x, y, tx, ty):
    return path_blocked(x, y, tx, ty, racks=WALL_BEHIND)


def test_straight_back_is_blocked_in_the_corner():
    assert blocked(17.32, 10.59, 16.55, 10.78)


def test_retreat_finds_another_allowed_direction():
    target = retreat_target(TEL, blocked)
    assert target is not None
    assert is_slow_retreat(TEL, target)              # the gate's own exception still applies
    assert not blocked(TEL["x"], TEL["y"], target["x"], target["y"])
    assert target["max_speed"] <= 0.3


def test_no_retreat_without_obstacle_position():
    assert retreat_target({"x": 1, "y": 1, "nearest_obstacle_m": 0.3}, blocked) is None
