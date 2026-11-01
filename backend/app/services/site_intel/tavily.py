"""Thin Tavily Search client (https://docs.tavily.com, POST /search).

Returns normalised results plus call metadata. Everything it returns is
untrusted web content: callers must pass it through the firewall.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from app.config import settings

TAVILY_URL = "https://api.tavily.com/search"


@dataclass
class SearchResult:
    title: str
    url: str
    content: str
    score: float
    domain: str


@dataclass
class SearchResponse:
    query: str
    results: List[SearchResult]
    live: bool                      # False = offline samples (no key)
    latency_ms: float = 0.0
    credits: Optional[float] = None
    request_id: Optional[str] = None
    error: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)


def domain_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def configured() -> bool:
    return bool(settings.tavily_api_key)


async def search(query: str, include_domains: List[str], max_results: int = 6,
                 client: Optional[httpx.AsyncClient] = None) -> SearchResponse:
    """Search Tavily, restricted to `include_domains`. Raises nothing: errors come back in `.error`."""
    body = {
        "query": query,
        "search_depth": settings.tavily_search_depth,
        "chunks_per_source": 3,
        "max_results": max_results,
        "include_domains": include_domains,
        "include_answer": False,       # we never use a model-written answer, only sources
        "include_raw_content": False,
        "include_usage": True,
    }
    params = {k: v for k, v in body.items() if k != "query"}
    if not settings.tavily_api_key:
        return SearchResponse(query=query, results=[], live=False, error="no TAVILY_API_KEY", params=params)
    headers = {"Authorization": f"Bearer {settings.tavily_api_key}", "Content-Type": "application/json"}
    t0 = time.perf_counter()
    own = client is None
    client = client or httpx.AsyncClient(timeout=settings.tavily_timeout_s)
    try:
        r = await client.post(TAVILY_URL, json=body, headers=headers)
        latency = (time.perf_counter() - t0) * 1000
        if r.status_code != 200:
            detail = r.text[:200]
            return SearchResponse(query=query, results=[], live=True, latency_ms=latency,
                                  error=f"HTTP {r.status_code}: {detail}", params=params)
        data = r.json()
        results = [
            SearchResult(title=str(x.get("title") or "")[:300], url=str(x.get("url") or ""),
                         content=str(x.get("content") or ""), score=float(x.get("score") or 0.0),
                         domain=domain_of(str(x.get("url") or "")))
            for x in (data.get("results") or []) if x.get("url")
        ]
        return SearchResponse(query=query, results=results, live=True, latency_ms=latency,
                              credits=(data.get("usage") or {}).get("credits"),
                              request_id=data.get("request_id"), params=params)
    except Exception as e:  # network, timeout, bad JSON
        return SearchResponse(query=query, results=[], live=True,
                              latency_ms=(time.perf_counter() - t0) * 1000, error=f"{type(e).__name__}: {e}", params=params)
    finally:
        if own:
            await client.aclose()
