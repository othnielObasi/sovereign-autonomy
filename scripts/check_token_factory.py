#!/usr/bin/env python3
"""Day-1 check for Nebius Token Factory.

1. Lists the NVIDIA models your key can see (so you can set the exact IDs).
2. Smoke-tests the configured fast and reasoning models with a tiny JSON prompt
   and reports latency and token usage for each.

Usage:
    export NEBIUS_API_KEY=...
    python scripts/check_token_factory.py            # list + smoke test
    python scripts/check_token_factory.py --list     # list only

Reads NEMOTRON_FAST_MODELS / NEMOTRON_REASONING_MODEL / NEBIUS_BASE_URL from
the environment if set, otherwise uses the backend defaults.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import httpx

# Windows consoles default to cp1252, which cannot print the check marks below
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

BASE_URL = os.environ.get("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1").rstrip("/")
FAST = [m.strip() for m in os.environ.get(
    "NEMOTRON_FAST_MODELS", "nvidia/Nemotron-3_5-Lightning,nvidia/nemotron-3-super-120b-a12b"
).split(",") if m.strip()]
REASONING = os.environ.get("NEMOTRON_REASONING_MODEL", "nvidia/Nemotron-3-Ultra-550b-a55b")

PROMPT = (
    'A warehouse robot at (2,3) must reach bay B-03 at (12,8). A worker stands at (7,5). '
    'Output STRICT JSON: {"waypoints":[{"x":<float>,"y":<float>,"max_speed":<float>}],"rationale":"..."}'
)


def list_models(client: httpx.Client) -> list[str]:
    r = client.get(f"{BASE_URL}/models")
    r.raise_for_status()
    ids = sorted(m["id"] for m in r.json().get("data", []))
    nvidia = [i for i in ids if "nvidia" in i.lower() or "nemotron" in i.lower()
              or "cosmos" in i.lower() or "gr00t" in i.lower()]
    print(f"\n{len(ids)} models visible; {len(nvidia)} NVIDIA:")
    for i in nvidia:
        print(f"  {i}")
    missing = [m for m in FAST + [REASONING] if m not in ids]
    if missing:
        print("\n⚠  Configured but NOT in your catalogue (update .env):")
        for m in missing:
            print(f"  {m}")
    return ids


def smoke(client: httpx.Client, model: str, timeout: float) -> None:
    t0 = time.monotonic()
    try:
        r = client.post(f"{BASE_URL}/chat/completions", timeout=timeout, json={
            "model": model,
            "messages": [{"role": "user", "content": PROMPT}],
            "temperature": 0.2, "max_tokens": 1024,
        })
        ms = round((time.monotonic() - t0) * 1000)
        if r.status_code >= 400:
            print(f"  ✗ {model}: HTTP {r.status_code} in {ms}ms — {r.text[:160]}")
            return
        data = r.json()
        content = data["choices"][0]["message"].get("content") or ""
        usage = data.get("usage", {})
        ok = "waypoints" in content
        print(f"  {'✓' if ok else '?'} {model}: {ms}ms, "
              f"{usage.get('prompt_tokens')}→{usage.get('completion_tokens')} tokens"
              f"{'' if ok else ' (no waypoints in reply)'}")
    except Exception as e:
        print(f"  ✗ {model}: {type(e).__name__}: {e}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="only list models")
    args = ap.parse_args()

    key = os.environ.get("NEBIUS_API_KEY")
    if not key:
        print("Set NEBIUS_API_KEY first (Token Factory console → API keys).")
        return 1
    with httpx.Client(headers={"Authorization": f"Bearer {key}"}, timeout=30) as client:
        list_models(client)
        if args.list:
            return 0
        print("\nFast tier:")
        for m in FAST:
            smoke(client, m, timeout=20)
        print("\nReasoning tier:")
        smoke(client, REASONING, timeout=60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
