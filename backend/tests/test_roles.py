"""Roles: viewer < operator < admin. Stopping is open to all; mission control needs an
operator; activating or rolling back safety rules needs an admin. Enforced in
production; in development a token that is sent must still carry the role."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth.jwt import create_access_token
from app.auth.roles import authenticate, hash_password, verify_password
from app.config import settings
from app.main import app


def bearer(name: str, role: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(name, role=role)}"}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def production(monkeypatch):
    monkeypatch.setattr(settings, "auth_required", True)
    monkeypatch.setattr(settings, "allow_dev_tokens", False)


def test_password_hashing_and_login(monkeypatch, client):
    stored = hash_password("correct horse battery", iterations=1000)
    assert verify_password("correct horse battery", stored) and not verify_password("wrong", stored)
    assert not verify_password("x", "garbage")
    monkeypatch.setattr(settings, "auth_accounts", f"alice:admin:{stored};bob:operator:{hash_password('pw-for-bob-123', iterations=1000)}")
    assert authenticate("alice", "correct horse battery").role == "admin"
    assert authenticate("alice", "nope") is None and authenticate("nobody", "x") is None

    r = client.post("/auth/login", json={"username": "bob", "password": "pw-for-bob-123"})
    assert r.status_code == 200 and r.json()["role"] == "operator"
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()
    assert me == {"signed_in": True, "user": "bob", "role": "operator", "auth_required": settings.require_auth}
    assert client.post("/auth/login", json={"username": "bob", "password": "wrong"}).status_code == 401


def test_dev_tokens_carry_a_role_and_are_off_in_production(client, production):
    assert client.post("/auth/dev-token").status_code == 404


def test_production_needs_operator_for_mission_control(client, production):
    body = {"title": "Role check", "bay_id": "B-03"}
    assert client.post("/missions", json=body).status_code == 401
    assert client.post("/missions", json=body, headers=bearer("v", "viewer")).status_code == 403
    r = client.post("/missions", json=body, headers=bearer("op", "operator"))
    assert r.status_code == 200
    mid = r.json()["id"]
    assert client.delete(f"/missions/{mid}", headers=bearer("op", "operator")).status_code in (200, 204)


def test_rule_activation_needs_admin(client, production):
    for path in ("/policies/proposals/does-not-exist/activate",):
        assert client.post(path, json={}, headers=bearer("op", "operator")).status_code == 403
        assert client.post(path, json={}, headers=bearer("ad", "admin")).status_code == 404   # past the role check
    assert client.post("/policies/rollback", json={"reason": "role check"}, headers=bearer("op", "operator")).status_code == 403


def test_stopping_needs_no_sign_in_even_in_production(client, production, monkeypatch, tmp_path):
    import os
    import app.api.routes_runs as rr
    import app.services.execution_authority as ea

    class Sim:
        async def estop(self, **kw):
            return {"ok": True}

        async def send_command(self, cmd):
            return {"ok": True}

        async def get_telemetry(self):
            return {"speed": 0.0, "target": None}

    monkeypatch.setattr(ea, "_authority", ea.ExecutionAuthority(secret=os.environ["PERMIT_SECRET"],
                                                                db_path=str(tmp_path / "r.db")))
    monkeypatch.setattr(rr.get_run_svc(), "sim", Sim())
    assert client.post("/authority/kill", json={"scope": "global"}).status_code == 200
    assert client.post("/authority/reset", json={"scope": "global"}, headers=bearer("v", "viewer")).status_code == 403
    assert client.post("/authority/reset", json={"scope": "global"}, headers=bearer("op", "operator")).status_code == 200
    assert client.post("/authority/drills", json={}).status_code == 401


def test_development_still_checks_a_token_that_is_sent(client):
    assert client.post("/policies/rollback", json={"reason": "role check"}, headers=bearer("v", "viewer")).status_code == 403
