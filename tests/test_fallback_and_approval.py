from app.services.local_fallback_planner import generate_fallback_waypoint
from app.services import operator_approval
from app.config import settings
from app.db.session import engine, Base


# Ensure DB tables exist for tests (uses local sqlite file configured in settings)
import os
os.makedirs(os.path.join(os.path.dirname(__file__), '..', 'data'), exist_ok=True)
Base.metadata.create_all(bind=engine)


def test_fallback_waypoint_moves_toward_goal():
    telemetry = {"x": 0.0, "y": 0.0}
    goal = {"x": 1.0, "y": 0.0}
    wp = generate_fallback_waypoint(telemetry, goal)
    assert isinstance(wp, dict)
    assert "x" in wp and "y" in wp and "max_speed" in wp
    # waypoint should be > 0.0 and <= 0.5 toward the goal
    assert 0.0 < wp["x"] <= 0.5
    assert wp["y"] == 0.0


def test_operator_approval_store_and_lookup():
    run_id = "test_run_123"
    proposal_hash = "deadbeef"
    # ensure clean state
    operator_approval.revoke(run_id, proposal_hash)
    assert not operator_approval.is_approved(run_id, proposal_hash)
    operator_approval.approve(run_id, proposal_hash)
    assert operator_approval.is_approved(run_id, proposal_hash)
    # list contains our approval
    lst = operator_approval.list_for_run(run_id)
    assert proposal_hash in lst
    # cleanup
    operator_approval.revoke(run_id, proposal_hash)
