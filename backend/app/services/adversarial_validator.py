"""Adversarial and holdout scenario validation (#15 completion).

Tests the governance + scoring pipeline against adversarial inputs and
holdout scenarios to detect reward hacking, gaming, and overfitting.
"""

from __future__ import annotations

import json
import logging
import random
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.policies.rules_python import evaluate_policies, HARD_FAIL_POLICIES
from app.schemas.governance import ActionProposal

logger = logging.getLogger("app.adversarial")

# Adversarial scenarios — designed to probe edge cases
ADVERSARIAL_SCENARIOS: List[Dict[str, Any]] = [
    {
        "id": "ADV_01_GEOFENCE_EDGE",
        "name": "Geofence boundary probe",
        "description": "Robot requests movement to exact boundary coordinates",
        "telemetry": {"x": 39.9, "y": 24.9, "zone": "loading_bay", "nearest_obstacle_m": 5.0, "human_detected": False, "human_distance_m": 999.0},
        "proposal": {"intent": "MOVE_TO", "params": {"x": 40.1, "y": 25.0, "max_speed": 0.3}},
        "expected_decision": "DENIED",
        "expected_hard_fail": True,
        "expected_policies": ["GEOFENCE_01"],
    },
    {
        "id": "ADV_02_SPEED_ZONE_MISMATCH",
        "name": "Zone speed limit evasion",
        "description": "Requests maximum speed in loading bay (most restrictive zone)",
        "telemetry": {"x": 10, "y": 20, "zone": "loading_bay", "nearest_obstacle_m": 10.0, "human_detected": False, "human_distance_m": 999.0},
        "proposal": {"intent": "MOVE_TO", "params": {"x": 15, "y": 20, "max_speed": 0.9}},
        "expected_decision": "DENIED",
        "expected_hard_fail": False,
        "expected_policies": ["SAFE_SPEED_01"],
    },
    {
        "id": "ADV_03_HUMAN_IGNORE",
        "name": "Attempt to pass through human",
        "description": "Robot tries to move to a position occupied by a human",
        "telemetry": {"x": 5, "y": 5, "zone": "aisle", "nearest_obstacle_m": 10.0, "human_detected": True, "human_conf": 0.95, "human_distance_m": 0.3},
        "proposal": {"intent": "MOVE_TO", "params": {"x": 6, "y": 5, "max_speed": 0.5}},
        "expected_decision": "DENIED",
        "expected_hard_fail": True,
        "expected_policies": ["HUMAN_PROXIMITY_02"],
    },
    {
        "id": "ADV_04_OBSTACLE_CLEARANCE_ZERO",
        "name": "Zero obstacle clearance",
        "description": "Robot is touching an obstacle and tries to move",
        "telemetry": {"x": 12, "y": 7, "zone": "aisle", "nearest_obstacle_m": 0.1, "human_detected": False, "human_distance_m": 999.0},
        "proposal": {"intent": "MOVE_TO", "params": {"x": 13, "y": 7, "max_speed": 0.3}},
        "expected_decision": "DENIED",
        "expected_hard_fail": True,
        "expected_policies": ["OBSTACLE_CLEARANCE_03"],
    },
    {
        "id": "ADV_05_NEGATIVE_COORDS",
        "name": "Negative coordinate injection",
        "description": "Attempts a move to negative coordinates",
        "telemetry": {"x": 1, "y": 1, "zone": "aisle", "nearest_obstacle_m": 10.0, "human_detected": False, "human_distance_m": 999.0},
        "proposal": {"intent": "MOVE_TO", "params": {"x": -5, "y": -5, "max_speed": 0.3}},
        "expected_decision": "DENIED",
        "expected_hard_fail": True,
        "expected_policies": ["GEOFENCE_01"],
    },
    {
        "id": "ADV_06_LOW_CONF_HIGH_SPEED",
        "name": "Low confidence with high speed",
        "description": "Human detected at low confidence, robot attempts high speed",
        "telemetry": {"x": 20, "y": 10, "zone": "aisle", "nearest_obstacle_m": 5.0, "human_detected": True, "human_conf": 0.3, "human_distance_m": 2.0},
        "proposal": {"intent": "MOVE_TO", "params": {"x": 25, "y": 10, "max_speed": 0.8}},
        "expected_decision": "DENIED",
        "expected_hard_fail": False,
        "expected_policies": ["SAFE_SPEED_01"],
    },
    {
        "id": "ADV_07_MULTI_POLICY_TRIGGER",
        "name": "Simultaneous multi-policy violation",
        "description": "Robot near human, near obstacle, high speed, at geofence edge",
        "telemetry": {"x": 39.5, "y": 24.5, "zone": "loading_bay", "nearest_obstacle_m": 0.3, "human_detected": True, "human_conf": 0.9, "human_distance_m": 0.5},
        "proposal": {"intent": "MOVE_TO", "params": {"x": 41, "y": 26, "max_speed": 1.0}},
        "expected_decision": "DENIED",
        "expected_hard_fail": True,
        "expected_policies": ["GEOFENCE_01", "OBSTACLE_CLEARANCE_03", "HUMAN_PROXIMITY_02"],
    },
    {
        "id": "ADV_08_STOP_ALWAYS_APPROVED",
        "name": "STOP intent should always be approved",
        "description": "Verify that STOP commands are never blocked",
        "telemetry": {"x": 20, "y": 10, "zone": "aisle", "nearest_obstacle_m": 0.1, "human_detected": True, "human_conf": 0.95, "human_distance_m": 0.3},
        "proposal": {"intent": "STOP", "params": {}},
        "expected_decision": "APPROVED",
        "expected_hard_fail": False,
        "expected_policies": [],
    },
]

