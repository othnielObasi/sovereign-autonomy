from __future__ import annotations

"""HTTP middleware stack for the Sovereign Autonomy backend.

Provides two middleware classes:

- **SecurityHeadersMiddleware** — injects OWASP-recommended security headers
  (X-Content-Type-Options, X-Frame-Options, HSTS in production, CSP).
- **RateLimitMiddleware** — sliding-window in-memory rate limiter that
  tracks requests per client IP.  Exempt paths: ``/health``, docs, OPTIONS.

Both are registered in ``main.py`` during app startup.
"""

import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
from typing import Deque, DefaultDict

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings


_DOC_PATHS = ("/docs", "/redoc", "/openapi.json")
_RATE_LIMIT_EXEMPT_PATHS = ("/health",)


def _is_doc_path(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in _DOC_PATHS)


def _get_client_identifier(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "").strip()
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


@dataclass
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int


class InMemoryRateLimiter:
    """Sliding-window rate limiter backed by an in-memory deque per client.

    Each request appends a monotonic timestamp to the client's bucket.
    Old entries (outside the window) are pruned on every check.  If the
    bucket is full, the request is rejected with a ``Retry-After`` hint.
    Thread-safe via a global :class:`threading.Lock`.
    """
    def __init__(self) -> None:
        self._buckets: DefaultDict[str, Deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()

    def check(self, client_id: str, limit: int, window_seconds: int) -> RateLimitDecision:
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets[client_id]
            cutoff = now - window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= limit:
                retry_after = max(1, math.ceil(window_seconds - (now - bucket[0])))
                return RateLimitDecision(False, limit, 0, retry_after)

            bucket.append(now)
            remaining = max(0, limit - len(bucket))
            reset_seconds = window_seconds if not bucket else max(1, math.ceil(window_seconds - (now - bucket[0])))
            return RateLimitDecision(True, limit, remaining, reset_seconds)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject OWASP-recommended security headers on every response.

    In production, also adds HSTS.  CSP is omitted on doc paths so
    Swagger UI / ReDoc can load their own scripts.
    """
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        if not settings.security_headers_enabled:
            return response

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), camera=(), microphone=()")

        if settings.is_production:
            response.headers.setdefault(
                "Strict-Transport-Security",
                f"max-age={settings.hsts_max_age_seconds}; includeSubDomains",
            )

        if not _is_doc_path(request.url.path):
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            )

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """ASGI middleware enforcing per-IP rate limits.

    Exempt paths: ``/health``, ``/docs``, ``/redoc``, ``/openapi.json``,
    ``OPTIONS`` pre-flight, and the root ``/``.
    """
    def __init__(self, app, limiter: InMemoryRateLimiter):
        super().__init__(app)
        self._limiter = limiter

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if (
            not settings.rate_limit_active
            or request.method == "OPTIONS"
            or path == "/"
            or path.startswith(_RATE_LIMIT_EXEMPT_PATHS)
            or _is_doc_path(path)
        ):
            return await call_next(request)

        decision = self._limiter.check(
            _get_client_identifier(request),
            settings.rate_limit_requests_per_minute,
            60,
        )

        headers = {
            "X-RateLimit-Limit": str(decision.limit),
            "X-RateLimit-Remaining": str(decision.remaining),
            "X-RateLimit-Reset": str(decision.reset_seconds),
        }
        if not decision.allowed:
            headers["Retry-After"] = str(decision.reset_seconds)
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers=headers,
            )

        response = await call_next(request)
        for key, value in headers.items():
            response.headers.setdefault(key, value)
        return response