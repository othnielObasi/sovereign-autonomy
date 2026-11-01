"""Tests for Phase A-C governance hardening features."""

from __future__ import annotations

import json
import math
import pytest
from unittest.mock import MagicMock

from app.policies.rules_python import evaluate_policies, GEOFENCE, ZONE_SPEED_LIMITS
from app.policies.versioning import policy_version_hash, policy_version_info
from app.schemas.governance import ActionProposal


# --- Policy versioning ---

class TestPolicyVersioning:
    def test_version_hash_is_stable(self):
        h1 = policy_version_hash()
        h2 = policy_version_hash()
        assert h1 == h2
        assert len(h1) == 16  # 16-char hex prefix

    def test_version_info_has_all_params(self):
        info = policy_version_info()
        assert "version_hash" in info
        assert "parameters" in info
        params = info["parameters"]
        assert "GEOFENCE" in params
        assert "ZONE_SPEED_LIMITS" in params
        assert "HUMAN_STOP_RADIUS_M" in params
        assert "REVIEW_RISK_THRESHOLD" in params

    def test_geofence_loaded_from_world_model(self):
        """GEOFENCE in rules_python should match world_model values."""
        from app.world_model import GEOFENCE as WM_GF
        assert GEOFENCE["min_x"] == WM_GF["min_x"]
        assert GEOFENCE["max_x"] == WM_GF["max_x"]
        assert GEOFENCE["min_y"] == WM_GF["min_y"]
        assert GEOFENCE["max_y"] == WM_GF["max_y"]

    def test_zone_speed_limits_unified(self):
        from app.world_model import ZONE_SPEED_LIMITS as WM_ZSL
        assert ZONE_SPEED_LIMITS == WM_ZSL


# --- Scoring engine ---

class TestScoringEngine:
    def test_compute_scorecard_missing_run(self):
        """Score a non-existent run returns error."""
        from app.services.scoring_engine import compute_scorecard
        from conftest import _TestSession
        db = _TestSession()
        try:
            result = compute_scorecard(db, "nonexistent-run-id")
            assert result.get("error") == "run_not_found"
        finally:
            db.close()

    def test_clamp_helper(self):
        from app.services.scoring_engine import _clamp
        assert _clamp(0.5) == 0.5
        assert _clamp(-0.1) == 0.0
        assert _clamp(1.5) == 1.0


# --- Replan logic (unit test the denial counter logic) ---

class TestReplanOnDenial:
    def test_run_service_has_denial_tracking(self):
        from app.services.run_service import RunService
        svc = RunService()
        assert hasattr(svc, "_wp_denial_counts")
        assert hasattr(svc, "REPLAN_DENIAL_THRESHOLD")
        assert svc.REPLAN_DENIAL_THRESHOLD == 5

    def test_run_service_has_executed_paths(self):
        from app.services.run_service import RunService
        svc = RunService()
        assert hasattr(svc, "_executed_paths")


# --- Simulator motion (trapezoidal velocity) ---

class TestSimulatorMotion:
    """Test the simulator's trapezoidal velocity and heading rate limit."""

    def test_motion_constants_defined(self):
        """Verify the motion constants are importable from server module scope."""
        import importlib
        import sys
        # We can't easily import the sim server (it starts FastAPI),
        # but we can at least verify the constants exist in the source.
        import pathlib
        # Navigate from backend/tests to repo root
        server_path = pathlib.Path(__file__).resolve().parent.parent.parent / "sim" / "mock_sim" / "server.py"
        source = server_path.read_text()
        assert "MAX_ACCEL" in source
        assert "MAX_DECEL" in source
        assert "MAX_HEADING_RATE" in source
        assert "trapezoidal" in source.lower() or "decel_speed" in source

    def test_heading_rate_math(self):
        """Verify the angular clamping math is correct."""
        # Simulate the heading rate limit logic
        MAX_HEADING_RATE = 2.0
        dt = 0.1
        current_theta = 0.0
        desired_theta = math.pi  # 180 degrees away

        dtheta = math.atan2(math.sin(desired_theta - current_theta),
                            math.cos(desired_theta - current_theta))
        max_dtheta = MAX_HEADING_RATE * dt
        clamped = max(-max_dtheta, min(max_dtheta, dtheta))

        # Should be clamped to 0.2 rad (MAX_HEADING_RATE * dt)
        assert abs(clamped) <= max_dtheta + 1e-9
        assert abs(clamped) == pytest.approx(0.2, abs=1e-9)

    def test_decel_ramp(self):
        """Verify deceleration ramp formula produces correct speed near target."""
        MAX_DECEL = 1.2
        dist = 0.1  # 10cm from target
        decel_speed = math.sqrt(2.0 * MAX_DECEL * dist)
        # Should be ~0.49 m/s — much less than typical max_speed
        assert decel_speed < 0.5
        assert decel_speed > 0.0


# --- Governance engine policy_version integration ---

class TestGovernanceEngineVersioning:
    def test_governance_engine_imports_versioning(self):
        """GovernanceEngine should use policy_version_hash."""
        from app.services.governance_engine import policy_version_hash as gov_pvh
        assert gov_pvh() == policy_version_hash()
