"""Single place that decides which LLM planner backend to use.

Nemotron on Nebius Token Factory is preferred; Gemini remains as a secondary
provider; with neither configured, GeminiPlanner's deterministic fallbacks run
(it returns rule-based plans when it has no API key).
"""
from __future__ import annotations

from app.config import settings
from app.services.gemini_planner import GeminiPlanner


def get_planner() -> GeminiPlanner:
    if settings.nemotron_configured:
        from app.services.nemotron_planner import NemotronPlanner
        return NemotronPlanner()
    return GeminiPlanner()


def provider_name() -> str:
    return settings.planner_provider
