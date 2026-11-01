"""Tests for Phase E services: adversarial, safety, memory, cross-run, path smoothing, world model."""

from __future__ import annotations

import json
import math
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.governance import ActionProposal
from app.policies.rules_python import evaluate_policies


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ── Adversarial validator (#15) ──

class TestAdversarialValidator:
    def test_geofence_probe_denied(self):
        """ADV_01: Movement outside geofence must be DENIED."""
        telemetry = {"x": 39.9, "y": 24.9, "zone": "loading_bay", "nearest_obstacle_m": 5.0,
                     "human_detected": False, "human_distance_m": 999.0}
        proposal = ActionProposal(intent="MOVE_TO", params={"x": 40.1, "y": 25.0, "max_speed": 0.3})
        result = evaluate_policies(telemetry, proposal)
        assert result.decision == "DENIED"
        assert result.hard_fail is True

    def test_stop_always_approved(self):
        """ADV_08: STOP intent should always be approved regardless of state."""
        telemetry = {"x": 20, "y": 10, "zone": "aisle", "nearest_obstacle_m": 0.1,
                     "human_detected": True, "human_conf": 0.95, "human_distance_m": 0.3}
        proposal = ActionProposal(intent="STOP", params={})
        result = evaluate_policies(telemetry, proposal)
        assert result.decision == "APPROVED"

    def test_human_proximity_stop(self):
        """ADV_03: Movement near a human ≤0.3m must be hard-denied."""
        telemetry = {"x": 5, "y": 5, "zone": "aisle", "nearest_obstacle_m": 10.0,
                     "human_detected": True, "human_conf": 0.95, "human_distance_m": 0.3}
        proposal = ActionProposal(intent="MOVE_TO", params={"x": 6, "y": 5, "max_speed": 0.5})
        result = evaluate_policies(telemetry, proposal)
        assert result.decision == "DENIED"
        assert result.hard_fail is True

    def test_negative_coords_denied(self):
        """ADV_05: Negative coordinates should be outside geofence."""
        telemetry = {"x": 1, "y": 1, "zone": "aisle", "nearest_obstacle_m": 10.0,
                     "human_detected": False, "human_distance_m": 999.0}
        proposal = ActionProposal(intent="MOVE_TO", params={"x": -5, "y": -5, "max_speed": 0.3})
        result = evaluate_policies(telemetry, proposal)
        assert result.decision == "DENIED"

    def test_full_adversarial_suite(self):
        """Run the full adversarial suite and verify pass rate ≥ 75%."""
        from app.services.adversarial_validator import run_adversarial_suite
        result = run_adversarial_suite()
        assert result["total"] >= 8
        assert result["pass_rate"] >= 0.75, f"Adversarial pass rate too low: {result['pass_rate']}"

    def test_full_holdout_suite(self):
        """Run holdout suite."""
        from app.services.adversarial_validator import run_holdout_suite
        result = run_holdout_suite()
        assert result["total"] >= 3

    def test_full_validation(self):
        """Run combined adversarial + holdout."""
        from app.services.adversarial_validator import run_full_validation
        result = run_full_validation()
        assert result["total_tests"] >= 11
        assert result["overall_pass_rate"] >= 0.5


# ── Adversarial API endpoint (#15) ──

def test_adversarial_api(client):
    r = client.get("/adversarial/validate")
    assert r.status_code == 200
    data = r.json()
    assert "adversarial" in data
    assert "holdout" in data
    assert data["total_tests"] >= 11


# ── Policy version API (#16) ──

def test_policy_versions_api(client):
    r = client.get("/policies/versions")
    assert r.status_code == 200
    # May be empty if no runs started yet
    assert isinstance(r.json(), list)


def test_policy_version_hash():
    from app.policies.versioning import policy_version_hash
    h = policy_version_hash()
    assert isinstance(h, str)
    assert len(h) == 16  # SHA256 hex[:16]


# ── Safety validator (#14) ──

def test_safety_validator_import():
    from app.services.safety_validator import validate_run_safety
    # Should be importable without error
    assert callable(validate_run_safety)


# ── Cross-run learning (#18) ──

def test_cross_run_learning_import():
    from app.services.cross_run_learning import aggregate_cross_run_lessons
    assert callable(aggregate_cross_run_lessons)


# ── Semantic memory (#17) ──

def test_persistent_memory_recall_similar():
    from app.services.persistent_memory import PersistentMemory
    mem = PersistentMemory()
    assert hasattr(mem, "recall_similar")


# ── World model single source (#24) ──

def test_world_model_zone_speed_limits():
    from app.world_model import ZONE_SPEED_LIMITS
    assert "aisle" in ZONE_SPEED_LIMITS
    assert "corridor" in ZONE_SPEED_LIMITS
    assert "loading_bay" in ZONE_SPEED_LIMITS
    assert ZONE_SPEED_LIMITS["aisle"] == 0.5
    assert ZONE_SPEED_LIMITS["corridor"] == 0.7
    assert ZONE_SPEED_LIMITS["loading_bay"] == 0.4


def test_world_model_loads_from_json():
    from app.world_model import GEOFENCE, ZONES, BAYS
    assert GEOFENCE["min_x"] == 0
    assert GEOFENCE["max_x"] == 40
    assert len(ZONES) == 4
    assert len(BAYS) >= 10


# ── Bezier path smoothing (#6) ──

def test_bezier_smoothing_basic():
    """Verify Bezier path smoothing produces more points than input."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'sim', 'mock_sim'))
    # Import from sim server
    from server import _smooth_path

    waypoints = [{"x": 0, "y": 0}, {"x": 10, "y": 0}, {"x": 10, "y": 10}]
    smoothed = _smooth_path(waypoints, resolution=10)
    assert len(smoothed) > len(waypoints)
    # First point should be near start
    assert abs(smoothed[0]["x"]) < 0.01
    # Last point should be near end
    assert abs(smoothed[-1]["x"] - 10) < 0.01
    assert abs(smoothed[-1]["y"] - 10) < 0.01


def test_bezier_two_points():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'sim', 'mock_sim'))
    from server import _smooth_path

    waypoints = [{"x": 0, "y": 0}, {"x": 10, "y": 5}]
    smoothed = _smooth_path(waypoints, resolution=5)
    assert len(smoothed) == 6  # 5 + 1
    assert abs(smoothed[-1]["x"] - 10) < 0.01


# ── Score trends API (#10) ──

def test_score_trends_api(client):
    r = client.get("/analytics/score-trends")
    assert r.status_code == 200
    data = r.json()
    assert "trends" in data
    assert "count" in data


# ── Divergence explanation API (#20) ──

def test_divergence_explanation_404(client):
    r = client.post("/runs/nonexistent/divergence-explanation")
    assert r.status_code == 404


# ── Executed path API (#3) ──

def test_executed_path_404(client):
    r = client.get("/runs/nonexistent/executed-path")
    assert r.status_code == 404


# ── Memory search API (#17) ──

def test_memory_search_api(client):
    r = client.get("/agent/memory/search?query=test")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ── Cross-run learning API (#18) ──

def test_cross_run_learning_api(client):
    r = client.get("/agent/cross-run-learning")
    assert r.status_code == 200
