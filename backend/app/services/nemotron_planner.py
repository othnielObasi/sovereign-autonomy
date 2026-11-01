"""NVIDIA Nemotron planner served by Nebius Token Factory.

Drop-in replacement for GeminiPlanner: it inherits every prompt, parser and
deterministic fallback, and swaps only the model transport and routing.

Tiered routing
--------------
* FAST tier (Nemotron Lightning / Super): per-step action proposals, scene
  analysis, telemetry analysis, failure detection. The top two fast models
  are raced concurrently, exactly like the Gemini cascade.
* REASONING tier (Nemotron Ultra): mission planning and replanning after a
  governance denial. Ultra is tried first and alone; fast models are only a
  fallback if Ultra fails or times out. Racing Ultra against a fast model
  would let the fast model win every time and defeat the point of the tier.

The governance gate never depends on this module: the model proposes, the
deterministic policy engine decides.
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import re
import time as _time
from collections import deque
from contextlib import contextmanager
from typing import Any, Deque, Dict, Iterator, List, Optional, Tuple

import httpx

from app.config import settings
from app.services.gemini_planner import GeminiPlanner

logger = logging.getLogger("app.nemotron_planner")

TIER_FAST = "fast"
TIER_REASONING = "reasoning"

_tier: contextvars.ContextVar[str] = contextvars.ContextVar("nemotron_tier", default=TIER_FAST)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

SYSTEM_PROMPT = (
    "You are a planning component inside a governed robotics system. "
    "A deterministic safety policy engine reviews every action you propose and "
    "may deny it. Respond with the STRICT JSON requested and nothing else."
)


def strip_reasoning(text: str) -> str:
    """Remove <think>…</think> blocks so braces inside reasoning can't break JSON extraction."""
    cleaned = _THINK_RE.sub("", text or "")
    # An unclosed <think> means the model was cut off mid-reasoning; keep what follows it, if anything.
    if "<think>" in cleaned.lower():
        idx = cleaned.lower().rfind("</think>")
        cleaned = cleaned[idx + len("</think>"):] if idx != -1 else ""
    return cleaned.strip()


# ---------------------------------------------------------------------------
# Usage metrics — feeds the "latency and cost per decision" panel
# ---------------------------------------------------------------------------

class UsageLog:
    """Bounded in-memory log of model calls (process-local, demo telemetry)."""

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


@contextmanager
def reasoning_tier() -> Iterator[None]:
    token = _tier.set(TIER_REASONING)
    try:
        yield
    finally:
        _tier.reset(token)


# ---------------------------------------------------------------------------
# Planner
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


class NemotronPlanner(GeminiPlanner):
    """GeminiPlanner behaviour, NVIDIA Nemotron models, Nebius Token Factory transport."""

    provider = "nemotron"

    def __init__(self) -> None:
        super().__init__()
        self.api_key = settings.nebius_api_key
        self.base_url = settings.nebius_base_url.rstrip("/")
        self.fast_models: List[str] = settings.nemotron_fast_models_list
        self.reasoning_model: str = settings.nemotron_reasoning_model
        self.primary_model = self.fast_models[0] if self.fast_models else self.reasoning_model
        self.model_cascade = self._dedupe([self.reasoning_model] + self.fast_models)
        self.fast_timeout_s = settings.nemotron_fast_timeout_s
        self.reasoning_timeout_s = settings.nemotron_reasoning_timeout_s

    @staticmethod
    def _dedupe(models: List[str]) -> List[str]:
        seen, out = set(), []
        for m in models:
            if m and m not in seen:
                seen.add(m)
                out.append(m)
        return out

    @property
    def current_tier(self) -> str:
        return _tier.get()

    # -- routing ------------------------------------------------------------

    def _get_cascade(self, preferred_model: Optional[str] = None, fast: bool = False) -> List[str]:
        if _tier.get() == TIER_REASONING:
            base = self._dedupe([self.reasoning_model] + self.fast_models)
        else:
            base = list(self.fast_models) or [self.reasoning_model]
        if preferred_model and preferred_model in self.model_cascade:
            return [preferred_model] + [m for m in base if m != preferred_model]
        return base

    async def _race_models(self, models: List[str], prompt: str) -> tuple[Optional[str], str]:
        if _tier.get() == TIER_REASONING:
            # Sequential: the reasoning model gets its full chance before any fallback.
            for model in models:
                text = await self._call_gemini(model, prompt)
                if text:
                    return text, model
            return None, "none"
        return await super()._race_models(models, prompt)

    # -- transport ----------------------------------------------------------

    async def _call_gemini(self, model: str, prompt: str) -> Optional[str]:
        """Token Factory chat completion. Keeps the parent's method name so every
        inherited code path (propose, plan, analysis, agentic ReAct) routes here."""
        tier = _tier.get()
        timeout = self.reasoning_timeout_s if model == self.reasoning_model else self.fast_timeout_s
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            # Nemotron reasons before answering and the reasoning counts against
            # max_tokens: Ultra was measured using up to ~4000 tokens on a live
            # replan, so a tight cap cuts the JSON off. Keep room for thought + answer.
            "max_tokens": 8192 if model == self.reasoning_model else 2048,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        t0 = _time.monotonic()
        record: Dict[str, Any] = {"model": model, "tier": tier, "ok": False}
        try:
            r = await _get_client().post(
                f"{self.base_url}/chat/completions", headers=headers, json=payload, timeout=timeout,
            )
            record["latency_ms"] = round((_time.monotonic() - t0) * 1000)
            record["status"] = r.status_code
            if r.status_code >= 400:
                logger.warning("Token Factory %s on %s (%sms): %s",
                               r.status_code, model, record["latency_ms"], r.text[:200])
                return None
            data = r.json()
            usage = data.get("usage") or {}
            record["prompt_tokens"] = usage.get("prompt_tokens")
            record["completion_tokens"] = usage.get("completion_tokens")
            choice = (data.get("choices") or [{}])[0]
            if choice.get("finish_reason") == "length":
                record["truncated"] = True
                logger.warning("Output from %s hit max_tokens (%s completion tokens); answer may be cut off",
                               model, usage.get("completion_tokens"))
            content = choice.get("message", {}).get("content") or ""
            text = strip_reasoning(content)
            if not text:
                logger.warning("Empty content from %s (%sms)", model, record["latency_ms"])
                return None
            record["ok"] = True
            logger.info("Nemotron %s [%s] responded in %sms", model, tier, record["latency_ms"])
            return text
        except Exception as e:  # network errors, timeouts, malformed JSON
            record["latency_ms"] = round((_time.monotonic() - t0) * 1000)
            record["error"] = type(e).__name__
            logger.warning("Exception calling %s (%sms): %s", model, record["latency_ms"], e)
            return None
        finally:
            if "latency_ms" not in record:
                # Lost a race and was cancelled before responding.
                record["latency_ms"] = round((_time.monotonic() - t0) * 1000)
                record["cancelled"] = True
            usage_log.record(**record)

    # -- tier assignment ----------------------------------------------------

    async def generate_plan(self, telemetry: Dict[str, Any], instruction: str,
                            goal: Optional[Dict[str, float]] = None,
                            preferred_model: Optional[str] = None,
                            lessons: Optional[List[Dict[str, Any]]] = None,
                            untrusted_context: str = "") -> Dict[str, Any]:
        """Mission planning and replanning run on the reasoning tier (Nemotron Ultra)."""
        with reasoning_tier():
            plan = await super().generate_plan(telemetry, instruction, goal, preferred_model, lessons=lessons,
                                               untrusted_context=untrusted_context)
        plan["tier"] = TIER_REASONING
        return plan
