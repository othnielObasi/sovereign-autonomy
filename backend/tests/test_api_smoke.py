"""API smoke tests using FastAPI TestClient."""

import json
from contextlib import nullcontext

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_root(client: TestClient):
    r = client.get("/")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "content-security-policy" in r.headers


def test_health(client: TestClient):
    from app.api import routes_health
    from unittest.mock import AsyncMock, patch, MagicMock

    class _Conn:
        def execute(self, _query):
            return None

    class _Engine:
        def connect(self):
            return nullcontext(_Conn())

    original_engine = routes_health.engine
    routes_health.engine = _Engine()

    # Mock httpx.AsyncClient to return 200 for sim check
    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    try:
        with patch("app.api.routes_health.httpx.AsyncClient", return_value=mock_client):
            r = client.get("/health")
    finally:
        routes_health.engine = original_engine

    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "gemini_enabled" in data
    assert data["checks"] == {"database": "ok", "simulator": "ok"}


def test_dev_token_disabled_when_overridden(client: TestClient):
    from app.auth import routes as auth_routes

    original = auth_routes.settings.allow_dev_tokens
    auth_routes.settings.allow_dev_tokens = False
    try:
        r = client.post("/auth/dev-token")
    finally:
        auth_routes.settings.allow_dev_tokens = original

    assert r.status_code == 404


def test_rate_limit_returns_429_when_exceeded(client: TestClient):
    from app.config import settings

    original_enabled = settings.rate_limit_enabled
    original_limit = settings.rate_limit_requests_per_minute
    app.state.rate_limiter.reset()
    settings.rate_limit_enabled = True
    settings.rate_limit_requests_per_minute = 2

    headers = {"x-forwarded-for": "203.0.113.10"}
    try:
        r1 = client.get("/missions", headers=headers)
        r2 = client.get("/missions", headers=headers)
        r3 = client.get("/missions", headers=headers)
    finally:
        settings.rate_limit_enabled = original_enabled
        settings.rate_limit_requests_per_minute = original_limit
        app.state.rate_limiter.reset()

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429
    assert r3.json()["detail"] == "Rate limit exceeded"
    assert r3.headers["retry-after"]


def test_list_missions_empty(client: TestClient):
    r = client.get("/missions")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_create_mission(client: TestClient):
    payload = {"title": "Test Mission", "goal": {"x": 10, "y": 5}}
    r = client.post("/missions", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["title"] == "Test Mission"
    assert data["id"].startswith("mis_")
    assert data["goal"]["x"] == 10


def test_get_mission(client: TestClient):
    payload = {"title": "Get Test", "goal": {"x": 1, "y": 2}}
    created = client.post("/missions", json=payload).json()
    mid = created["id"]

    r = client.get(f"/missions/{mid}")
    assert r.status_code == 200
    assert r.json()["id"] == mid


def test_get_mission_not_found(client: TestClient):
    r = client.get("/missions/mis_nonexistent")
    assert r.status_code == 404


def test_delete_mission(client: TestClient):
    payload = {"title": "Delete Me", "goal": {"x": 0, "y": 0}}
    created = client.post("/missions", json=payload).json()
    mid = created["id"]

    r = client.delete(f"/missions/{mid}")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # Soft-deleted missions still exist but are excluded from list
    r2 = client.get(f"/missions/{mid}")
    assert r2.status_code == 200
    assert r2.json()["status"] == "deleted"

    # Ensure deleted missions don't appear in list
    listed = client.get("/missions").json()
    assert mid not in [m["id"] for m in listed]


def test_list_policies(client: TestClient):
    r = client.get("/policies")
    assert r.status_code == 200
    policies = r.json()
    assert isinstance(policies, list)
    assert len(policies) >= 5
    ids = [p["policy_id"] for p in policies]
    assert "GEOFENCE_01" in ids
    assert "SAFE_SPEED_01" in ids


def test_policies_test_endpoint(client: TestClient):
    payload = {
        "telemetry": {"x": 5, "y": 5, "zone": "aisle", "nearest_obstacle_m": 5.0, "human_detected": False, "human_conf": 0.0},
        "proposal": {"intent": "MOVE_TO", "params": {"x": 6, "y": 6, "max_speed": 0.3}, "rationale": "test"},
    }
    r = client.post("/policies/test", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["decision"] == "APPROVED"


def test_list_runs(client: TestClient):
    r = client.get("/runs")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_get_run_not_found(client: TestClient):
    r = client.get("/runs/run_nonexistent")
    assert r.status_code == 404


def test_compliance_frameworks(client: TestClient):
    r = client.get("/compliance/frameworks")
    assert r.status_code == 200
    data = r.json()
    ids = [f["id"] for f in data["frameworks"]]
    assert "ISO_42001" in ids
    assert "EU_AI_ACT" in ids


def test_duplicate_start_returns_409(client: TestClient):
    """Starting a run for a mission that already has an active run returns 409."""
    payload = {"title": "Dup Start Test", "goal": {"x": 5, "y": 5}}
    created = client.post("/missions", json=payload).json()
    mid = created["id"]

    # First start should succeed
    r1 = client.post(f"/missions/{mid}/start")
    assert r1.status_code == 200
    run_id = r1.json()["run_id"]

    # Second start on same mission should be rejected
    r2 = client.post(f"/missions/{mid}/start")
    assert r2.status_code == 409
    assert "active run" in r2.json()["detail"].lower()

    # Cleanup: stop the run so it doesn't interfere with other tests
    client.post(f"/runs/{run_id}/stop")
