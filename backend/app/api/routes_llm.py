from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.services.gemini_planner import GeminiPlanner, resolve_bay_from_instruction
from app.services.llm_factory import get_planner
from app.services.sim_adapter import SimAdapter
from app.services.governance_engine import GovernanceEngine
from app.policies.rules_python import evaluate_policies, GEOFENCE
from app.schemas.governance import ActionProposal
from app.utils.hashing import sha256_canonical
from app.utils.time import utc_now

logger = logging.getLogger("app.routes_llm")

router = APIRouter(prefix="/llm", tags=["llm"])


class PlanRequest(BaseModel):
    instruction: str = Field(..., description="Natural-language instruction for the robot")
    goal: Optional[Dict[str, Any]] = Field(None, description="Optional {x, y, zone?} goal coordinate")
    model: Optional[str] = Field(None, description="Preferred starting model (e.g. nvidia/nemotron-3-super-120b-a12b). Falls back through cascade.")


class ExecuteRequest(BaseModel):
    instruction: str = Field(..., description="The original instruction")
    waypoints: List[Dict[str, Any]] = Field(..., description="Waypoints to execute [{x, y, max_speed}, ...]")
    rationale: str = Field("", description="Plan rationale from Gemini")


class AnalyzeRequest(BaseModel):
    events: List[Dict[str, Any]] = Field(..., description="Mission event log entries")
    question: Optional[str] = Field(None, description="Optional operator question about the telemetry")
    model: Optional[str] = Field(None, description="Preferred starting model. Falls back through cascade.")


class SceneRequest(BaseModel):
    scene_description: str = Field(..., description="Text description of the camera/scene")
    include_telemetry: bool = Field(True, description="Include current sim telemetry for context")
    model: Optional[str] = Field(None, description="Preferred starting model. Falls back through cascade.")


class FailureRequest(BaseModel):
    events: List[Dict[str, Any]] = Field(..., description="Mission event log entries")
    model: Optional[str] = Field(None, description="Preferred starting model. Falls back through cascade.")


class Waypoint(BaseModel):
    x: float
    y: float
    max_speed: float


class WaypointPolicy(BaseModel):
    waypoint_index: int
    decision: str
    policy_hits: List[str]
    reasons: List[str]
    policy_state: str


class PlanResponse(BaseModel):
    waypoints: List[Waypoint]
    rationale: str
    estimated_time_s: float
    governance: List[WaypointPolicy]
    all_approved: bool


class ExecutionStep(BaseModel):
    waypoint_index: int
    waypoint: Dict[str, float]
    governance_decision: str
    policy_state: str
    policy_hits: List[str]
    executed: bool
    sim_result: Optional[Dict[str, Any]] = None
    telemetry_after: Optional[Dict[str, Any]] = None
    movement_m: Optional[float] = None


class ExecuteResponse(BaseModel):
    status: str  # "completed" | "completed_with_warnings" | "blocked" | "partial"
    instruction: str
    rationale: str
    steps: List[ExecutionStep]
    audit_hash: str


class Hazard(BaseModel):
    type: str
    severity: str
    description: str
    estimated_distance_m: Optional[float] = None


class SceneResponse(BaseModel):
    hazards: List[Hazard]
    risk_score: float
    recommended_action: str
    reasoning: str
    model_used: str


class FailureItem(BaseModel):
    type: str
    severity: str
    description: str
    mitigation: str


class FailureResponse(BaseModel):
    failures: List[FailureItem]
    total_events_analyzed: int
    health_status: str
    model_used: str


_sim = SimAdapter()
_gov = GovernanceEngine()
_planner: Optional[GeminiPlanner] = None


def _get_planner() -> GeminiPlanner:
    global _planner
    if _planner is None:
        _planner = get_planner()
    return _planner


@router.get("/usage")
async def llm_usage(limit: int = 50):
    """Per-model latency and token usage for Nemotron calls (process-local).

    Powers the 'cost and latency per decision' view: which tier handled the
    call, p50/p95 latency, and prompt/completion tokens.
    """
    from app.services.nemotron_planner import usage_log
    return {
        "provider": settings.planner_provider,
        "summary": usage_log.summary(),
        "recent": usage_log.recent(limit=max(1, min(limit, 500))),
    }


