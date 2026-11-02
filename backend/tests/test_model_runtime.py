"""Shared model plumbing and the Muse planner's tiers: reasoning-model first, fast
models for steps, <think> stripping, fallbacks, clamping, usage log and /llm/usage.

No network: httpx.MockTransport stands in for the Meta Model API and Baseten.
"""
from __future__ import annotations

import asyncio
import json
from typing import List

import httpx
import pytest

from app.config import settings
from app.services import model_runtime as rt
from app.services.model_runtime import strip_reasoning, usage_log
from app.services.muse_planner import MusePlanner

REASONING = "muse-spark-1.3"
OPEN = "meta-models/muse-spark-open-1026"


@pytest.fixture
def muse(monkeypatch):
    monkeypatch.setattr(settings, "model_api_key", "LLM_test")
    monkeypatch.setattr(settings, "baseten_api_key", "bt_test")
    monkeypatch.setattr(settings, "muse_plan_with_camera", False)
    usage_log.clear()
    yield
    usage_log.clear()


def _install(monkeypatch, handler) -> List[dict]:
    seen: List[dict] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append({"body": body, "host": request.url.host})
        return handler(body)

    monkeypatch.setattr(rt, "_client", httpx.AsyncClient(transport=httpx.MockTransport(wrapped)))
    return seen


def _completion(content: str, prompt_tokens: int = 100, completion_tokens: int = 20) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}],
                                     "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}})


PLAN_JSON = json.dumps({"waypoints": [{"x": 5, "y": 5, "max_speed": 0.5}, {"x": 12, "y": 8, "max_speed": 0.4}],
                        "rationale": "avoid worker", "estimated_time_s": 20})
MOVE_JSON = json.dumps({"intent": "MOVE_TO", "params": {"x": 3, "y": 4, "max_speed": 0.4}, "rationale": "step"})
TELEMETRY = {"x": 1.0, "y": 1.0, "zone": "aisle", "human_detected": False}
GOAL = {"x": 12.0, "y": 8.0}


def test_mission_planning_uses_the_reasoning_model_first(muse, monkeypatch):
    seen = _install(monkeypatch, lambda body: _completion(PLAN_JSON))
    plan = asyncio.run(MusePlanner().generate_plan(TELEMETRY, "go", GOAL))
    assert seen[0]["body"]["model"] == REASONING and plan["model_used"] == REASONING


def test_planning_falls_back_to_a_fast_model_when_the_reasoning_model_fails(muse, monkeypatch):
    def handler(body):
        return httpx.Response(503, text="busy") if body["model"] == REASONING else _completion(PLAN_JSON)
    _install(monkeypatch, handler)
    plan = asyncio.run(MusePlanner().generate_plan(TELEMETRY, "go", GOAL))
    assert plan["model_used"] in (OPEN, REASONING) and plan["model_used"] != "deterministic_fallback"
    assert plan["model_used"] == OPEN


def test_steps_use_the_fast_tier_only(muse, monkeypatch):
    seen = _install(monkeypatch, lambda body: _completion(MOVE_JSON))
    planner = MusePlanner()
    asyncio.run(planner.propose(TELEMETRY, GOAL, "go"))
    assert seen and all(s["body"].get("reasoning_effort") in (None, "low") for s in seen)
    assert planner.current_tier == "fast"


def test_tier_resets_after_planning(muse, monkeypatch):
    _install(monkeypatch, lambda body: _completion(PLAN_JSON))
    planner = MusePlanner()
    asyncio.run(planner.generate_plan(TELEMETRY, "go", GOAL))
    assert planner.current_tier == "fast"


def test_strip_reasoning_removes_think_blocks_with_braces():
    raw = '<think>maybe {"x": 99}? no.</think>\n{"intent": "STOP", "params": {}, "rationale": "done"}'
    assert strip_reasoning(raw).startswith('{"intent": "STOP"')


def test_strip_reasoning_handles_truncated_think():
    assert strip_reasoning("<think>still reasoning {") == ""


def test_think_block_does_not_break_a_proposal(muse, monkeypatch):
    _install(monkeypatch, lambda body: _completion('<think>consider {"x": 0, "y": 0}</think>' + MOVE_JSON))
    assert asyncio.run(MusePlanner().propose(TELEMETRY, GOAL, "go")).params["x"] == 3.0


def test_all_models_failing_returns_the_labelled_fallback(muse, monkeypatch):
    _install(monkeypatch, lambda body: httpx.Response(500, text="down"))
    plan = asyncio.run(MusePlanner().generate_plan(TELEMETRY, "go", GOAL))
    assert plan["model_used"] == "deterministic_fallback" and plan["waypoints"][-1]["x"] == GOAL["x"]


def test_waypoints_are_clamped_to_the_site(muse, monkeypatch):
    wild = json.dumps({"waypoints": [{"x": 9999, "y": -50, "max_speed": 7}], "rationale": "x"})
    _install(monkeypatch, lambda body: _completion(wild))
    wp = asyncio.run(MusePlanner().generate_plan(TELEMETRY, "go", None))["waypoints"][0]
    from app.world_model import GEOFENCE
    assert GEOFENCE["min_x"] <= wp["x"] <= GEOFENCE["max_x"] and GEOFENCE["min_y"] <= wp["y"] <= GEOFENCE["max_y"]
    assert wp["max_speed"] <= 1.0


def test_usage_log_records_tier_latency_and_tokens(muse, monkeypatch):
    _install(monkeypatch, lambda body: _completion(PLAN_JSON, 321, 45))
    asyncio.run(MusePlanner().generate_plan(TELEMETRY, "go", GOAL))
    row = usage_log.summary()["by_model"][0]
    assert row["tier"] == "reasoning" and row["model"] == REASONING and row["ok"] == 1
    assert row["prompt_tokens"] == 321 and row["completion_tokens"] == 45 and row["p50_latency_ms"] is not None


def test_usage_endpoint(muse, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    _install(monkeypatch, lambda body: _completion(PLAN_JSON))
    asyncio.run(MusePlanner().generate_plan(TELEMETRY, "go", GOAL))
    with TestClient(app) as client:
        body = client.get("/llm/usage").json()
    assert body["provider"] == "muse" and body["summary"]["total_calls"] >= 1


def test_without_meta_keys_the_deterministic_planner_is_used(monkeypatch):
    from app.services.gemini_planner import GeminiPlanner
    from app.services.llm_factory import get_planner
    monkeypatch.setattr(settings, "model_api_key", None)
    monkeypatch.setattr(settings, "baseten_api_key", None)
    monkeypatch.setattr(settings, "gemini_api_key", None)
    planner = get_planner()
    assert type(planner) is GeminiPlanner and settings.planner_provider == "fallback"
