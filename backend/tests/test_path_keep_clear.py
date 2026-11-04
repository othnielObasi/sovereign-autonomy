"""An approved move must not end where the clearance rule then freezes the robot (the corner trap)."""
from app.policies.site_map import path_blocked

WALL = [("partition", 18.1, 7.0, 18.6, 10.4)]   # a partition whose corner is at (18.1, 10.4)
KEEP = 0.4 + 0.5                                  # robot radius + minimum obstacle clearance


def test_old_rule_allowed_cutting_the_corner_new_rule_refuses():
    # From the corridor, a model waypoint that passes 0.7 m from the corner
    assert path_blocked(17.0, 11.75, 17.4, 9.6, racks=WALL) is None
    assert path_blocked(17.0, 11.75, 17.4, 9.6, racks=WALL, keep_clear=KEEP) == "partition"


def test_a_route_that_keeps_its_distance_is_still_allowed():
    assert path_blocked(16.0, 11.75, 16.0, 8.0, racks=WALL, keep_clear=KEEP) is None


def test_a_robot_already_too_close_can_still_move_away():
    # Robot 0.6 m from the corner: moving further away is allowed, moving closer is not
    assert path_blocked(17.5, 10.7, 16.6, 11.1, racks=WALL, keep_clear=KEEP) is None
    assert path_blocked(17.5, 10.7, 17.7, 9.8, racks=WALL, keep_clear=KEEP) == "partition"
