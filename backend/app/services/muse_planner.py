"""Meta Muse planner: Muse Spark plans missions, Muse Spark Open proposes steps.

Drop-in replacement for GeminiPlanner (same prompts, parsing and deterministic
fallbacks); only the model transport and routing change.

* Reasoning tier (mission planning and replanning after a denial): Muse Spark
  with high reasoning effort. It also sees the robot's camera frame, so it can
  plan around people and hazards it sees, not only what the map lists.
* Fast tier (per-step proposals and analysis): Muse Spark Open, Meta's
  open-weight model on Baseten, raced against Muse Spark with low effort.

The planner only proposes. The deterministic gate decides, and only an approved
move gets a single-use permit.
"""
from __future__ import annotations

import contextvars
import logging
from typing import Any, Dict, List, Optional

from app.config import settings
from app.services import meta_models
from app.services.gemini_planner import GeminiPlanner
from app.services.nemotron_planner import TIER_FAST, TIER_REASONING, _tier, reasoning_tier

logger = logging.getLogger("app.muse_planner")

SYSTEM_PROMPT = (
    "You are the planning component inside a governed warehouse-robotics system. "
    "A deterministic safety policy engine reviews every action you propose and may deny it; "
    "nothing you say can authorize a move. Respond with the STRICT JSON requested and nothing else. "
    "If an image is attached, it is the robot's top-down camera: the robot is the blue triangle pointing up, "
    "orange circles are people, yellow shapes are the forklift, light-blue patches are spills, brown squares "
    "are pallets, long dark-brown bars are racks. Use it to keep the route clear of people and hazards; the "
    "numeric STATE is authoritative for positions."
)

_frame: contextvars.ContextVar[Optional[bytes]] = contextvars.ContextVar("muse_frame", default=None)
# The robot whose camera a mission plan should use (set by the caller; default robot if unset)
planning_robot: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("planning_robot", default=None)


def _dedupe(models: List[str]) -> List[str]:
    seen, out = set(), []
    for m in models:
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    return out


class MusePlanner(GeminiPlanner):
    provider = "muse"

    def __init__(self) -> None:
        super().__init__()
        # Truthy key so the inherited code paths call the model instead of the fallback
        self.api_key = settings.model_api_key or settings.baseten_api_key
        self.reasoning_model = settings.muse_reasoning_model if settings.muse_configured else settings.muse_open_model
        fast = []
        if settings.muse_open_configured:
            fast.append(settings.muse_open_model)
        if settings.muse_configured:
            fast.append(settings.muse_fast_model)
        self.fast_models = _dedupe(fast) or [self.reasoning_model]
        self.primary_model = self.fast_models[0]
        self.model_cascade = _dedupe([self.reasoning_model] + self.fast_models)

    @property
    def current_tier(self) -> str:
        return _tier.get()

    def _get_cascade(self, preferred_model: Optional[str] = None, fast: bool = False) -> List[str]:
        if _tier.get() == TIER_REASONING:
            base = _dedupe([self.reasoning_model] + self.fast_models)
        else:
            base = list(self.fast_models)
        if preferred_model and preferred_model in self.model_cascade:
            return [preferred_model] + [m for m in base if m != preferred_model]
        return base

    async def _race_models(self, models: List[str], prompt: str) -> tuple[Optional[str], str]:
        if _tier.get() == TIER_REASONING:
            # The reasoning model gets its full chance before any fallback.
            for model in models:
                text = await self._call_gemini(model, prompt)
                if text:
                    return text, model
            return None, "none"
        return await super()._race_models(models, prompt)

    async def _call_gemini(self, model: str, prompt: str) -> Optional[str]:
        """Keeps the parent's method name so every inherited path routes here."""
        reasoning = _tier.get() == TIER_REASONING
        return await meta_models.chat(
            model, SYSTEM_PROMPT, prompt,
            image_png=_frame.get() if reasoning else None,
            max_tokens=8192 if reasoning else 2048,
            reasoning_effort=settings.muse_reasoning_effort if reasoning else settings.muse_fast_effort,
            timeout_s=settings.muse_reasoning_timeout_s if reasoning else settings.muse_fast_timeout_s,
            tier=TIER_REASONING if reasoning else TIER_FAST,
        )

    async def _camera_frame(self) -> Optional[bytes]:
        if not settings.muse_plan_with_camera:
            return None
        from app.services.sim_adapter import SimAdapter
        sim = SimAdapter()
        try:
            robot = planning_robot.get()
            return await (sim.get_frame(size=512, robot_id=robot) if robot else sim.get_frame(size=512))
        except Exception as exc:   # no camera: plan from the map alone
            logger.info("No camera frame for planning: %s", exc)
            return None
        finally:
            await sim.close()

    async def generate_plan(self, telemetry: Dict[str, Any], instruction: str,
                            goal: Optional[Dict[str, float]] = None,
                            preferred_model: Optional[str] = None,
                            lessons: Optional[List[Dict[str, Any]]] = None,
                            untrusted_context: str = "") -> Dict[str, Any]:
        """Mission planning on the reasoning tier, with the camera frame attached."""
        frame = await self._camera_frame()
        token = _frame.set(frame)
        try:
            with reasoning_tier():
                plan = await super().generate_plan(telemetry, instruction, goal, preferred_model,
                                                   lessons=lessons, untrusted_context=untrusted_context)
        finally:
            _frame.reset(token)
        plan["tier"] = TIER_REASONING
        plan["camera_used"] = bool(frame) and plan.get("model_used") not in (None, "deterministic_fallback")
        return plan
