"""Single place that decides which LLM planner backend to use.

Meta Muse (Muse Spark on the Meta Model API, Muse Spark Open on Baseten).
Gemini remains as a secondary provider from the earlier codebase. With neither
configured, the deterministic fallbacks run.
"""
from __future__ import annotations

from app.config import settings
from app.services.gemini_planner import GeminiPlanner


def get_planner() -> GeminiPlanner:
    if settings.muse_configured or settings.muse_open_configured:
        from app.services.muse_planner import MusePlanner
        return MusePlanner()
    return GeminiPlanner()


def provider_name() -> str:
    return settings.planner_provider
