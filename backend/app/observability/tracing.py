"""Mission tracing to LangSmith and OpenTelemetry: one trace per mission, linking
what the models said to what the robot was allowed to do.

    mission
      ├─ muse-spark-1.3 (llm)        planning call (LangSmith: prompt and answer)
      ├─ plan                        source, model, waypoints, canary result
      ├─ gate                        each decision: verdict, policy hits
      ├─ permit                      permit used, or refused and why
      └─ canary                      if the planner obeyed a hidden instruction

Kill switches, resets and security drills are traced on their own.

Two independent sinks, each on only when configured:
  LangSmith      LANGSMITH_API_KEY            (full model prompts and answers)
  OpenTelemetry  OTEL_EXPORTER_OTLP_ENDPOINT  (spans with attributes; prompt sizes only)

Tracing never blocks or changes a safety decision: every call swallows its own
errors. Camera images and keys are never sent.
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import threading
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional, Tuple

from app.config import settings

logger = logging.getLogger("app.tracing")

_client = None
_lock = threading.Lock()
_missions: Dict[str, Any] = {}        # run_id -> LangSmith root RunTree
_otel_missions: Dict[str, Any] = {}   # run_id -> OpenTelemetry root span
_parent: contextvars.ContextVar[Tuple[Optional[Any], Optional[Any]]] = contextvars.ContextVar(
    "trace_parent", default=(None, None))
MAX_TEXT = 20000


# =============================================================================== LangSmith

def enabled() -> bool:
    return bool(settings.langsmith_api_key) and settings.langsmith_tracing


def _get_client():
    global _client
    if _client is None:
        from langsmith import Client
        _client = Client(api_key=settings.langsmith_api_key, api_url=settings.langsmith_endpoint)
    return _client


def _root(name: str, run_type: str, inputs: Dict[str, Any], **meta: Any):
    from langsmith.run_trees import RunTree
    return RunTree(name=name, run_type=run_type, inputs=inputs, project_name=settings.langsmith_project,
                   client=_get_client(), tags=["sovereign-autonomy"], extra={"metadata": meta})


def _clip(v: Any) -> Any:
    if isinstance(v, str) and len(v) > MAX_TEXT:
        return v[:MAX_TEXT] + f"… [{len(v) - MAX_TEXT} more characters]"
    return v


def _quiet(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception as exc:   # tracing must never affect the robot
        logger.debug("Tracing skipped: %s", exc)
        return None


# =========================================================================== OpenTelemetry

_otel_tracer = None
_otel_checked = False


def otel_endpoint() -> Optional[str]:
    return os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or settings.otel_exporter_endpoint


def configure_otel(exporter=None) -> None:
    """Set up the tracer. `exporter` overrides the OTLP/HTTP exporter (tests)."""
    global _otel_tracer, _otel_checked
    _otel_checked = True
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
    provider = TracerProvider(resource=Resource.create({"service.name": settings.otel_service_name}))
    if exporter is None:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        ep = otel_endpoint().rstrip("/")
        exporter = OTLPSpanExporter(endpoint=ep if ep.endswith("/v1/traces") else f"{ep}/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))
    else:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    _otel_tracer = provider.get_tracer("sovereign-autonomy")


def disable_otel() -> None:
    global _otel_tracer, _otel_checked
    _otel_tracer, _otel_checked = None, True
    _otel_missions.clear()


def _tracer():
    if not _otel_checked and otel_endpoint():
        _quiet(configure_otel)
    return _otel_tracer


def _attrs(prefix: str, data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in (data or {}).items():
        if v is None:
            continue
        key = f"{prefix}.{k}"
        if isinstance(v, (bool, int, float, str)):
            out[key] = v if not isinstance(v, str) else v[:500]
        else:
            out[key] = json.dumps(v, default=str)[:500]
    return out


def _otel_span(name: str, parent=None, attributes: Optional[Dict[str, Any]] = None):
    from opentelemetry import trace
    ctx = trace.set_span_in_context(parent) if parent is not None else None
    return _tracer().start_span(name, context=ctx, attributes=attributes or {})


def _otel_error(span, error: Optional[str]) -> None:
    if error:
        from opentelemetry.trace import Status, StatusCode
        span.set_status(Status(StatusCode.ERROR, error[:200]))


# ================================================================================ missions

def mission_start(run_id: str, mission_id: str, title: str, goal: Dict[str, Any]) -> None:
    if enabled():
        def ls():
            root = _root("mission", "chain", {"title": title, "goal": goal}, run_id=run_id, mission_id=mission_id)
            root.post()
            with _lock:
                _missions[run_id] = root
        _quiet(ls)
    if _tracer():
        def ot():
            span = _otel_span("mission", attributes={"run.id": run_id, "mission.id": mission_id,
                                                      "mission.title": title, **_attrs("mission.goal", goal)})
            with _lock:
                _otel_missions[run_id] = span
        _quiet(ot)


def mission_event(run_id: str, name: str, *, run_type: str = "tool", inputs: Optional[Dict[str, Any]] = None,
                  outputs: Optional[Dict[str, Any]] = None, error: Optional[str] = None, **meta: Any) -> None:
    if enabled():
        def ls():
            with _lock:
                root = _missions.get(run_id)
            if root is None:
                return
            child = root.create_child(name=name, run_type=run_type, inputs=inputs or {}, extra={"metadata": meta})
            child.end(outputs=outputs or {}, error=error)
            child.post()
        _quiet(ls)
    if _tracer():
        def ot():
            with _lock:
                root = _otel_missions.get(run_id)
            if root is None:
                return
            span = _otel_span(name, root, {"run.id": run_id, **_attrs("in", inputs), **_attrs("out", outputs)})
            _otel_error(span, error)
            span.end()
        _quiet(ot)


def mission_end(run_id: str, status: str) -> None:
    if enabled():
        def ls():
            with _lock:
                root = _missions.pop(run_id, None)
            if root is not None:
                root.end(outputs={"status": status})
                root.patch()
        _quiet(ls)
    with _lock:
        span = _otel_missions.pop(run_id, None)
    if span is not None:
        def ot():
            span.set_attribute("mission.status", status)
            span.end()
        _quiet(ot)


@contextmanager
def within_mission(run_id: str) -> Iterator[None]:
    """Model calls made inside this block are traced under the mission."""
    with _lock:
        parents = (_missions.get(run_id), _otel_missions.get(run_id))
    token = _parent.set(parents)
    try:
        yield
    finally:
        _parent.reset(token)


# ============================================================================== model calls

def llm_call(*, model: str, provider: str, tier: str, system: str = "", prompt: str = "",
             output: Optional[str] = None, with_image: bool = False, error: Optional[str] = None,
             **meta: Any) -> None:
    ls_parent, otel_parent = _parent.get()
    if enabled():
        def ls():
            inputs = {"messages": [{"role": "system", "content": _clip(system)}, {"role": "user", "content": _clip(prompt)}],
                      "camera_image_attached": with_image}
            metadata = {"ls_model_name": model, "ls_provider": provider, "tier": tier, **meta}
            if ls_parent is not None:
                run = ls_parent.create_child(name=model, run_type="llm", inputs=inputs, extra={"metadata": metadata})
            else:
                run = _root(model, "llm", inputs, **metadata)
            run.end(outputs={"content": _clip(output or "")}, error=error)
            run.post()
        _quiet(ls)
    if _tracer():
        def ot():
            span = _otel_span(f"model {model}", otel_parent, {
                "gen_ai.system": provider, "gen_ai.request.model": model, "model.tier": tier,
                "model.camera_image_attached": with_image, "model.prompt_chars": len(prompt or ""),
                "model.answer_chars": len(output or ""), **_attrs("model", meta)})
            _otel_error(span, error)
            span.end()
        _quiet(ot)


# ============================================================================ system events

def event(name: str, inputs: Dict[str, Any], outputs: Dict[str, Any], **meta: Any) -> None:
    """A standalone trace: kill switches, resets, security drills."""
    if enabled():
        def ls():
            run = _root(name, "tool", inputs, **meta)
            run.end(outputs=outputs)
            run.post()
        _quiet(ls)
    if _tracer():
        def ot():
            span = _otel_span(name, None, {**_attrs("in", inputs), **_attrs("out", outputs)})
            span.end()
        _quiet(ot)


def flush() -> None:
    if _client is not None:
        _quiet(_client.flush)