@router.get("/models")
async def list_models():
    """List the active planner provider, its model tiers and cascade order."""
    from app.services.gemini_planner import MODEL_CASCADE
    planner = _get_planner()
    if getattr(planner, "provider", None) == "nemotron":
        return {
            "provider": "nemotron",
            "primary": planner.primary_model,
            "tiers": {"fast": planner.fast_models, "reasoning": planner.reasoning_model},
            "cascade": planner.model_cascade,
            "available": planner.model_cascade,
            "deterministic_fallback": True,
        }
    return {
        "provider": settings.planner_provider,
        "primary": planner.primary_model,
        "cascade": planner.model_cascade,
        "available": MODEL_CASCADE,
        "deterministic_fallback": True,
    }


@router.post("/plan", response_model=PlanResponse)
async def generate_plan(body: PlanRequest):
    """Generate a multi-waypoint plan via Gemini and validate every waypoint
    against governance policies.

    Returns the plan, rationale, and per-waypoint governance results.
    """
    # Get current telemetry for context
    try:
        telemetry = await _sim.get_telemetry()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Cannot reach simulator: {e}")

    # Fetch world to get bays for coordinate resolution
    try:
        world = await _sim.get_world()
    except Exception:
        world = {}
    bays = world.get("bays", [])

    # Auto-resolve bay name from instruction to goal coordinates
    goal = body.goal
    if not goal:
        resolved = resolve_bay_from_instruction(body.instruction, bays)
        if resolved:
            goal = resolved

    planner = _get_planner()
    planner.set_bays(bays)
    try:
        plan = await planner.generate_plan(telemetry, body.instruction, goal, preferred_model=body.model)
    except Exception as e:
        logger.exception("Gemini plan generation failed")
        raise HTTPException(status_code=502, detail=f"Gemini plan generation failed: {e}")

    waypoints = plan.get("waypoints", [])
    rationale = plan.get("rationale", "")
    estimated_time_s = plan.get("estimated_time_s", 0)

    # Validate each waypoint against governance policies
    governance_results: List[WaypointPolicy] = []
    all_approved = True

    for idx, wp in enumerate(waypoints):
        proposal = ActionProposal(
            intent="MOVE_TO",
            params={"x": wp["x"], "y": wp["y"], "max_speed": wp["max_speed"]},
            rationale=f"Waypoint {idx + 1} of generated plan",
        )
        decision = evaluate_policies(telemetry, proposal)
        gov_result = WaypointPolicy(
            waypoint_index=idx,
            decision=decision.decision,
            policy_hits=decision.policy_hits,
            reasons=decision.reasons,
            policy_state=decision.policy_state,
        )
        governance_results.append(gov_result)
        if decision.decision != "APPROVED":
            all_approved = False

    return PlanResponse(
        waypoints=[Waypoint(**wp) for wp in waypoints],
        rationale=rationale,
        estimated_time_s=estimated_time_s,
        governance=governance_results,
        all_approved=all_approved,
    )


