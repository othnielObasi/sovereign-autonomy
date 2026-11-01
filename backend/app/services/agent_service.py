from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple
from app.schemas.governance import ActionProposal, GovernanceDecision

logger = logging.getLogger("app.agent_service")


class SimpleAgent:
    """A tiny agent that proposes actions.

    For MVP reliability, this is deterministic and structured (no LLM required).
    It still demonstrates the loop: propose -> govern -> execute -> audit.

    Behavior:
    - Move toward goal with initial speed 0.8
    - If last decision was denied/reviewed due to speed, reduce to 0.4
    """

    def __init__(self):
        self.last_adjusted_speed: Optional[float] = None

    def propose(self, telemetry: Dict[str, Any], goal: Dict[str, Any], last_governance: Optional[Dict[str, Any]] = None) -> ActionProposal:
        x, y = float(telemetry.get("x", 0.0)), float(telemetry.get("y", 0.0))
        gx, gy = float(goal.get("x", 0.0)), float(goal.get("y", 0.0))

        # If close to goal, stop
        if abs(x - gx) < 0.3 and abs(y - gy) < 0.3:
            return ActionProposal(intent="STOP", params={}, rationale="Reached goal.")

        # Default higher speed
        speed = 0.8
        rationale_parts = ["Navigate toward mission goal"]

        # Structured denial feedback: adapt behavior based on governance reasons
        if last_governance:
            decision = last_governance.get("decision", "")
            hits = set(last_governance.get("policy_hits", []))
            reasons = last_governance.get("reasons", [])

            if decision in ("DENIED", "NEEDS_REVIEW"):
                if hits & {"SAFE_SPEED_01", "HUMAN_CLEARANCE_02", "HUMAN_PROXIMITY_02",
                           "OBSTACLE_CLEARANCE_03", "UNCERTAINTY_04", "WORKER_PROXIMITY_06"}:
                    speed = 0.2  # Well below MAX_SPEED_NEAR_HUMAN (0.4)
                    rationale_parts.append(f"reduced speed due to: {', '.join(hits & {'SAFE_SPEED_01', 'HUMAN_CLEARANCE_02', 'HUMAN_PROXIMITY_02', 'OBSTACLE_CLEARANCE_03'})}")

                if "GEOFENCE_01" in hits:
                    # Clamp target to geofence bounds
                    from app.world_model import GEOFENCE
                    gx = max(GEOFENCE["min_x"] + 0.5, min(gx, GEOFENCE["max_x"] - 0.5))
                    gy = max(GEOFENCE["min_y"] + 0.5, min(gy, GEOFENCE["max_y"] - 0.5))
                    rationale_parts.append("clamped target to geofence after GEOFENCE_01 denial")

        return ActionProposal(
            intent="MOVE_TO",
            params={"x": gx, "y": gy, "max_speed": speed},
            rationale="; ".join(rationale_parts),
        )


class AgentRouter:
    """Select between deterministic, LLM, or agentic planner.

    Modes (via settings.llm_provider):
    - "nemotron" → Single-call Nemotron planner on Nebius Token Factory
    - "gemini"   → Single-call GeminiPlanner (fast, stateless)
    - "agentic"  → ReAct agent with tool use, memory, replanning
    - default    → Deterministic SimpleAgent
    """

    def __init__(self):
        self.simple = SimpleAgent()
        self._gemini = None
        self._agentic = None
        self._last_thought_chain: List[Dict[str, Any]] = []

    def _gemini_planner(self):
        if self._gemini is None:
            from app.services.llm_factory import get_planner
            self._gemini = get_planner()
        return self._gemini

    def _agentic_planner(self):
        if self._agentic is None:
            from app.services.agentic_planner import AgenticPlanner
            self._agentic = AgenticPlanner()
        return self._agentic

    @property
    def last_thought_chain(self) -> List[Dict[str, Any]]:
        """Last agentic reasoning chain (for UI/audit)."""
        return self._last_thought_chain

    def record_outcome(self, proposal: ActionProposal, governance: GovernanceDecision, was_executed: bool) -> None:
        """Feed outcome back to agentic memory (no-op for non-agentic modes)."""
        if self._agentic:
            self._agentic.record_outcome(proposal, governance, was_executed)

    def get_agent_memory(self) -> Optional[Dict[str, Any]]:
        """Return agentic memory summary if agentic mode is active."""
        if self._agentic:
            return self._agentic.get_memory_summary()
        return None

    async def propose(
        self,
        telemetry: Dict[str, Any],
        goal: Dict[str, float],
        nl_task: str,
        last_governance: Optional[Dict[str, Any]] = None,
        world: Optional[Dict[str, Any]] = None,
    ) -> ActionProposal:
        from app.config import settings
        self._last_thought_chain = []

        if not settings.llm_enabled:
            return self.simple.propose(telemetry, goal, last_governance)

        provider = settings.llm_provider

        # ── Agentic mode (ReAct with tools + memory) ──
        if provider == "agentic":
            try:
                proposal, thoughts, model = await self._agentic_planner().propose(
                    telemetry, goal, nl_task, last_governance, world,
                )
                self._last_thought_chain = [
                    {
                        "step": t.step_number,
                        "thought": t.thought,
                        "action": t.action,
                        "action_input": t.action_input,
                        "observation": t.observation,
                    }
                    for t in thoughts
                ]
                logger.info(f"[Agentic] {len(thoughts)} reasoning steps via {model}")
                return proposal
            except Exception as e:
                logger.exception(f"[Agentic] Failed: {e}, falling back to deterministic")
                return self.simple.propose(telemetry, goal, last_governance)

        # ── Single-call LLM mode (Nemotron preferred, Gemini fallback) ──
        if provider in ("nemotron", "gemini"):
            try:
                return await self._gemini_planner().propose(telemetry, goal, nl_task, last_governance)
            except Exception:
                return self.simple.propose(telemetry, goal, last_governance)

        return self.simple.propose(telemetry, goal, last_governance)
