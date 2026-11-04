"""Pilot request form: public submit, validation, spam trap, limits, operator-only reading."""
import pytest
from fastapi.testclient import TestClient

import app.api.routes_pilot as rp
from app.demo_guard import HourlyBudget
from app.main import app

GOOD = {"name": "Ada Lovelace", "email": "ada@example.com", "organisation": "Example Pharma", "role": "Head of Operations",
        "site_type": "pharma", "fleet_size": "6-20", "message": "Mixed AMR and humanoid fleet in a cleanroom.", "consent": True}


@pytest.fixture(autouse=True)
def fresh_limits(monkeypatch):
    monkeypatch.setattr(rp, "_limits", HourlyBudget())


@pytest.fixture
def client():
    return TestClient(app)


def stored(client):
    # Use the app's own (test-overridden) session; importing conftest again would make a new database
    from app.db.models import PilotRequest
    from app.deps import get_db
    gen = app.dependency_overrides.get(get_db, get_db)()
    db = next(gen)
    try:
        return db.query(PilotRequest).all()
    finally:
        gen.close()


def test_valid_request_is_stored_with_a_reference(client):
    before = len(stored(client))
    r = client.post("/pilot-requests", json=GOOD)
    assert r.status_code == 200 and r.json()["ok"] and r.json()["reference"].startswith("PR-")
    rows = stored(client)
    assert len(rows) == before + 1
    row = rows[-1]
    assert row.reference == r.json()["reference"] and row.organisation == "Example Pharma"
    assert row.source_hash and "testclient" not in row.source_hash   # address kept only as a hash


@pytest.mark.parametrize("change", [{"email": "not-an-email"}, {"consent": False}, {"site_type": "spaceport"},
                                    {"name": "A"}, {"message": "x" * 2001}])
def test_invalid_input_is_refused(client, change):
    assert client.post("/pilot-requests", json={**GOOD, **change}).status_code == 422


def test_spam_trap_answers_ok_but_stores_nothing(client):
    before = len(stored(client))
    r = client.post("/pilot-requests", json={**GOOD, "website": "http://spam.example"})
    assert r.status_code == 200 and r.json()["ok"]
    assert len(stored(client)) == before


def test_one_sender_is_limited_per_hour(client):
    codes = [client.post("/pilot-requests", json=GOOD).status_code for _ in range(rp.PER_SENDER_PER_HOUR + 1)]
    assert codes[:-1] == [200] * rp.PER_SENDER_PER_HOUR and codes[-1] == 429


def test_reading_requests_needs_a_signed_in_operator(client):
    assert client.get("/pilot-requests").status_code == 401