@router.post("/execute", response_model=ExecuteResponse)
async def execute_plan(body: ExecuteRequest):
    """Execute an LLM-generated plan: send each waypoint to the simulator
    sequentially, validating governance at each step, and building a
    tamper-proof audit trail.

    This is the key flow: NL instruction → Gemini plan → governance → sim execution → audit.
    """
    steps: List[ExecutionStep] = []
    overall_status = "completed"
    audit_records: List[Dict[str, Any]] = []

    for idx, wp in enumerate(body.waypoints):
        # Get fresh telemetry before each waypoint
        try:
            telemetry = await _sim.get_telemetry()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Simulator unreachable: {e}")

        # Build proposal
        proposal = ActionProposal(
            intent="MOVE_TO",
            params={"x": float(wp["x"]), "y": float(wp["y"]), "max_speed": float(wp.get("max_speed", 0.5))},
            rationale=f"Waypoint {idx + 1}: LLM plan for '{body.instruction}'",
        )

        # Governance evaluation
        gov = _gov.evaluate(telemetry, proposal)

        step = ExecutionStep(
            waypoint_index=idx,
            waypoint=wp,
            governance_decision=gov.decision,
            policy_state=gov.policy_state,
            policy_hits=gov.policy_hits,
            executed=False,
            sim_result=None,
            telemetry_after=None,
        )

        # Audit record
        audit_records.append({
            "ts": utc_now().isoformat(),
            "waypoint_index": idx,
            "proposal": proposal.model_dump(),
            "governance": gov.model_dump(),
        })

        if gov.decision != "DENIED":
            # APPROVED or NEEDS_REVIEW — execute (NEEDS_REVIEW is a warning, not a block)
            cmd = {"intent": "MOVE_TO", "params": proposal.params}
            try:
                result = await _sim.send_command(cmd)
                step.executed = True
                step.sim_result = result
            except Exception as e:
                step.sim_result = {"error": str(e)}
                overall_status = "partial"

            # Wait for robot to move toward waypoint (short settle time)
            await asyncio.sleep(0.5)

            # Capture post-execution telemetry
            try:
                step.telemetry_after = await _sim.get_telemetry()
            except Exception:
                pass

            # Compute movement displacement from pre->post telemetry for diagnostics
            try:
                if step.telemetry_after and telemetry and telemetry.get("x") is not None and telemetry.get("y") is not None:
                    bx, by = float(telemetry.get("x", 0.0)), float(telemetry.get("y", 0.0))
                    ax, ay = float(step.telemetry_after.get("x", 0.0)), float(step.telemetry_after.get("y", 0.0))
                    step.movement_m = ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
            except Exception:
                step.movement_m = None

            # If NEEDS_REVIEW, note it but continue
            if gov.decision == "NEEDS_REVIEW" and overall_status == "completed":
                overall_status = "completed_with_warnings"
        else:
            # DENIED — governance hard-blocks this waypoint
            overall_status = "blocked" if idx == 0 else "partial"
            steps.append(step)
            break  # Stop at first denied waypoint

        steps.append(step)

    # Build audit hash for the entire execution
    audit_payload = {
        "instruction": body.instruction,
        "rationale": body.rationale,
        "steps": [s.model_dump() for s in steps],
        "status": overall_status,
    }
    audit_hash = sha256_canonical(audit_payload)

    return ExecuteResponse(
        status=overall_status,
        instruction=body.instruction,
        rationale=body.rationale,
        steps=steps,
        audit_hash=audit_hash,
    )


@router.post("/analyze")
async def analyze_telemetry(body: AnalyzeRequest):
    """Analyze mission event logs for anomalies, denials, safety near-misses, and compliance risks."""
    if not body.events:
        raise HTTPException(status_code=400, detail="No events provided for analysis.")
    planner = _get_planner()
    try:
        result = await planner.analyze_telemetry(body.events, body.question, preferred_model=body.model)
    except Exception as e:
        logger.exception("Telemetry analysis failed")
        raise HTTPException(status_code=502, detail=f"Analysis failed: {e}")
    result["audit_hash"] = sha256_canonical({"type": "ANALYSIS", "result": result})
    return result


@router.post("/scene", response_model=SceneResponse)
async def analyze_scene(body: SceneRequest):
    """Analyze a scene description for hazards, obstacles, humans, and recommend robot action."""
    telemetry = None
    if body.include_telemetry:
        try:
            telemetry = await _sim.get_telemetry()
        except Exception:
            pass
    planner = _get_planner()
    try:
        result = await planner.analyze_scene(body.scene_description, telemetry, preferred_model=body.model)
    except Exception as e:
        logger.exception("Scene analysis failed")
        raise HTTPException(status_code=502, detail=f"Scene analysis failed: {e}")
    hazards = []
    for h in result.get("hazards", []):
        hazards.append(Hazard(
            type=h.get("type", "OTHER"), severity=h.get("severity", "MEDIUM"),
            description=h.get("description", ""),
            estimated_distance_m=h.get("estimated_distance_m"),
        ))
    return SceneResponse(
        hazards=hazards, risk_score=float(result.get("risk_score", 0.5)),
        recommended_action=result.get("recommended_action", "SLOW"),
        reasoning=result.get("reasoning", ""), model_used=result.get("model_used", "unknown"),
    )


