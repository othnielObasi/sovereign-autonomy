from app.policies.rules_python import evaluate_policies
from app.schemas.governance import ActionProposal


def test_policy_denies_speed_in_aisle():
    telemetry = {"x": 1, "y": 1, "zone": "aisle", "nearest_obstacle_m": 2.0, "human_detected": False, "human_conf": 0.0}
    proposal = ActionProposal(intent="MOVE_TO", params={"x": 10, "y": 10, "max_speed": 0.9})
    decision = evaluate_policies(telemetry, proposal)
    assert decision.decision in ("DENIED", "NEEDS_REVIEW")
    assert "SAFE_SPEED_01" in decision.policy_hits


def test_policy_approves_safe_speed():
    telemetry = {"x": 5, "y": 5, "zone": "aisle", "nearest_obstacle_m": 5.0, "human_detected": False, "human_conf": 0.0}
    proposal = ActionProposal(intent="MOVE_TO", params={"x": 6, "y": 6, "max_speed": 0.3})
    decision = evaluate_policies(telemetry, proposal)
    assert decision.decision == "APPROVED"
    assert decision.policy_hits == []
    assert decision.risk_score < 0.7


def test_geofence_violation_current_position():
    telemetry = {"x": -5, "y": 5, "zone": "aisle", "nearest_obstacle_m": 5.0, "human_detected": False, "human_conf": 0.0}
    proposal = ActionProposal(intent="MOVE_TO", params={"x": 5, "y": 5, "max_speed": 0.3})
    decision = evaluate_policies(telemetry, proposal)
    assert decision.decision == "DENIED"
    assert "GEOFENCE_01" in decision.policy_hits
    assert decision.risk_score >= 0.95


def test_geofence_violation_proposed_destination():
    telemetry = {"x": 5, "y": 5, "zone": "aisle", "nearest_obstacle_m": 5.0, "human_detected": False, "human_conf": 0.0}
    proposal = ActionProposal(intent="MOVE_TO", params={"x": 50, "y": 5, "max_speed": 0.3})
    decision = evaluate_policies(telemetry, proposal)
    assert decision.decision == "DENIED"
    assert "GEOFENCE_01" in decision.policy_hits


def test_human_clearance_denies_high_speed_near_human():
    telemetry = {"x": 5, "y": 5, "zone": "aisle", "nearest_obstacle_m": 5.0, "human_detected": True, "human_conf": 0.9}
    proposal = ActionProposal(intent="MOVE_TO", params={"x": 6, "y": 6, "max_speed": 0.8})
    decision = evaluate_policies(telemetry, proposal)
    assert decision.decision in ("DENIED", "NEEDS_REVIEW")
    assert "HUMAN_CLEARANCE_02" in decision.policy_hits


def test_obstacle_clearance():
    telemetry = {"x": 5, "y": 5, "zone": "aisle", "nearest_obstacle_m": 0.2, "human_detected": False, "human_conf": 0.0}
    proposal = ActionProposal(intent="MOVE_TO", params={"x": 6, "y": 6, "max_speed": 0.3})
    decision = evaluate_policies(telemetry, proposal)
    assert decision.decision in ("DENIED", "NEEDS_REVIEW")
    assert "OBSTACLE_CLEARANCE_03" in decision.policy_hits


def test_uncertainty_gate():
    telemetry = {"x": 5, "y": 5, "zone": "aisle", "nearest_obstacle_m": 5.0, "human_detected": True, "human_conf": 0.3}
    proposal = ActionProposal(intent="MOVE_TO", params={"x": 6, "y": 6, "max_speed": 0.3})
    decision = evaluate_policies(telemetry, proposal)
    assert decision.decision in ("DENIED", "NEEDS_REVIEW")
    assert "UNCERTAINTY_04" in decision.policy_hits


def test_stop_always_approved():
    telemetry = {"x": 5, "y": 5, "zone": "aisle", "nearest_obstacle_m": 5.0, "human_detected": False, "human_conf": 0.0}
    proposal = ActionProposal(intent="STOP", params={})
    decision = evaluate_policies(telemetry, proposal)
    assert decision.decision == "APPROVED"
    assert decision.risk_score == 0.0


def test_wait_always_approved():
    telemetry = {"x": 5, "y": 5, "zone": "aisle", "nearest_obstacle_m": 0.2, "human_detected": True, "human_conf": 0.95}
    proposal = ActionProposal(intent="WAIT", params={})
    decision = evaluate_policies(telemetry, proposal)
    assert decision.decision == "APPROVED"


def test_corridor_speed_limit():
    telemetry = {"x": 5, "y": 5, "zone": "corridor", "nearest_obstacle_m": 5.0, "human_detected": False, "human_conf": 0.0}
    proposal_ok = ActionProposal(intent="MOVE_TO", params={"x": 6, "y": 6, "max_speed": 0.6})
    decision_ok = evaluate_policies(telemetry, proposal_ok)
    assert decision_ok.decision == "APPROVED"

    proposal_bad = ActionProposal(intent="MOVE_TO", params={"x": 6, "y": 6, "max_speed": 0.9})
    decision_bad = evaluate_policies(telemetry, proposal_bad)
    assert "SAFE_SPEED_01" in decision_bad.policy_hits


def test_multiple_policy_hits():
    telemetry = {"x": 5, "y": 5, "zone": "aisle", "nearest_obstacle_m": 0.3, "human_detected": True, "human_conf": 0.9}
    proposal = ActionProposal(intent="MOVE_TO", params={"x": 6, "y": 6, "max_speed": 0.9})
    decision = evaluate_policies(telemetry, proposal)
    assert decision.decision in ("DENIED", "NEEDS_REVIEW")
    assert len(decision.policy_hits) >= 2  # At least SAFE_SPEED + OBSTACLE or HUMAN
    assert decision.risk_score >= 0.85
