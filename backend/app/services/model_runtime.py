"""Shared plumbing for model calls: the HTTP client, the usage log, planner tiers.

Used by the Meta model transport (Muse Spark, Muse Spark Open, SAM 3.1, voice),
the planner, and the /llm/usage and /metrics views.
"""
from __future__ import annotations

import asyncio
import contextvars
import re
import time as _time
from collections import deque
from contextlib import contextmanager
from typing import Any, Deque, Dict, Iterator, List, Optional, Tuple

import httpx

TIER_FAST = "fast"
TIER_REASONING = "reasoning"

_tier: contextvars.ContextVar[str] = contextvars.ContextVar("planner_tier", default=TIER_FAST)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def strip_reasoning(text: str) -> str:
    """Remove <think>…</think> blocks so braces inside reasoning can't break JSON extraction."""
    cleaned = _THINK_RE.sub("", text or "")
    # An unclosed <think> means the model was cut off mid-reasoning; keep what follows it, if anything.
    if "<think>" in cleaned.lower():
        idx = cleaned.lower().rfind("</think>")
        cleaned = cleaned[idx + len("</think>"):] if idx != -1 else ""
    return cleaned.strip()


@contextmanager
def reasoning_tier() -> Iterator[None]:
    token = _tier.set(TIER_REASONING)
    try:
        yield
    finally:
        _tier.reset(token)


# ---------------------------------------------------------------------------
# Usage metrics: feeds the "latency and cost per decision" view and /metrics
# ---------------------------------------------------------------------------

class UsageLog:
    """Bounded in-memory log of model calls (process-local)."""

    def __init__(self, maxlen: int = 2000):
        self._calls: Deque[Dict[str, Any]] = deque(maxlen=maxlen)

    def record(self, **call: Any) -> None:
        call.setdefault("ts", _time.time())
        self._calls.append(call)

    def recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        return list(self._calls)[-limit:]

    def summary(self) -> Dict[str, Any]:
        by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for c in self._calls:
            key = (c.get("tier", "?"), c.get("model", "?"))
            s = by_key.setdefault(key, {
                "tier": key[0], "model": key[1], "calls": 0, "ok": 0,
                "latency_ms": [], "prompt_tokens": 0, "completion_tokens": 0,
            })
            s["calls"] += 1
            if c.get("ok"):
                s["ok"] += 1
                s["latency_ms"].append(c.get("latency_ms", 0))
            s["prompt_tokens"] += int(c.get("prompt_tokens") or 0)
            s["completion_tokens"] += int(c.get("completion_tokens") or 0)

        rows = []
        for s in by_key.values():
            lat = sorted(s.pop("latency_ms"))
            s["p50_latency_ms"] = lat[len(lat) // 2] if lat else None
            s["p95_latency_ms"] = lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else None
            rows.append(s)
        rows.sort(key=lambda r: (r["tier"], r["model"]))
        return {"total_calls": len(self._calls), "by_model": rows}

    def clear(self) -> None:
        self._calls.clear()


usage_log = UsageLog()


# ---------------------------------------------------------------------------
# Shared HTTP client
# ---------------------------------------------------------------------------

_client: Optional[httpx.AsyncClient] = None
_own_client: Optional[httpx.AsyncClient] = None       # the client this module created
_own_client_loop: Optional[asyncio.AbstractEventLoop] = None


def _get_client() -> httpx.AsyncClient:
    """Shared client. An AsyncClient is bound to the event loop it first ran on;
    callers that use asyncio.run() per call (the benchmark, scripts) get a fresh
    loop each time, and reusing a client whose loop has closed fails with
    "Event loop is closed". So a client this module created is replaced once its
    loop is closed. A client set from outside (tests) is left alone."""
    global _client, _own_client, _own_client_loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    stale = (_client is not None and _client is _own_client and _own_client_loop is not None
             and _own_client_loop is not loop and _own_client_loop.is_closed())
    if _client is None or _client.is_closed or stale:
        _client = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        _own_client, _own_client_loop = _client, loop
    elif _client is _own_client and _own_client_loop is None:
        _own_client_loop = loop
    return _client
