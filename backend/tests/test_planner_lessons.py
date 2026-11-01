"""Planner learning loop: lessons distilled from gate decisions, retrieved per route,
fed to the Nemotron planner, and never able to change the rules."""
from __future__ import annotations

import asyncio
import json
import uuid

import httpx
import pytest
from conftest import _TestSession
from fastapi.testclient import TestClient

from app.config import settings
from app.db.models import AgentMemoryEntry
from app.main import app
from app.policies.versioning import policy_version_hash
from app.schemas.governance import ActionProposal
from app.services import nemotron_planner as np_mod
from app.services import planner_lessons as pl
from app.services.governance_engine import GovernanceEngine
from app.services.nemotron_planner import NemotronPlanner

AISLE = {"x": 12.3, "y": 8.1, "zone": "aisle", "speed": 0.3, "human_detected": False, "nearest_obstacle_m": 5.0}


@pytest.fixture
def db():
    s = _TestSession()
    s.query(AgentMemoryEntry).filter(AgentMemoryEntry.category == pl.CATEGORY_SPATIAL).delete()
    s.commit()
    yield s
    s.close()


def _record(db, run_id, telemetry, speed, executed=False):
    GovernanceEngine().evaluate_and_record(
        db, run_id, telemetry,
        ActionProposal(intent="MOVE_TO", params={"x": 14.0, "y": 8.0, "max_speed": speed}, rationale="t"),
        was_executed=executed,
    )
    db.commit()


def _run_with_speeding(db, n_denials=3):
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    for _ in range(n_denials):
        _record(db, run_id, AISLE, 0.9)                 # SAFE_SPEED_01 -> NEEDS_REVIEW
    _record(db, run_id, AISLE, 0.45, executed=True)     # approved in the same cell
    return run_id


# -- distillation --------------------------------------------------------------

def test_distill_creates_spatial_lesson_with_approved_speed(db):
    run_id = _run_with_speeding(db)
    lessons = pl.distill_run(db, run_id)

    assert len(lessons) == 1
    c = lessons[0]
    assert c["policy"] == "SAFE_SPEED_01" and c["zone"] == "aisle"
    assert (c["cell_x"], c["cell_y"]) == (13.0, 9.0)        # 2 m grid cell containing (12.3, 8.1)
    assert c["denials"] == 3 and c["runs"] == [run_id]
    assert c["max_approved_speed"] == pytest.approx(0.45)
    assert c["policy_version"] == policy_version_hash()
    assert "approved at up to 0.45 m/s" in c["text"]


def test_distill_is_idempotent_and_accumulates_across_runs(db):
    r1 = _run_with_speeding(db, 2)
    pl.distill_run(db, r1)
    pl.distill_run(db, r1)                                  # same run again: no double count
    r2 = _run_with_speeding(db, 3)
    pl.distill_run(db, r2)

    rows = pl.all_lessons(db)
    assert len(rows) == 1
    assert rows[0]["denials"] == 5
    assert set(rows[0]["runs"]) == {r1, r2}
    assert "across 2 runs" in rows[0]["text"]


def test_hard_policy_lesson_says_route_around(db):
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    _record(db, run_id, dict(AISLE, walking_humans=[{"x": 12.8, "y": 8.1, "conf": 0.95}]), 0.3)
    c = pl.distill_run(db, run_id)[0]
    assert c["policy"] == "WORKER_PROXIMITY_06"
    assert "Workers often cross here" in c["text"]
    assert "approved at up to" not in c["text"]  # a moving hazard: approved speeds are not evidence


def test_distill_does_not_change_the_rules(db):
    before = policy_version_hash()
    pl.distill_run(db, _run_with_speeding(db))
    assert policy_version_hash() == before


# -- retrieval -----------------------------------------------------------------

def test_route_retrieval_keeps_corridor_lessons_only(db):
    pl.distill_run(db, _run_with_speeding(db))

    on_route = pl.lessons_for_route(db, {"x": 2.0, "y": 8.0}, {"x": 30.0, "y": 8.0})
    off_route = pl.lessons_for_route(db, {"x": 2.0, "y": 22.0}, {"x": 30.0, "y": 22.0})
    replan = pl.lessons_for_route(db, {"x": 2.0, "y": 22.0}, {"x": 30.0, "y": 22.0}, avoid={"x": 13.0, "y": 9.0})

    assert [l["policy"] for l in on_route] == ["SAFE_SPEED_01"]
    assert off_route == []
    assert len(replan) == 1                                 # the blocked waypoint pulls it back in


def test_lessons_from_older_policy_versions_are_not_retrieved(db, monkeypatch):
    pl.distill_run(db, _run_with_speeding(db))
    monkeypatch.setattr(pl, "policy_version_hash", lambda: "rules-changed")
    assert pl.lessons_for_route(db, {"x": 2.0, "y": 8.0}, {"x": 30.0, "y": 8.0}) == []
    assert pl.all_lessons(db) == []
    assert len(pl.all_lessons(db, current_version_only=False)) == 1


# -- planner integration ---------------------------------------------------------

PLAN_JSON = json.dumps({"waypoints": [{"x": 6, "y": 8, "max_speed": 0.45}, {"x": 30, "y": 8, "max_speed": 0.45}],
                        "rationale": "slow through aisle", "estimated_time_s": 60})


def test_planner_prompt_carries_lessons_and_reports_ids(db, monkeypatch):
    monkeypatch.setattr(settings, "nebius_api_key", "k")
    monkeypatch.setattr(settings, "nemotron_fast_models", "nvidia/fast")
    monkeypatch.setattr(settings, "nemotron_reasoning_model", "nvidia/ultra")
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": PLAN_JSON}}], "usage": {}})

    monkeypatch.setattr(np_mod, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    pl.distill_run(db, _run_with_speeding(db))
    lessons = pl.lessons_for_route(db, {"x": 2.0, "y": 8.0}, {"x": 30.0, "y": 8.0})
    plan = asyncio.run(NemotronPlanner().generate_plan(
        {"x": 2.0, "y": 8.0}, "deliver to dock", {"x": 30.0, "y": 8.0}, lessons=lessons))

    prompt = seen[0]["messages"][-1]["content"]
    assert "LESSONS FROM PAST RUNS" in prompt
    assert lessons[0]["text"] in prompt
    assert "the gate still evaluates every move" in prompt
    assert plan["lessons_applied"] == [lessons[0]["id"]]


def test_no_lessons_means_no_lesson_block(monkeypatch):
    monkeypatch.setattr(settings, "nebius_api_key", "k")
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": PLAN_JSON}}], "usage": {}})

    monkeypatch.setattr(np_mod, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    plan = asyncio.run(NemotronPlanner().generate_plan({"x": 2, "y": 8}, "go", {"x": 30, "y": 8}))
    assert "LESSONS FROM PAST RUNS" not in seen[0]["messages"][-1]["content"]
    assert plan["lessons_applied"] == []


# -- API -------------------------------------------------------------------------

def test_lesson_endpoints(db):
    pl.distill_run(db, _run_with_speeding(db))
    with TestClient(app) as client:
        all_ = client.get("/agent/lessons").json()
        route = client.get("/agent/lessons/route", params={"sx": 2, "sy": 8, "gx": 30, "gy": 8}).json()
    assert all_["count"] == 1 and all_["policy_version"] == policy_version_hash()
    assert route["lessons"][0]["policy"] == "SAFE_SPEED_01"
    assert route["prompt_block"].startswith("LESSONS FROM PAST RUNS")
