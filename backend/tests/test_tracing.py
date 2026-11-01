"""LangSmith tracing: off without a key; one trace per mission with model calls, gate
decisions and permits nested under it; a LangSmith failure never affects a mission."""
from __future__ import annotations

import pytest

from app.config import settings
from app.observability import tracing


class FakeRun:
    """Stands in for langsmith.run_trees.RunTree; records the tree instead of sending it."""
    roots: list = []
    fail = False

    def __init__(self, name, run_type, inputs, metadata=None, parent=None):
        self.name, self.run_type, self.inputs, self.metadata = name, run_type, inputs, metadata or {}
        self.children, self.outputs, self.error, self.posted, self.patched = [], None, None, False, False

    def create_child(self, name, run_type="chain", inputs=None, extra=None, **_):
        child = FakeRun(name, run_type, inputs or {}, (extra or {}).get("metadata"))
        self.children.append(child)
        return child

    def post(self):
        if FakeRun.fail:
            raise ConnectionError("LangSmith is down")
        self.posted = True

    def end(self, outputs=None, error=None, **_):
        self.outputs, self.error = outputs, error

    def patch(self):
        if FakeRun.fail:
            raise ConnectionError("LangSmith is down")
        self.patched = True


@pytest.fixture
def traced(monkeypatch):
    FakeRun.roots, FakeRun.fail = [], False
    monkeypatch.setattr(settings, "langsmith_api_key", "lsv2_test")

    def root(name, run_type, inputs, **meta):
        r = FakeRun(name, run_type, inputs, meta)
        FakeRun.roots.append(r)
        return r

    monkeypatch.setattr(tracing, "_root", root)
    monkeypatch.setattr(tracing, "_missions", {})
    return FakeRun


def test_off_without_a_key(monkeypatch):
    monkeypatch.setattr(settings, "langsmith_api_key", None)
    called = []
    monkeypatch.setattr(tracing, "_root", lambda *a, **k: called.append(1))
    tracing.mission_start("r", "m", "t", {})
    tracing.llm_call(model="m", provider="p", tier="t", prompt="x")
    tracing.event("kill_switch", {}, {})
    assert called == [] and not tracing.enabled()


def test_one_trace_per_mission(traced):
    tracing.mission_start("run-1", "mis-1", "Deliver to B-03", {"x": 12.5, "y": 13.5})
    with tracing.within_mission("run-1"):
        tracing.llm_call(model="muse-spark-1.3", provider="meta", tier="reasoning", prompt="plan…", output="{}",
                         with_image=True)
    tracing.llm_call(model="sam-3.1", provider="meta", tier="vision", prompt="orange circle")   # outside: own trace
    tracing.mission_event("run-1", "gate", inputs={"proposal": {}}, outputs={"decision": "APPROVED"})
    tracing.mission_event("run-1", "permit", inputs={}, outputs={"permit": "used"})
    tracing.mission_end("run-1", "completed")

    mission = next(r for r in traced.roots if r.name == "mission")
    assert mission.posted and mission.patched and mission.outputs == {"status": "completed"}
    assert [(c.name, c.run_type) for c in mission.children] == [
        ("muse-spark-1.3", "llm"), ("gate", "tool"), ("permit", "tool")]
    llm = mission.children[0]
    assert llm.inputs["camera_image_attached"] is True and "data:image" not in str(llm.inputs)
    assert llm.metadata["ls_model_name"] == "muse-spark-1.3"
    assert any(r.name == "sam-3.1" for r in traced.roots)
    assert tracing._missions == {}


def test_langsmith_outage_never_breaks_a_mission(traced):
    traced.fail = True
    tracing.mission_start("run-2", "mis-2", "x", {})       # post raises inside: swallowed
    tracing.mission_event("run-2", "gate", outputs={})
    tracing.llm_call(model="m", provider="p", tier="t")
    tracing.event("kill_switch", {}, {})
    tracing.mission_end("run-2", "stopped")


def test_run_loop_is_traced_end_to_end(traced, monkeypatch):
    """The real run loop with tracing on: the mission trace holds gate decisions and permits."""
    from test_execution_authority import test_run_loop_sends_only_permitted_moves
    test_run_loop_sends_only_permitted_moves(monkeypatch)
    mission = next(r for r in traced.roots if r.name == "mission")
    names = [c.name for c in mission.children]
    assert "gate" in names and names.count("permit") >= 3
    assert mission.patched and mission.outputs["status"] in ("stopped", "completed")
    assert all(c.outputs.get("permit") == "used" for c in mission.children if c.name == "permit")


# --- OpenTelemetry -------------------------------------------------------------------------------

@pytest.fixture
def otel(monkeypatch):
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    monkeypatch.setattr(settings, "langsmith_api_key", None)    # OpenTelemetry on its own
    exporter = InMemorySpanExporter()
    tracing.configure_otel(exporter)
    yield exporter
    tracing.disable_otel()


def test_otel_mission_spans_nest_under_the_mission(otel):
    tracing.mission_start("run-o", "mis-o", "Deliver to B-03", {"x": 12.5, "y": 13.5})
    with tracing.within_mission("run-o"):
        tracing.llm_call(model="muse-spark-1.3", provider="meta", tier="reasoning", prompt="secret plan text",
                         output="{}", with_image=True)
    tracing.mission_event("run-o", "gate", inputs={"proposal": {"intent": "MOVE_TO"}}, outputs={"decision": "APPROVED"})
    tracing.mission_event("run-o", "permit", outputs={"permit": "refused", "reason": "kill_switch_active"},
                          error="kill_switch_active")
    tracing.mission_end("run-o", "stopped")
    spans = {s.name: s for s in otel.get_finished_spans()}
    mission = spans["mission"]
    assert mission.attributes["mission.status"] == "stopped" and mission.attributes["run.id"] == "run-o"
    for name in ("model muse-spark-1.3", "gate", "permit"):
        assert spans[name].parent.span_id == mission.context.span_id
        assert spans[name].context.trace_id == mission.context.trace_id
    model = spans["model muse-spark-1.3"]
    assert model.attributes["gen_ai.request.model"] == "muse-spark-1.3" and model.attributes["model.camera_image_attached"]
    assert "secret plan text" not in str(dict(model.attributes))      # prompts stay out of OpenTelemetry
    assert spans["gate"].attributes["out.decision"] == "APPROVED"
    assert not spans["permit"].status.is_ok


def test_otel_standalone_events(otel):
    tracing.event("kill_switch", {"scope": "global"}, {"stop_verified": True, "authority_revoked_ms": 3.2})
    span = otel.get_finished_spans()[0]
    assert span.name == "kill_switch" and span.parent is None and span.attributes["out.stop_verified"] is True


def test_otel_run_loop_end_to_end(otel, monkeypatch):
    from test_execution_authority import test_run_loop_sends_only_permitted_moves
    test_run_loop_sends_only_permitted_moves(monkeypatch)
    spans = otel.get_finished_spans()
    mission = next(s for s in spans if s.name == "mission")
    children = [s for s in spans if s.parent is not None and s.parent.span_id == mission.context.span_id]
    names = [s.name for s in children]
    assert "gate" in names and names.count("permit") >= 3
