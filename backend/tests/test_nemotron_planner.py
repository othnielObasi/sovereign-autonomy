"""Nemotron / Token Factory planner: routing, transport, parsing, provider selection.

No network: httpx.MockTransport stands in for Token Factory.
"""
from __future__ import annotations

import asyncio
import json
from typing import List

import httpx
import pytest

from app.config import settings
from app.services import nemotron_planner as np_mod
from app.services.gemini_planner import GeminiPlanner
from app.services.llm_factory import get_planner
from app.services.nemotron_planner import NemotronPlanner, strip_reasoning, usage_log

FAST = ["nvidia/fast-a", "nvidia/fast-b"]
ULTRA = "nvidia/ultra"


@pytest.fixture
def nemotron_settings(monkeypatch):
    monkeypatch.setattr(settings, "nebius_api_key", "test-key")
    monkeypatch.setattr(settings, "nemotron_enabled", True)
    monkeypatch.setattr(settings, "nemotron_fast_models", ",".join(FAST))
    monkeypatch.setattr(settings, "nemotron_reasoning_model", ULTRA)
    usage_log.clear()
    yield
    usage_log.clear()


def _install_transport(monkeypatch, handler) -> List[dict]:
    """Route the planner's HTTP client through `handler`; return captured request bodies."""
    seen: List[dict] = []

    def _wrapped(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append({"body": body, "auth": request.headers.get("authorization"), "url": str(request.url)})
        return handler(body)

    client = httpx.AsyncClient(transport=httpx.MockTransport(_wrapped))
    monkeypatch.setattr(np_mod, "_client", client)
    return seen


def _completion(content: str, prompt_tokens: int = 100, completion_tokens: int = 20) -> httpx.Response:
    return httpx.Response(200, json={
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    })


PLAN_JSON = json.dumps({"waypoints": [{"x": 5, "y": 5, "max_speed": 0.5}, {"x": 12, "y": 8, "max_speed": 0.4}],
                        "rationale": "avoid worker", "estimated_time_s": 20})
MOVE_JSON = json.dumps({"intent": "MOVE_TO", "params": {"x": 3, "y": 4, "max_speed": 0.4}, "rationale": "step"})

TELEMETRY = {"x": 1.0, "y": 1.0, "zone": "aisle", "human_detected": False}
GOAL = {"x": 12.0, "y": 8.0}


# -- provider selection --------------------------------------------------------

def test_factory_prefers_nemotron_when_key_set(nemotron_settings):
    assert isinstance(get_planner(), NemotronPlanner)
    assert settings.planner_provider == "nemotron"
    assert settings.planner_configured


def test_factory_falls_back_without_key(monkeypatch):
    monkeypatch.setattr(settings, "nebius_api_key", None)
    planner = get_planner()
    assert type(planner) is GeminiPlanner
    assert settings.planner_provider in ("gemini", "fallback")


# -- tier routing --------------------------------------------------------------

def test_generate_plan_uses_reasoning_model_first(nemotron_settings, monkeypatch):
    seen = _install_transport(monkeypatch, lambda body: _completion(PLAN_JSON))
    plan = asyncio.run(NemotronPlanner().generate_plan(TELEMETRY, "go to B-03", GOAL))

    assert [s["body"]["model"] for s in seen] == [ULTRA]  # Ultra alone, no race
    assert plan["model_used"] == ULTRA
    assert plan["tier"] == "reasoning"
    assert len(plan["waypoints"]) == 2
    assert seen[0]["auth"] == "Bearer test-key"
    assert seen[0]["url"].endswith("/chat/completions")


def test_generate_plan_falls_back_to_fast_when_ultra_fails(nemotron_settings, monkeypatch):
    def handler(body):
        if body["model"] == ULTRA:
            return httpx.Response(503, text="overloaded")
        return _completion(PLAN_JSON)

    seen = _install_transport(monkeypatch, handler)
    plan = asyncio.run(NemotronPlanner().generate_plan(TELEMETRY, "go to B-03", GOAL))

    assert [s["body"]["model"] for s in seen] == [ULTRA, FAST[0]]  # sequential, Ultra first
    assert plan["model_used"] == FAST[0]


def test_propose_uses_fast_tier_only(nemotron_settings, monkeypatch):
    seen = _install_transport(monkeypatch, lambda body: _completion(MOVE_JSON))
    proposal = asyncio.run(NemotronPlanner().propose(TELEMETRY, GOAL, "go to B-03"))

    models = {s["body"]["model"] for s in seen}
    assert ULTRA not in models
    assert models <= set(FAST)
    assert proposal.intent == "MOVE_TO"
    assert proposal.params["max_speed"] == 0.4


def test_tier_resets_after_planning(nemotron_settings, monkeypatch):
    _install_transport(monkeypatch, lambda body: _completion(PLAN_JSON))
    planner = NemotronPlanner()
    asyncio.run(planner.generate_plan(TELEMETRY, "go", GOAL))
    assert planner.current_tier == "fast"
    assert ULTRA not in planner._get_cascade(fast=True)


# -- parsing and failure handling ----------------------------------------------

def test_strip_reasoning_removes_think_blocks_with_braces():
    raw = '<think>maybe {"x": 99}? no.</think>\n{"intent": "STOP", "params": {}, "rationale": "done"}'
    assert strip_reasoning(raw).startswith('{"intent": "STOP"')


def test_strip_reasoning_handles_truncated_think():
    assert strip_reasoning("<think>still reasoning {") == ""


def test_think_block_does_not_break_proposal(nemotron_settings, monkeypatch):
    content = '<think>consider {"x": 0, "y": 0}</think>' + MOVE_JSON
    _install_transport(monkeypatch, lambda body: _completion(content))
    proposal = asyncio.run(NemotronPlanner().propose(TELEMETRY, GOAL, "go"))
    assert proposal.params["x"] == 3.0


def test_all_models_failing_returns_deterministic_fallback(nemotron_settings, monkeypatch):
    _install_transport(monkeypatch, lambda body: httpx.Response(500, text="down"))
    plan = asyncio.run(NemotronPlanner().generate_plan(TELEMETRY, "go", GOAL))
    assert plan["model_used"] == "deterministic_fallback"
    assert plan["waypoints"][-1]["x"] == GOAL["x"]


def test_waypoints_are_clamped_to_geofence(nemotron_settings, monkeypatch):
    wild = json.dumps({"waypoints": [{"x": 9999, "y": -50, "max_speed": 7}], "rationale": "x"})
    _install_transport(monkeypatch, lambda body: _completion(wild))
    plan = asyncio.run(NemotronPlanner().generate_plan(TELEMETRY, "go", None))
    wp = plan["waypoints"][0]
    from app.world_model import GEOFENCE
    assert GEOFENCE["min_x"] <= wp["x"] <= GEOFENCE["max_x"]
    assert GEOFENCE["min_y"] <= wp["y"] <= GEOFENCE["max_y"]
    assert wp["max_speed"] <= 1.0


# -- usage metrics -------------------------------------------------------------

def test_usage_log_records_tier_latency_and_tokens(nemotron_settings, monkeypatch):
    _install_transport(monkeypatch, lambda body: _completion(PLAN_JSON, 321, 45))
    asyncio.run(NemotronPlanner().generate_plan(TELEMETRY, "go", GOAL))

    summary = usage_log.summary()
    assert summary["total_calls"] == 1
    row = summary["by_model"][0]
    assert row["tier"] == "reasoning" and row["model"] == ULTRA
    assert row["ok"] == 1
    assert row["prompt_tokens"] == 321 and row["completion_tokens"] == 45
    assert row["p50_latency_ms"] is not None


def test_usage_endpoint(nemotron_settings, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    _install_transport(monkeypatch, lambda body: _completion(PLAN_JSON))
    asyncio.run(NemotronPlanner().generate_plan(TELEMETRY, "go", GOAL))
    with TestClient(app) as client:
        r = client.get("/llm/usage")
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "nemotron"
    assert body["summary"]["total_calls"] >= 1
