"""Short-lived vision caution zones must not invalidate route experience; real site constraints still do."""
from app.services.environment_lifecycle import constraints_key

HAZARD = {"id": "hazard-spill-1", "x": 10.0, "y": 5.0, "radius": 1.5, "slow_radius": 3.0, "max_speed": 0.3}
VISION = {"id": "vision-vis-12-person-0", "x": 7.3, "y": 15.2, "radius": 0.0, "slow_radius": 1.5, "max_speed": 0.3}


def test_vision_sighting_does_not_change_the_constraint_fingerprint():
    assert constraints_key({"site_constraints": []}) == constraints_key({"site_constraints": [VISION]})
    assert constraints_key({"site_constraints": [HAZARD]}) == constraints_key({"site_constraints": [HAZARD, VISION]})


def test_a_real_hazard_zone_still_changes_it():
    assert constraints_key({"site_constraints": []}) != constraints_key({"site_constraints": [HAZARD]})
    moved = dict(HAZARD, x=12.0)
    assert constraints_key({"site_constraints": [HAZARD]}) != constraints_key({"site_constraints": [moved]})
