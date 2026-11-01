"""LangSmith tracing: one trace per mission, linking what the models said to what
the robot was allowed to do.

    mission (chain)
      ├─ muse-spark-1.3 (llm)        planning call, prompt and answer
      ├─ plan (chain)                source, model, waypoints, canary result
      ├─ gate (tool)                 each decision: verdict, policy hits
      ├─ permit (tool)               permit issued and used, or refused and why
      └─ canary (tool)               if the planner obeyed a hidden instruction

Kill switches and security drills are traced on their own.

On only when LANGSMITH_API_KEY is set. Tracing never blocks or changes a safety
decision: every call here swallows its own errors. Camera images are never sent
(only a flag that one was attached), and neither are keys.
"""
from __future__ import annotations

import contextvars
import logging
import threading
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

from app.config import settings

logger = logging.getLogger("app.tracing")

_client = None
_lock = threading.Lock()
_missions: Dict[str, Any] = {}      # run_id -> root RunTree
_parent: contextvars.ContextVar[Optional[Any]] = contextvars.ContextVar("trace_parent", default=None)
MAX_TEXT = 20000


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


def _safe(fn):
    def wrapper(*a, **kw):
        if not enabled():
            return None
        try:
            return fn(*a, **kw)
        except Exception as exc:   # tracing must never affect the robot
            logger.debug("LangSmith tracing skipped: %s", exc)
            return None
    return wrapper


# --- missions ------------------------------------------------------------------------------------

@_safe
def mission_start(run_id: str, mission_id: str, title: str, goal: Dict[str, Any]) -> None:
    root = _root("mission", "chain", {"title": title, "goal": goal}, run_id=run_id, mission_id=mission_id)
    root.post()
    with _lock:
        _missions[run_id] = root


@_safe
def mission_event(run_id: str, name: str, *, run_type: str = "tool", inputs: Optional[Dict[str, Any]] = None,
                  outputs: Optional[Dict[str, Any]] = None, error: Optional[str] = None, **meta: Any) -> None:
    with _lock:
        root = _missions.get(run_id)
    if root is None:
        return
    child = root.create_child(name=name, run_type=run_type, inputs=inputs or {}, extra={"metadata": meta})
    child.end(outputs=outputs or {}, error=error)
    child.post()


@_safe
def mission_end(run_id: str, status: str) -> None:
    with _lock:
        root = _missions.pop(run_id, None)
    if root is not None:
        root.end(outputs={"status": status})
        root.patch()


@contextmanager
def within_mission(run_id: str) -> Iterator[None]:
    """Model calls made inside this block are traced under the mission."""
    with _lock:
        root = _missions.get(run_id)
    token = _parent.set(root)
    try:
        yield
    finally:
        _parent.reset(token)


# --- model calls -----------------------------------------------------------------------------------

@_safe
def llm_call(*, model: str, provider: str, tier: str, system: str = "", prompt: str = "",
             output: Optional[str] = None, with_image: bool = False, error: Optional[str] = None,
             **meta: Any) -> None:
    inputs = {"messages": [{"role": "system", "content": _clip(system)}, {"role": "user", "content": _clip(prompt)}],
              "camera_image_attached": with_image}
    outputs = {"content": _clip(output or "")}
    metadata = {"ls_model_name": model, "ls_provider": provider, "tier": tier, **meta}
    parent = _parent.get()
    if parent is not None:
        run = parent.create_child(name=model, run_type="llm", inputs=inputs, extra={"metadata": metadata})
    else:
        run = _root(model, "llm", inputs, **metadata)
    run.end(outputs=outputs, error=error)
    run.post()


# --- system events ------------------------------------------------------------------------------

@_safe
def event(name: str, inputs: Dict[str, Any], outputs: Dict[str, Any], **meta: Any) -> None:
    """A standalone trace: kill switches, resets, security drills."""
    run = _root(name, "tool", inputs, **meta)
    run.end(outputs=outputs)
    run.post()


def flush() -> None:
    if _client is not None:
        try:
            _client.flush()
        except Exception:
            pass
