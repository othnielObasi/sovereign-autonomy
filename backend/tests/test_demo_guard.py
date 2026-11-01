"""Public demo guardrails: shared settings read-only, one mission at a time, hourly budgets."""
from fastapi.testclient import TestClient

from conftest import _TestSession
from app.config import settings
from app import demo_guard


def _client(monkeypatch, **overrides):
    from app.main import app
    monkeypatch.setattr(settings, "public_demo", True)
    for k, v in overrides.items():
        monkeypatch.setattr(settings, k, v)
    monkeypatch.setattr(demo_guard, "budget", demo_guard.HourlyBudget())
    monkeypatch.setattr(demo_guard, "_active_run", lambda: None)
    return TestClient(app)


def test_off_by_default_changes_nothing():
    assert settings.public_demo is False


def test_rule_changes_are_read_only(monkeypatch):
    c = _client(monkeypatch)
    r = c.post("/policies/proposals", json={"changes": {"ZONE_SPEED_LIMITS.aisle": 0.45}, "created_by": "x"})
    assert r.status_code == 403 and r.json()["public_demo"] is True
    assert c.post("/policies/rollback", json={}).status_code == 403
    assert c.delete("/missions/abc").status_code == 403


def test_reads_still_work(monkeypatch):
    c = _client(monkeypatch)
    assert c.get("/health").status_code == 200
    assert c.get("/policies").status_code == 200


def test_one_mission_at_a_time(monkeypatch):
    c = _client(monkeypatch)
    monkeypatch.setattr(demo_guard, "_active_run", lambda: "run_busy")
    r = c.post("/missions/m1/start")
    assert r.status_code == 409 and r.json()["active_run_id"] == "run_busy"
    assert c.post("/runs/r1/resume").status_code == 409


def test_hourly_budget_on_paid_actions(monkeypatch):
    c = _client(monkeypatch, demo_vision_checks_per_hour=2)
    codes = [c.post("/perception/check").status_code for _ in range(3)]
    assert codes[:2] != [429, 429] and codes[2] == 429


def test_budget_window_slides():
    b = demo_guard.HourlyBudget()
    assert b.take("k", 1, now=0) is None
    assert b.take("k", 1, now=10) is not None
    assert b.take("k", 1, now=3601) is None