@router.post("/failure-analysis", response_model=FailureResponse)
async def failure_analysis(body: FailureRequest):
    """Detect failure patterns: stuck robots, oscillation, repeated policy conflicts."""
    if not body.events:
        raise HTTPException(status_code=400, detail="No events provided for failure analysis.")
    try:
        telemetry = await _sim.get_telemetry()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Cannot reach simulator: {e}")
    planner = _get_planner()
    try:
        result = await planner.detect_failures(body.events, telemetry, preferred_model=body.model)
    except Exception as e:
        logger.exception("Failure analysis failed")
        raise HTTPException(status_code=502, detail=f"Failure analysis failed: {e}")
    failures = []
    for f in result.get("failures", []):
        failures.append(FailureItem(
            type=f.get("type", "NONE"), severity=f.get("severity", "LOW"),
            description=f.get("description", ""), mitigation=f.get("mitigation", ""),
        ))
    return FailureResponse(
        failures=failures, total_events_analyzed=int(result.get("total_events_analyzed", len(body.events))),
        health_status=result.get("health_status", "OK"), model_used=result.get("model_used", "unknown"),
    )


# ---- Agentic Endpoints ----

class AgenticProposeRequest(BaseModel):
    instruction: str = Field(..., description="Natural-language task for the agent")
    goal: Optional[Dict[str, Any]] = Field(None, description="Optional {x, y, zone?} goal coordinate")


class AgenticThoughtStep(BaseModel):
    step: int
    thought: str
    action: Optional[str] = None
    action_input: Optional[Dict[str, Any]] = None
    observation: Optional[str] = None


class AgenticResponse(BaseModel):
    proposal: Dict[str, Any]
    thought_chain: List[AgenticThoughtStep]
    governance: Dict[str, Any]
    model_used: str
    replanning_used: bool
    memory_summary: Optional[Dict[str, Any]] = None


@router.post("/agentic/propose", response_model=AgenticResponse)
async def agentic_propose(body: AgenticProposeRequest):
    """Run the agentic ReAct planner: reason → use tools → propose → govern."""
    try:
        telemetry = await _sim.get_telemetry()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Cannot reach simulator: {e}")
    try:
        world = await _sim.get_world()
    except Exception:
        world = None

    # Auto-resolve bay name from instruction to goal coordinates
    bays = (world or {}).get("bays", [])
    goal = body.goal
    if not goal:
        resolved = resolve_bay_from_instruction(body.instruction, bays)
        if resolved:
            goal = resolved
    if not goal:
        goal = {"x": 15.0, "y": 10.0}

    from app.services.agentic_planner import AgenticPlanner
    agent = AgenticPlanner()

    try:
        proposal, thoughts, model = await agent.propose(
            telemetry, goal, body.instruction, world=world,
        )
    except Exception as e:
        logger.exception("Agentic proposal failed")
        raise HTTPException(status_code=502, detail=f"Agentic proposal failed: {e}")

    # Governance check
    gov_decision = evaluate_policies(telemetry, proposal)
    agent.record_outcome(proposal, gov_decision, gov_decision.decision == "APPROVED")

    thought_steps = [
        AgenticThoughtStep(
            step=t.step_number,
            thought=t.thought,
            action=t.action,
            action_input=t.action_input,
            observation=t.observation,
        )
        for t in thoughts
    ]

    replanning_used = any(t.action == "replan" for t in thoughts)

    return AgenticResponse(
        proposal=proposal.model_dump(),
        thought_chain=thought_steps,
        governance=gov_decision.model_dump(),
        model_used=model,
        replanning_used=replanning_used,
        memory_summary=agent.get_memory_summary(),
    )
