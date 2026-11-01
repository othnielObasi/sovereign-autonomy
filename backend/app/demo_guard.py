"""Public-demo guardrails (PUBLIC_DEMO=true).

A public link means strangers share one simulated robot and the operator's
Token Factory and Tavily credits. In demo mode:

- Shared settings are read-only: rule changes, rollbacks and deleting missions
  return 403. Everyone sees the same rules.
- One mission at a time: starting or resuming a run while another is active
  returns 409 with the active run, so the visitor can watch it instead.
- Paid actions have a site-wide hourly budget (mission starts, direct model
  calls, vision checks, Tavily lookups and bulletins); over it returns 429.
- Missions stop automatically after DEMO_MAX_RUN_S (enforced in the run loop).

Paths here are the backend's own (the reverse proxy strips /api).
"""
from __future__ import annotations

import re
import threading
import time
from collections import deque
from typing import Deque, Dict, Optional, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

# Shared settings nobody on a public link may change
READ_ONLY = [
    re.compile(r"^/policies/proposals"),
    re.compile(r"^/policies/rollback$"),
    re.compile(r"^/agent/memory/learn/"),
]
# DELETE /missions/{id}
DELETE_BLOCKED = re.compile(r"^/missions/[^/]+$")

# Starting robot motion: one active run at a time
STARTS = [
    re.compile(r"^/runs$"),
    re.compile(r"^/missions/[^/]+/(start|replay|resume)$"),
    re.compile(r"^/runs/[^/]+/resume$"),
]

# Paid actions: (budget key, pattern)
PAID: Tuple[Tuple[str, re.Pattern], ...] = (
    ("missions", re.compile(r"^/runs$")),
    ("missions", re.compile(r"^/missions/[^/]+/(start|replay)$")),
    ("model_calls", re.compile(r"^/llm/")),
    ("vision_checks", re.compile(r"^/perception/check$")),
    ("site_intel", re.compile(r"^/site-intel/(lookup|bulletin)$")),
)


class HourlyBudget:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: Dict[str, Deque[float]] = {}

    def take(self, key: str, limit: int, now: Optional[float] = None) -> Optional[int]:
        """Record one use; return seconds to wait if over the hourly limit."""
        now = time.time() if now is None else now
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and q[0] <= now - 3600:
                q.popleft()
            if len(q) >= limit:
                return max(1, int(3600 - (now - q[0])))
            q.append(now)
            return None


budget = HourlyBudget()


def _limit(key: str) -> int:
    return {
        "missions": settings.demo_missions_per_hour,
        "model_calls": settings.demo_model_calls_per_hour,
        "vision_checks": settings.demo_vision_checks_per_hour,
        "site_intel": settings.demo_site_intel_per_hour,
    }[key]


def _active_run() -> Optional[str]:
    from app.db.models import Run
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        run = db.query(Run).filter(Run.status.in_(("planning", "running", "paused"))).first()
        return run.id if run else None
    finally:
        db.close()


def _deny(status: int, message: str, **extra) -> JSONResponse:
    headers = {"Retry-After": str(extra["retry_after_s"])} if "retry_after_s" in extra else None
    return JSONResponse(status_code=status, content={"detail": message, "public_demo": True, **extra},
                        headers=headers)


class DemoGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not settings.public_demo or request.method not in MUTATING:
            return await call_next(request)
        path = request.url.path.rstrip("/") or "/"

        if any(p.match(path) for p in READ_ONLY) or (request.method == "DELETE" and DELETE_BLOCKED.match(path)):
            return _deny(403, "Disabled on the public demo: shared safety settings are read-only.")

        if any(p.match(path) for p in STARTS):
            active = _active_run()
            if active:
                return _deny(409, f"A mission is already running on the shared robot. Watch it at /runs/{active}.",
                             active_run_id=active)

        for key, pattern in PAID:
            if pattern.match(path):
                wait = budget.take(key, _limit(key))
                if wait is not None:
                    return _deny(429, f"Public demo limit reached for {key.replace('_', ' ')}; try again later.",
                                 retry_after_s=wait)
                break

        return await call_next(request)
