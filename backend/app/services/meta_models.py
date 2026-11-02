"""Meta Model API and Muse Spark Open (Baseten) transport.

One small HTTP client for every Meta model the system uses:

- Muse Spark (chat completions, with an optional camera image) plans missions.
- Muse Spark Open, Meta's open-weight model served by Baseten, proposes steps.
- SAM 3.1 (Responses API) finds objects in the robot camera frame.
- Muse Voice Transcribe turns operator speech into text.

Request and response shapes follow https://dev.meta.ai/docs. Every call is
logged to the shared usage log (latency, tokens, status). Model output is only
ever a proposal or an observation; the governance gate and the execution
authority decide what the robot does.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings

logger = logging.getLogger("app.meta_models")


def _client():
    from app.services.model_runtime import _get_client   # shared, event-loop-safe client
    return _get_client()


def _log(**record: Any) -> None:
    from app.services.model_runtime import usage_log
    usage_log.record(**record)


def endpoint_for(model: str) -> Tuple[str, str, str]:
    """(base_url, api_key, provider) for a model id."""
    if model == settings.muse_open_model or model.startswith("meta-models/"):
        return settings.baseten_base_url.rstrip("/"), settings.baseten_api_key or "", "baseten"
    return settings.meta_base_url.rstrip("/"), settings.model_api_key or "", "meta"


def png_data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()


async def chat(model: str, system: str, prompt: str, *, image_png: Optional[bytes] = None,
               max_tokens: int = 4096, reasoning_effort: Optional[str] = None,
               timeout_s: float = 20.0, tier: str = "fast") -> Optional[str]:
    """One chat completion. Returns the answer text, or None on any failure."""
    base, key, provider = endpoint_for(model)
    if not key:
        return None
    content: Any = prompt
    if image_png:
        content = [{"type": "text", "text": prompt},
                   {"type": "image_url", "image_url": {"url": png_data_url(image_png)}}]
    body: Dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
        "max_completion_tokens": max_tokens,
    }
    if reasoning_effort and provider == "meta":
        body["reasoning_effort"] = reasoning_effort
    record: Dict[str, Any] = {"model": model, "tier": tier, "provider": provider, "ok": False,
                              "with_image": bool(image_png)}
    t0 = time.monotonic()
    try:
        r = await _client().post(f"{base}/chat/completions", json=body, timeout=timeout_s,
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        record.update(latency_ms=round((time.monotonic() - t0) * 1000), status=r.status_code)
        if r.status_code >= 400:
            logger.warning("%s %s on %s: %s", provider, r.status_code, model, r.text[:300])
            return None
        data = r.json()
        usage = data.get("usage") or {}
        record.update(prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"),
                      reasoning_tokens=(usage.get("completion_tokens_details") or {}).get("reasoning_tokens"))
        choice = (data.get("choices") or [{}])[0]
        if choice.get("finish_reason") == "length":
            record["truncated"] = True
        text = (choice.get("message") or {}).get("content") or ""
        if isinstance(text, list):   # some providers return content parts
            text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
        from app.services.model_runtime import strip_reasoning
        text = strip_reasoning(text)
        if not text:
            return None
        record["ok"] = True
        return text
    except Exception as exc:
        record.setdefault("latency_ms", round((time.monotonic() - t0) * 1000))
        record["error"] = type(exc).__name__
        logger.warning("%s call to %s failed: %s", provider, model, exc)
        return None
    finally:
        _log(**record)
        from app.observability import tracing
        tracing.llm_call(model=model, provider=provider, tier=tier, system=system, prompt=prompt,
                         output=locals().get("text") if record.get("ok") else None, with_image=bool(image_png),
                         error=None if record.get("ok") else str(record.get("error") or record.get("status")),
                         latency_ms=record.get("latency_ms"), prompt_tokens=record.get("prompt_tokens"),
                         completion_tokens=record.get("completion_tokens"))


# --- SAM 3.1 ---------------------------------------------------------------------------------

_BOX_RE = re.compile(r"<\|box;([^|]*)\|>")
_LINE_RE = re.compile(r"<(\d+)f>")


def parse_sam_boxes(text: str) -> List[Dict[str, float]]:
    """Boxes from SAM's output text (masks are ignored).

    Format (dev.meta.ai/docs/sam/reading-segmentation): one line per frame starting
    `<Nf>`, then records `id<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..[;c=..]|><|mask;...|>`.
    Coordinates are source pixels; w/h are the frame size."""
    boxes: List[Dict[str, float]] = []
    for m in _BOX_RE.finditer(text or ""):
        fields = {}
        for part in m.group(1).split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                try:
                    fields[k.strip()] = float(v)
                except ValueError:
                    pass
        if all(k in fields for k in ("x1", "y1", "x2", "y2", "w", "h")) and fields["w"] > 0 and fields["h"] > 0:
            boxes.append(fields)
    return boxes


def _sam_text_from_response(data: Dict[str, Any]) -> str:
    """Non-streaming Responses API body -> concatenated output_text."""
    out = []
    for item in data.get("output") or []:
        if item.get("type") == "message":
            for part in item.get("content") or []:
                if part.get("type") == "output_text":
                    out.append(part.get("text") or "")
    return "".join(out) or str(data.get("output_text") or "")


async def sam_segment(png: bytes, concept: str) -> Tuple[Optional[List[Dict[str, float]]], Dict[str, Any]]:
    """Ask SAM 3.1 for every instance of `concept` in the image. Returns (boxes, call record);
    boxes is None on failure and [] when nothing matched (a valid answer)."""
    key = settings.model_api_key or ""
    record: Dict[str, Any] = {"model": settings.sam_model, "tier": "vision", "provider": "meta", "ok": False,
                              "concept": concept}
    if not key:
        return None, record
    body = {
        "model": settings.sam_model,
        "input": [{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": concept},
            {"type": "input_image", "image_url": png_data_url(png)},
        ]}],
        "stream": True,
    }
    t0 = time.monotonic()
    try:
        chunks: List[str] = []
        async with _client().stream("POST", f"{settings.meta_base_url.rstrip('/')}/responses", json=body,
                                    timeout=settings.sam_timeout_s,
                                    headers={"Authorization": f"Bearer {key}", "Accept": "text/event-stream",
                                             "Content-Type": "application/json"}) as r:
            record["status"] = r.status_code
            if r.status_code >= 400:
                logger.warning("SAM %s: %s", r.status_code, (await r.aread())[:300])
                return None, record
            if "text/event-stream" not in r.headers.get("content-type", ""):
                text = _sam_text_from_response(json.loads(await r.aread()))
            else:
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        event = json.loads(payload)
                    except ValueError:
                        continue
                    if event.get("type") == "response.output_text.delta":
                        chunks.append(event.get("delta") or "")
                    elif event.get("type") == "response.completed":
                        break
                text = "".join(chunks)
        record["latency_ms"] = round((time.monotonic() - t0) * 1000)
        boxes = parse_sam_boxes(text)
        record.update(ok=True, detections=len(boxes))
        return boxes, record
    except Exception as exc:
        record.setdefault("latency_ms", round((time.monotonic() - t0) * 1000))
        record["error"] = type(exc).__name__
        logger.warning("SAM call failed: %s", exc)
        return None, record
    finally:
        _log(**record)
        from app.observability import tracing
        tracing.llm_call(model=settings.sam_model, provider="meta", tier="vision", prompt=concept,
                         output=f"{record.get('detections', 0)} detection(s)" if record.get("ok") else None,
                         with_image=True, error=None if record.get("ok") else str(record.get("error") or record.get("status")),
                         latency_ms=record.get("latency_ms"))


# --- Muse Voice Transcribe ------------------------------------------------------------------------

async def transcribe(wav: bytes) -> Tuple[Optional[str], Dict[str, Any]]:
    """WAV (mono 16-bit PCM, 16 or 24 kHz) -> transcript."""
    key = settings.model_api_key or ""
    record: Dict[str, Any] = {"model": settings.voice_model, "tier": "voice", "provider": "meta", "ok": False}
    if not key:
        return None, record
    request = json.dumps({"mode": "PUSH_TO_TALK", "model": settings.voice_model, "audioEncoding": "WAV"})
    t0 = time.monotonic()
    try:
        r = await _client().post(
            f"{settings.meta_base_url.rstrip('/')}/asr/transcribe",
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            files=[("request", (None, request, "application/json")), ("audio", ("audio.wav", wav, "audio/wav"))],
            timeout=20.0,
        )
        record.update(latency_ms=round((time.monotonic() - t0) * 1000), status=r.status_code)
        if r.status_code >= 400:
            logger.warning("Transcribe %s: %s", r.status_code, r.text[:300])
            return None, record
        transcript = (r.json() or {}).get("transcript") or ""
        record["ok"] = True
        return transcript, record
    except Exception as exc:
        record.setdefault("latency_ms", round((time.monotonic() - t0) * 1000))
        record["error"] = type(exc).__name__
        logger.warning("Transcribe failed: %s", exc)
        return None, record
    finally:
        _log(**record)
        from app.observability import tracing
        tracing.llm_call(model=settings.voice_model, provider="meta", tier="voice", prompt="(operator audio)",
                         output=locals().get("transcript") if record.get("ok") else None,
                         error=None if record.get("ok") else str(record.get("error") or record.get("status")),
                         latency_ms=record.get("latency_ms"))