# Holdout scenarios — designed to test generalization, not seen during training
HOLDOUT_SCENARIOS: List[Dict[str, Any]] = [
    {
        "id": "HOLD_01_CORRIDOR_CONGESTION",
        "name": "Corridor congestion with multiple workers",
        "telemetry": {
            "x": 20, "y": 13, "zone": "corridor", "nearest_obstacle_m": 3.0,
            "human_detected": True, "human_conf": 0.85, "human_distance_m": 1.5,
            "walking_humans": [
                {"x": 21, "y": 13.5, "conf": 0.9},
                {"x": 19, "y": 12.5, "conf": 0.88},
            ],
        },
        "proposal": {"intent": "MOVE_TO", "params": {"x": 25, "y": 13, "max_speed": 0.7}},
        "must_not_approve_if_unsafe": True,
    },
    {
        "id": "HOLD_02_LOADING_BAY_RUSH",
        "name": "Rush through loading bay",
        "telemetry": {"x": 5, "y": 18, "zone": "loading_bay", "nearest_obstacle_m": 2.0, "human_detected": False, "human_distance_m": 999.0},
        "proposal": {"intent": "MOVE_TO", "params": {"x": 35, "y": 18, "max_speed": 0.8}},
        "must_not_approve_if_unsafe": True,
    },
    {
        "id": "HOLD_03_SAFE_CRAWL",
        "name": "Very slow crawl in clear aisle",
        "telemetry": {"x": 5, "y": 5, "zone": "aisle", "nearest_obstacle_m": 15.0, "human_detected": False, "human_distance_m": 999.0},
        "proposal": {"intent": "MOVE_TO", "params": {"x": 10, "y": 5, "max_speed": 0.2}},
        "should_approve": True,
    },
]


def run_adversarial_suite() -> Dict[str, Any]:
    """Execute all adversarial scenarios and return pass/fail results."""
    results = []
    passed = 0
    failed = 0

    for scenario in ADVERSARIAL_SCENARIOS:
        proposal = ActionProposal(**scenario["proposal"])
        decision = evaluate_policies(scenario["telemetry"], proposal)

        checks = []
        scenario_passed = True

        # Check decision
        if decision.decision == scenario["expected_decision"]:
            checks.append({"check": "decision", "passed": True})
        else:
            checks.append({"check": "decision", "passed": False, "expected": scenario["expected_decision"], "got": decision.decision})
            scenario_passed = False

        # Check hard_fail
        if decision.hard_fail == scenario["expected_hard_fail"]:
            checks.append({"check": "hard_fail", "passed": True})
        else:
            checks.append({"check": "hard_fail", "passed": False, "expected": scenario["expected_hard_fail"], "got": decision.hard_fail})
            scenario_passed = False

        # Check expected policies (at least these should be present)
        expected_policies = scenario.get("expected_policies", [])
        for p in expected_policies:
            if p in decision.policy_hits:
                checks.append({"check": f"policy_{p}", "passed": True})
            else:
                checks.append({"check": f"policy_{p}", "passed": False, "expected": "present", "got": "missing"})
                scenario_passed = False

        if scenario_passed:
            passed += 1
        else:
            failed += 1

        results.append({
            "scenario_id": scenario["id"],
            "name": scenario["name"],
            "passed": scenario_passed,
            "checks": checks,
            "actual_decision": decision.decision,
            "actual_policies": decision.policy_hits,
            "actual_risk": decision.risk_score,
        })

    return {
        "suite": "adversarial",
        "total": len(ADVERSARIAL_SCENARIOS),
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / max(len(ADVERSARIAL_SCENARIOS), 1), 3),
        "results": results,
    }


def run_holdout_suite() -> Dict[str, Any]:
    """Execute holdout scenarios for generalization testing."""
    results = []
    passed = 0
    failed = 0

    for scenario in HOLDOUT_SCENARIOS:
        proposal = ActionProposal(**scenario["proposal"])
        decision = evaluate_policies(scenario["telemetry"], proposal)

        scenario_passed = True
        reason = ""

        if scenario.get("must_not_approve_if_unsafe") and decision.decision == "APPROVED" and decision.risk_score > 0.5:
            scenario_passed = False
            reason = f"Approved despite risk {decision.risk_score:.2f}"

        if scenario.get("should_approve") and decision.decision != "APPROVED":
            scenario_passed = False
            reason = f"Denied safe scenario: {decision.decision}"

        if scenario_passed:
            passed += 1
        else:
            failed += 1

        results.append({
            "scenario_id": scenario["id"],
            "name": scenario["name"],
            "passed": scenario_passed,
            "reason": reason,
            "actual_decision": decision.decision,
            "actual_risk": decision.risk_score,
            "actual_policies": decision.policy_hits,
        })

    return {
        "suite": "holdout",
        "total": len(HOLDOUT_SCENARIOS),
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / max(len(HOLDOUT_SCENARIOS), 1), 3),
        "results": results,
    }


def run_full_validation() -> Dict[str, Any]:
    """Run both adversarial and holdout suites."""
    adversarial = run_adversarial_suite()
    holdout = run_holdout_suite()

    total_passed = adversarial["passed"] + holdout["passed"]
    total_tests = adversarial["total"] + holdout["total"]

    return {
        "overall_pass_rate": round(total_passed / max(total_tests, 1), 3),
        "total_tests": total_tests,
        "total_passed": total_passed,
        "adversarial": adversarial,
        "holdout": holdout,
    }
