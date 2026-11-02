"""Meta models, against a fake Meta Model API / Baseten that checks every request
has the documented shape (dev.meta.ai/docs): Muse Spark planning with the camera
frame, Muse Spark Open step proposals, SAM 3.1 detections projected onto the floor,
and the voice stop."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.config import settings

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


class FakeMeta:
    """Records requests; answers like the Meta Model API and Baseten."""

    def __init__(self, *, chat_text=None, sam=None, transcript="", fail=False):
        self.requests = []
        self.chat_text = chat_text
        self.sam = sam or {}
        self.transcript = transcript
        self.fail = fail

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = request.content
        self.requests.append(request)
        if self.fail:
            return httpx.Response(503, json={"error": {"message": "overloaded", "type": "server_error"}})
        assert request.headers["authorization"].startswith("Bearer ")
        if request.url.path.endswith("/chat/completions"):
            data = json.loads(body)
            text = self.chat_text(data) if callable(self.chat_text) else self.chat_text
            return httpx.Response(200, json={"id": "chatcmpl-1", "object": "chat.completion", "model": data["model"],
                                             "choices": [{"index": 0, "finish_reason": "stop",
                                                          "message": {"role": "assistant", "content": text}}],
                                             "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
        if request.url.path.endswith("/responses"):
            data = json.loads(body)
            assert data["model"] == "sam-3.1" and data["stream"] is True
            parts = data["input"][0]["content"]
            concept = next(p["text"] for p in parts if p["type"] == "input_text")
            assert next(p for p in parts if p["type"] == "input_image")["image_url"].startswith("data:image/png;base64,")
            line = self.sam.get(concept, "")
            events = []
            if line:
                events.append({"type": "response.output_text.delta", "delta": line})
            events.append({"type": "response.completed"})
            sse = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=sse)
        if request.url.path.endswith("/asr/transcribe"):
            assert b'"model": "muse-voice-transcribe-1.0"' in body and b'name="audio"' in body
            return httpx.Response(200, json={"sessionId": "s1", "transcript": self.transcript, "turns": []})
        return httpx.Response(404)


@pytest.fixture
def meta(monkeypatch):
    """Turn on Meta (and Baseten) with fake keys and route HTTP to a FakeMeta."""
    import app.services.model_runtime as np_mod
    monkeypatch.setattr(settings, "model_api_key", "LLM_test_key")
    monkeypatch.setattr(settings, "baseten_api_key", None)
    fakes = {}

    def install(fake: FakeMeta):
        fakes["fake"] = fake
        monkeypatch.setattr(np_mod, "_client", httpx.AsyncClient(transport=httpx.MockTransport(fake)))
        return fake

    yield install


# --- planning ---------------------------------------------------------------------------------

def test_factory_prefers_muse(meta):
    from app.services.llm_factory import get_planner
    from app.services.muse_planner import MusePlanner
    planner = get_planner()
    assert isinstance(planner, MusePlanner) and settings.planner_provider == "muse"
    assert planner.reasoning_model == "muse-spark-1.3"


def test_muse_spark_plans_with_the_camera_frame(meta, monkeypatch):
    from app.services.muse_planner import MusePlanner
    fake = meta(FakeMeta(chat_text='{"waypoints": [{"x": 8, "y": 3.5, "max_speed": 0.4}, {"x": 12.5, "y": 13.5, '
                                   '"max_speed": 0.3}], "rationale": "aisle A then cross-aisle", "estimated_time_s": 40}'))
    planner = MusePlanner()

    async def frame():
        return PNG
    monkeypatch.setattr(planner, "_camera_frame", frame)
    plan = asyncio.run(planner.generate_plan({"x": 3, "y": 3.5}, "Deliver to B-03", {"x": 12.5, "y": 13.5}))

    body = json.loads(fake.requests[0].content)
    assert fake.requests[0].url.host == "api.meta.ai"
    assert body["model"] == "muse-spark-1.3" and body["reasoning_effort"] == "high"
    assert "max_completion_tokens" in body and "max_tokens" not in body
    user = body["messages"][1]["content"]
    assert user[1]["type"] == "image_url" and user[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert plan["model_used"] == "muse-spark-1.3" and plan["camera_used"] is True and plan["tier"] == "reasoning"
    assert plan["waypoints"][-1]["x"] == pytest.approx(12.5)


def test_muse_spark_open_on_baseten_proposes_steps(meta, monkeypatch):
    from app.services.muse_planner import MusePlanner
    monkeypatch.setattr(settings, "baseten_api_key", "bt_test")
    fake = meta(FakeMeta(chat_text=lambda d: '{"intent": "MOVE_TO", "params": {"x": 6, "y": 3.5, "max_speed": 0.4}, '
                                             f'"rationale": "{d["model"]}"}}'))
    planner = MusePlanner()
    assert planner.fast_models[0] == "meta-models/muse-spark-open-1026"
    proposal = asyncio.run(planner.propose({"x": 3, "y": 3.5}, {"x": 12.5, "y": 13.5}, "Deliver"))
    hosts = {r.url.host for r in fake.requests}
    assert "inference.baseten.co" in hosts
    baseten_body = json.loads(next(r for r in fake.requests if r.url.host == "inference.baseten.co").content)
    assert baseten_body["model"] == "meta-models/muse-spark-open-1026" and "reasoning_effort" not in baseten_body
    assert "image_url" not in json.dumps(baseten_body)    # steps are text-only
    assert proposal.intent == "MOVE_TO" and proposal.params["x"] == 6


def test_model_outage_falls_back_to_labelled_deterministic_plan(meta, monkeypatch):
    from app.services.muse_planner import MusePlanner
    meta(FakeMeta(fail=True))
    planner = MusePlanner()

    async def frame():
        return None
    monkeypatch.setattr(planner, "_camera_frame", frame)
    plan = asyncio.run(planner.generate_plan({"x": 3, "y": 3.5}, "Deliver", {"x": 12.5, "y": 13.5}))
    assert plan["model_used"] == "deterministic_fallback" and plan["camera_used"] is False


# --- SAM 3.1 ----------------------------------------------------------------------------------------

DOC_EXAMPLE = ("<0f>0<|box;x1=353;y1=382;x2=453;y2=427;w=537;h=561|><|mask;x=0;y=0;data=46,101,~abc|>,"
               "1<|box;x1=260;y1=382;x2=340;y2=427;w=537;h=561;c=0.91|><|mask;x=0;y=0;data=46,81,~def|>")


def test_sam_box_parser_matches_the_documented_format():
    from app.services.meta_models import parse_sam_boxes
    boxes = parse_sam_boxes(DOC_EXAMPLE)
    assert len(boxes) == 2
    assert boxes[0] == {"x1": 353, "y1": 382, "x2": 453, "y2": 427, "w": 537, "h": 561}
    assert boxes[1]["c"] == pytest.approx(0.91)
    assert parse_sam_boxes("") == []


def test_sam_detection_becomes_a_floor_position_that_matches_the_sensors(meta):
    from app.services.perception import FRAME_SIZE, Perception, world_to_robot, ROBOT_ROW, VIEW_M

    # A person 3 m ahead of the robot and 1 m to its right; work out where the camera shows them
    tel = {"x": 5.0, "y": 3.5, "theta": 0.0, "walking_humans": [{"x": 8.0, "y": 2.5}], "obstacles": []}
    ahead, right = world_to_robot(tel, 8.0, 2.5)
    scale = FRAME_SIZE / VIEW_M
    px, py = FRAME_SIZE / 2 + right * scale, FRAME_SIZE * ROBOT_ROW - ahead * scale
    box = f"<0f>0<|box;x1={px - 6:.0f};y1={py - 6:.0f};x2={px + 6:.0f};y2={py + 6:.0f};w={FRAME_SIZE};h={FRAME_SIZE}|>"
    fake = meta(FakeMeta(sam={settings.sam_concept_map["person"]: box}))

    class Sim:
        async def get_frame(self, size=512):
            return PNG

    result = asyncio.run(Perception().check(Sim(), tel))
    assert len([r for r in fake.requests if r.url.path.endswith("/responses")]) == 4   # one per object type
    assert result["model"] == "sam-3.1" and result["verdict"] == "agree"
    assert result["matched"][0]["type"] == "person" and result["matched"][0]["error_m"] < 0.5


def test_sam_sighting_the_sensors_do_not_confirm_only_adds_caution(meta):
    from app.services.perception import FRAME_SIZE, Perception
    box = f"<0f>0<|box;x1=250;y1=150;x2=262;y2=162;w={FRAME_SIZE};h={FRAME_SIZE}|>"
    meta(FakeMeta(sam={settings.sam_concept_map["spill"]: box}))

    class Sim:
        async def get_frame(self, size=512):
            return PNG

    p = Perception()
    result = asyncio.run(p.check(Sim(), {"x": 5.0, "y": 3.5, "theta": 0.0, "walking_humans": [], "obstacles": []}))
    assert result["verdict"] == "unconfirmed_sighting"
    zones = p.caution_zones()
    assert zones and zones[0]["radius"] == 0.0 and zones[0]["max_speed"] <= 0.3   # slow only, never exclusion


# --- voice stop -----------------------------------------------------------------------------------------

def test_voice_intent_only_ever_stops():
    from app.api.routes_authority import voice_intent
    assert voice_intent("Stop the robot now", "robot-1") == {"scope": "robot", "id": "robot-1"}
    assert voice_intent("emergency, stop everything", "robot-1") == {"scope": "global", "id": "*"}
    assert voice_intent("start moving again", "robot-1") is None
    assert voice_intent("resume the mission", "robot-1") is None
    assert voice_intent("call the nonstop team", "robot-1") is None
    assert voice_intent("", "robot-1") is None


def test_voice_endpoint_fires_a_kill_switch(meta, monkeypatch, tmp_path):
    import os
    from fastapi.testclient import TestClient
    import app.services.execution_authority as ea
    import app.api.routes_runs as rr
    from app.main import app

    class StopSim:
        async def estop(self, **kw):
            return {"ok": True, "engaged": kw.get("engaged")}

        async def send_command(self, cmd):
            return {"ok": True}

        async def get_telemetry(self):
            return {"speed": 0.0, "target": None}

    monkeypatch.setattr(ea, "_authority", ea.ExecutionAuthority(secret=os.environ["PERMIT_SECRET"],
                                                                db_path=str(tmp_path / "v.db")))
    monkeypatch.setattr(rr.get_run_svc(), "sim", StopSim())
    client = TestClient(app)

    meta(FakeMeta(transcript="please resume and go faster"))
    r = client.post("/authority/voice", files={"audio": ("a.wav", b"RIFF0000WAVE", "audio/wav")})
    assert r.status_code == 200 and r.json()["action"] == "none"
    assert ea._authority.kill_locks() == []

    meta(FakeMeta(transcript="Stop the robot!"))
    r = client.post("/authority/voice", files={"audio": ("a.wav", b"RIFF0000WAVE", "audio/wav")})
    body = r.json()
    assert r.status_code == 200 and body["action"] == "kill" and body["scope"] == "robot" and body["stop_verified"]
    assert ea._authority.kill_locks()[0]["reason"].startswith("voice:")
