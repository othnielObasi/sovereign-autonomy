from __future__ import annotations

import asyncio
import json
import logging
import re
import time as _time
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from app.schemas.governance import ActionProposal
from app.world_model import GEOFENCE as _WM_GEOFENCE


logger = logging.getLogger("app.gemini_planner")


def resolve_bay_from_instruction(instruction: str, bays: List[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    """Extract a bay ID from natural-language instruction and return its coordinates.

    Matches patterns like 'B-03', 'bay B-03', 'dock B-01', 'shelf S-02', 'R-01'.
    Returns {"x": ..., "y": ...} or None.
    """
    if not bays:
        return None
    bay_map = {b["id"].upper(): b for b in bays if "id" in b}
    # Look for bay IDs in the instruction (e.g. A-04, B-03, S-01, R-02)
    matches = re.findall(r'\b([ABSR]-\d{1,3})\b', instruction.upper())
    for m in matches:
        if m in bay_map:
            b = bay_map[m]
            return {"x": float(b["x"]), "y": float(b["y"])}
    return None


def bay_directory_text(bays: List[Dict[str, Any]]) -> str:
    """Format bay list as a text table for LLM prompts."""
    if not bays:
        return ""
    lines = ["BAY DIRECTORY (use exact coordinates when navigating to a bay):"]
    for b in bays:
        label = f"{b['id']} ({b.get('type', 'bay')})"
        lines.append(f"  {label:20s} → x={b['x']}, y={b['y']}")
    return "\n".join(lines)

# Model cascade: flash first (fastest) → robotics-er → heavier models
MODEL_CASCADE: List[str] = [
    "gemini-2.5-flash",                # Fastest, best quota
    "gemini-2.0-flash",                # Ultra-fast fallback
    "gemini-robotics-er-1.5-preview",  # Robotics-specialized
    "gemini-2.5-flash-lite",           # Lightweight, high quota
    "gemini-3-flash-preview",          # Gemini 3 Flash
    "gemini-3-pro-preview",            # Gemini 3 Pro (slowest)
]

# Shorter cascade for latency-sensitive paths (agentic propose, single-call)
FAST_CASCADE: List[str] = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.5-flash-lite",
]


def _extract_json(text: str) -> Any:
    """Extract the first complete JSON object/array from a string.

    Models often wrap JSON in prose or code fences, or follow it with more text
    or a second object. Decoding from each opening brace in turn returns the
    first value that parses, instead of everything between the first '{' and
    the last '}' (which fails with "Extra data" when two objects appear).
    """
    s = (text or "").strip()
    decoder = json.JSONDecoder()
    first_list = None
    i = 0
    while i < len(s):
        if s[i] in "{[":
            try:
                obj, end = decoder.raw_decode(s, i)
            except json.JSONDecodeError:
                i += 1
                continue
            # Callers expect an object; a list found first is often a fragment
            # (e.g. a waypoint array quoted in reasoning), so keep looking.
            if isinstance(obj, dict):
                return obj
            if first_list is None:
                first_list = obj
            i = end
            continue
        i += 1
    if first_list is not None:
        return first_list
    raise ValueError("No JSON found in model output")


# Shared httpx client — reuse connections across calls
_shared_client: Optional[httpx.AsyncClient] = None


def _get_shared_client(timeout: float) -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _shared_client


class GeminiPlanner:
    """LLM planner with cascading model fallback and concurrent racing."""

    def __init__(self):
        self.api_key = settings.gemini_api_key
        self.primary_model = settings.gemini_model
        self.timeout_s = min(settings.gemini_timeout_s, 6.0)  # Cap at 6s for speed
        self.model_cascade = [self.primary_model] + [
            m for m in MODEL_CASCADE if m != self.primary_model
        ]
        # Deduplicate while preserving order
        seen = set()
        deduped = []
        for m in self.model_cascade:
            if m not in seen:
                seen.add(m)
                deduped.append(m)
        self.model_cascade = deduped
        self._bays: List[Dict[str, Any]] = []

    def set_bays(self, bays: List[Dict[str, Any]]) -> None:
        """Load bay directory for coordinate resolution."""
        self._bays = bays or []

    def _get_cascade(self, preferred_model: Optional[str] = None, fast: bool = False) -> List[str]:
        """Return model cascade. Use fast=True for latency-sensitive paths."""
        base = FAST_CASCADE if fast else self.model_cascade
        if not preferred_model or preferred_model not in MODEL_CASCADE:
            return base
        remaining = [m for m in base if m != preferred_model]
        return [preferred_model] + remaining

    async def _call_gemini(self, model: str, prompt: str) -> Optional[str]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2},
        }
        t0 = _time.monotonic()
        try:
            client = _get_shared_client(self.timeout_s)
            r = await client.post(url, headers=headers, json=payload)
            elapsed = _time.monotonic() - t0
            if r.status_code == 429:
                logger.warning(f"Rate limited on {model} ({elapsed:.1f}s)")
                return None
            if r.status_code >= 400:
                logger.warning(f"Error {r.status_code} on {model} ({elapsed:.1f}s): {r.text[:200]}")
                return None
            data = r.json()
            text = data["candidates"][0]["content"]["parts"][0].get("text", "")
            logger.info(f"Gemini {model} responded in {elapsed:.1f}s")
            return text
        except Exception as e:
            elapsed = _time.monotonic() - t0
            logger.warning(f"Exception calling {model} ({elapsed:.1f}s): {e}")
            return None

    async def _race_models(self, models: List[str], prompt: str) -> tuple[Optional[str], str]:
        """Race multiple models concurrently — return first successful response."""
        if not models:
            return None, "none"

        async def _try(model: str) -> tuple[Optional[str], str]:
            result = await self._call_gemini(model, prompt)
            return result, model

        tasks = [asyncio.create_task(_try(m)) for m in models[:2]]  # Race top 2
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

        # Check if winner succeeded
        for task in done:
            text, model = task.result()
            if text:
                for p in pending:
                    p.cancel()
                return text, model

        # Winner failed — wait for runner-up
        for task in pending:
            try:
                text, model = await task
                if text:
                    return text, model
            except asyncio.CancelledError:
                pass

        # Both failed — try remaining models sequentially
        for model in models[2:]:
            text = await self._call_gemini(model, prompt)
            if text:
                return text, model

        return None, "none"

    # ---- Deterministic fallbacks ----

    def _deterministic_proposal(self, telemetry: Dict[str, Any], goal: Dict[str, float]) -> ActionProposal:
        x, y = float(telemetry.get("x", 0)), float(telemetry.get("y", 0))
        gx, gy = float(goal.get("x", 0)), float(goal.get("y", 0))
        if abs(x - gx) < 0.5 and abs(y - gy) < 0.5:
            return ActionProposal(intent="STOP", params={}, rationale="[Fallback] Reached goal.")
        speed = 0.4 if telemetry.get("human_detected") else 0.6
        return ActionProposal(intent="MOVE_TO", params={"x": gx, "y": gy, "max_speed": speed},
                              rationale="[Fallback] Deterministic path to goal.")

    def _deterministic_plan(self, telemetry: Dict[str, Any], goal: Optional[Dict[str, float]]) -> Dict[str, Any]:
        gx = float(goal.get("x", 15) if goal else 15)
        gy = float(goal.get("y", 10) if goal else 10)
        speed = 0.4 if telemetry.get("human_detected") else 0.6
        return {
            "waypoints": [{"x": gx, "y": gy, "max_speed": speed}],
            "rationale": "[Fallback] Deterministic direct-to-goal plan.",
            "estimated_time_s": 15.0,
            "model_used": "deterministic_fallback",
        }

    async def propose(self, telemetry: Dict[str, Any], goal: Dict[str, float], nl_task: str,
                      last_governance: Optional[Dict[str, Any]] = None,
                      preferred_model: Optional[str] = None) -> ActionProposal:
        if not self.api_key:
            return self._deterministic_proposal(telemetry, goal)

        prompt = f"""You are the high-level reasoning layer for a simulated mobile robot.

TASK: {nl_task}

WORLD STATE: {json.dumps(telemetry, indent=2)}

GOAL: {json.dumps(goal)}

Output STRICT JSON: {{"intent":"MOVE_TO|STOP|WAIT","params":{{...}},"rationale":"..."}}
"""
        cascade = self._get_cascade(preferred_model, fast=True)
        text, model = await self._race_models(cascade, prompt)
        if text:
            try:
                obj = _extract_json(text)
                proposal = ActionProposal(**obj)
                if proposal.intent == "MOVE_TO":
                    p = proposal.params or {}
                    p["x"] = float(p.get("x", goal.get("x", 0)))
                    p["y"] = float(p.get("y", goal.get("y", 0)))
                    p["max_speed"] = max(0.1, min(1.0, float(p.get("max_speed", 0.5))))
                    proposal.params = p
                proposal.rationale = f"[{model}] {proposal.rationale}"
                return proposal
            except Exception as e:
                logger.warning(f"Parse failed {model}: {e}")
        return self._deterministic_proposal(telemetry, goal)

    async def generate_plan(self, telemetry: Dict[str, Any], instruction: str,
                            goal: Optional[Dict[str, float]] = None,
                            preferred_model: Optional[str] = None,
                            lessons: Optional[List[Dict[str, Any]]] = None,
                            untrusted_context: str = "") -> Dict[str, Any]:
        """Multi-waypoint plan. `lessons` = advisory context from planner_lessons
        (learned from past gate decisions); their IDs are returned as lessons_applied.
        `untrusted_context` = fenced, firewall-screened outside information (reference only)."""
        lesson_ids = [l["id"] for l in (lessons or [])]
        if not self.api_key:
            plan = self._deterministic_plan(telemetry, goal)
            plan["lessons_applied"] = []
            return plan
        from app.services.planner_lessons import format_for_prompt
        lessons_text = format_for_prompt(lessons or [])

        goal_text = f"GOAL: {json.dumps(goal)}" if goal else "No specific goal."
        bays_text = bay_directory_text(self._bays) if self._bays else ""
        prompt = f"""You are a robot planner in a 40x25m warehouse.

INSTRUCTION: {instruction}

STATE: {json.dumps(telemetry, indent=2)}

{goal_text}

{bays_text}

{lessons_text}

{untrusted_context}

IMPORTANT: When the instruction mentions a bay ID (e.g. B-03, S-01, R-02), use the EXACT coordinates from the Bay Directory above. Do NOT guess bay positions.

Output STRICT JSON:
{{"waypoints": [{{"x": <float>, "y": <float>, "max_speed": <float>}}, ...], "rationale": "...", "estimated_time_s": <float>}}
"""
        cascade = self._get_cascade(preferred_model, fast=True)
        text, model = await self._race_models(cascade, prompt)
        if text:
            try:
                obj = _extract_json(text)
                waypoints = obj.get("waypoints", [])
                for wp in waypoints:
                    wp["x"] = max(_WM_GEOFENCE["min_x"], min(_WM_GEOFENCE["max_x"], float(wp.get("x", 0))))
                    wp["y"] = max(_WM_GEOFENCE["min_y"], min(_WM_GEOFENCE["max_y"], float(wp.get("y", 0))))
                    wp["max_speed"] = max(0.1, min(1.0, float(wp.get("max_speed", 0.5))))
                # Ensure last waypoint matches the goal (snap to bay coords)
                if goal and waypoints:
                    gx, gy = float(goal.get("x", 0)), float(goal.get("y", 0))
                    last = waypoints[-1]
                    if abs(last["x"] - gx) > 1.0 or abs(last["y"] - gy) > 1.0:
                        waypoints.append({"x": gx, "y": gy, "max_speed": last["max_speed"]})
                elif goal and not waypoints:
                    gx, gy = float(goal.get("x", 0)), float(goal.get("y", 0))
                    waypoints = [{"x": gx, "y": gy, "max_speed": 0.4}]
                return {
                    "waypoints": waypoints,
                    "rationale": f"[{model}] {obj.get('rationale', '')}",
                    "estimated_time_s": float(obj.get("estimated_time_s", 0)),
                    "model_used": model,
                    "lessons_applied": lesson_ids,
                }
            except Exception as e:
                logger.warning(f"Plan parse failed {model}: {e}")
        plan = self._deterministic_plan(telemetry, goal)
        plan["lessons_applied"] = []
        return plan

    # ---- Deterministic analysis fallbacks ----

    def _deterministic_analysis(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Rule-based telemetry analysis when LLM is unavailable."""
        denials = [e for e in events if e.get("type") == "DECISION" and
                   e.get("payload", {}).get("decision") == "DENIED"]
        alerts = [e for e in events if e.get("type") == "ALERT"]
        high_risk = [e for e in events if e.get("type") == "DECISION" and
                     float(e.get("payload", {}).get("risk_score", 0)) > 0.7]
        findings = []
        if denials:
            findings.append(f"{len(denials)} governance denial(s) detected.")
        if alerts:
            findings.append(f"{len(alerts)} alert(s) raised during mission.")
        if high_risk:
            findings.append(f"{len(high_risk)} high-risk decision(s) (risk > 0.7).")
        if not findings:
            findings.append("No anomalies detected. Mission telemetry looks nominal.")
        recommendations = []
        if denials:
            recommendations.append("Review denied waypoints and consider safer routing.")
        if high_risk:
            recommendations.append("Lower speeds in high-risk zones or add waypoint buffers.")
        if not recommendations:
            recommendations.append("Continue current operational pattern.")
        return {
            "findings": findings,
            "risk_summary": {"total_events": len(events), "denials": len(denials),
                             "alerts": len(alerts), "high_risk_decisions": len(high_risk)},
            "recommendations": recommendations,
            "model_used": "deterministic_fallback",
        }

    def _deterministic_scene(self, scene_description: str) -> Dict[str, Any]:
        """Rule-based scene analysis when LLM is unavailable."""
        desc_lower = scene_description.lower()
        hazards = []
        risk = 0.2
        if any(w in desc_lower for w in ["human", "person", "worker", "people"]):
            hazards.append({"type": "HUMAN", "severity": "HIGH", "description": "Human presence detected in scene"})
            risk = max(risk, 0.8)
        if any(w in desc_lower for w in ["obstacle", "box", "crate", "pallet", "block"]):
            hazards.append({"type": "OBSTACLE", "severity": "MEDIUM", "description": "Physical obstacle in path"})
            risk = max(risk, 0.5)
        if any(w in desc_lower for w in ["spill", "wet", "slippery"]):
            hazards.append({"type": "FLOOR_HAZARD", "severity": "MEDIUM", "description": "Floor hazard detected"})
            risk = max(risk, 0.6)
        if not hazards:
            hazards.append({"type": "NONE", "severity": "LOW", "description": "No hazards detected"})
        return {
            "hazards": hazards, "risk_score": risk,
            "recommended_action": "STOP" if risk > 0.7 else "SLOW" if risk > 0.4 else "PROCEED",
            "reasoning": f"[Fallback] Keyword-based scene analysis. {len(hazards)} hazard(s) found.",
            "model_used": "deterministic_fallback",
        }

    def _deterministic_failure(self, events: List[Dict[str, Any]], telemetry: Dict[str, Any]) -> Dict[str, Any]:
        """Rule-based failure detection when LLM is unavailable."""
        failures = []
        denials = [e for e in events if e.get("type") == "DECISION" and
                   e.get("payload", {}).get("decision") == "DENIED"]
        if len(denials) >= 3:
            failures.append({"type": "REPEATED_DENIALS", "severity": "HIGH",
                             "description": f"{len(denials)} governance denials — robot may be stuck in a denied loop.",
                             "mitigation": "Re-plan route to avoid policy-violating zones."})
        telem_events = [e for e in events if e.get("type") == "TELEMETRY"]
        if len(telem_events) >= 5:
            recent = telem_events[-5:]
            positions = [(e.get("payload", {}).get("x", 0), e.get("payload", {}).get("y", 0)) for e in recent]
            dx = max(p[0] for p in positions) - min(p[0] for p in positions)
            dy = max(p[1] for p in positions) - min(p[1] for p in positions)
            if dx < 0.3 and dy < 0.3:
                failures.append({"type": "STUCK_ROBOT", "severity": "HIGH",
                                 "description": "Robot position has barely changed over recent telemetry samples.",
                                 "mitigation": "Issue a new plan or manually reposition."})
        if not failures:
            failures.append({"type": "NONE", "severity": "LOW",
                             "description": "No failure patterns detected.", "mitigation": "Continue normal operations."})
        return {
            "failures": failures, "total_events_analyzed": len(events),
            "health_status": "CRITICAL" if any(f["severity"] == "HIGH" for f in failures) else "OK",
            "model_used": "deterministic_fallback",
        }

    # ---- NEW: Telemetry log analysis ----

    async def analyze_telemetry(self, events: List[Dict[str, Any]],
                                 question: Optional[str] = None,
                                 preferred_model: Optional[str] = None) -> Dict[str, Any]:
        """Analyze mission telemetry logs for anomalies, patterns, and safety insights."""
        if not self.api_key:
            return self._deterministic_analysis(events)
        summary_events = events[-50:]
        event_summary = json.dumps(summary_events, indent=1, default=str)
        user_q = f"\nOPERATOR QUESTION: {question}" if question else ""
        prompt = f"""You are an AI safety analyst for an autonomous warehouse robot.

Analyze the following mission event log for:
1. Anomalies or unusual patterns
2. Repeated governance denials (and why)
3. Safety near-misses
4. Efficiency issues (unnecessary stops, oscillation)
5. Compliance risks (ISO 42001 / EU AI Act concerns)
{user_q}

EVENT LOG ({len(summary_events)} most recent of {len(events)} total):
{event_summary}

Output STRICT JSON:
{{
  "findings": ["<finding 1>", "<finding 2>"],
  "risk_summary": {{"total_events": <int>, "denials": <int>, "alerts": <int>, "high_risk_decisions": <int>}},
  "recommendations": ["<rec 1>", "<rec 2>"],
  "compliance_notes": ["<note 1>"]
}}
"""
        cascade = self._get_cascade(preferred_model, fast=True)
        text, model = await self._race_models(cascade, prompt)
        if text:
            try:
                obj = _extract_json(text)
                obj["model_used"] = model
                return obj
            except Exception as e:
                logger.warning(f"Analysis parse failed {model}: {e}")
        return self._deterministic_analysis(events)

    # ---- NEW: Multimodal scene analysis ----

    async def analyze_scene(self, scene_description: str,
                            telemetry: Optional[Dict[str, Any]] = None,
                            preferred_model: Optional[str] = None) -> Dict[str, Any]:
        """Analyze a scene (camera description or sensor data) for hazards."""
        if not self.api_key:
            return self._deterministic_scene(scene_description)
        telem_ctx = f"\nCURRENT TELEMETRY: {json.dumps(telemetry, indent=1)}" if telemetry else ""
        prompt = f"""You are a computer vision safety module for a warehouse robot.

Analyze the following scene description (simulating camera input) and identify:
1. Hazards (humans, obstacles, spills, restricted zones)
2. Risk level (0.0 - 1.0)
3. Recommended robot action (PROCEED / SLOW / STOP / REPLAN)

SCENE DESCRIPTION:
{scene_description}
{telem_ctx}

Output STRICT JSON:
{{
  "hazards": [{{"type": "<HUMAN|OBSTACLE|FLOOR_HAZARD|RESTRICTED_ZONE|OTHER>", "severity": "<LOW|MEDIUM|HIGH>", "description": "...", "estimated_distance_m": null}}],
  "risk_score": <float 0-1>,
  "recommended_action": "<PROCEED|SLOW|STOP|REPLAN>",
  "reasoning": "..."
}}
"""
        cascade = self._get_cascade(preferred_model, fast=True)
        text, model = await self._race_models(cascade, prompt)
        if text:
            try:
                obj = _extract_json(text)
                obj["model_used"] = model
                return obj
            except Exception as e:
                logger.warning(f"Scene parse failed {model}: {e}")
        return self._deterministic_scene(scene_description)

    # ---- NEW: Failure detection & adaptation ----

    async def detect_failures(self, events: List[Dict[str, Any]],
                               telemetry: Dict[str, Any],
                               preferred_model: Optional[str] = None) -> Dict[str, Any]:
        """Detect failure patterns: stuck robots, oscillating behavior, repeated policy conflicts."""
        if not self.api_key:
            return self._deterministic_failure(events, telemetry)
        summary_events = events[-30:]
        event_summary = json.dumps(summary_events, indent=1, default=str)
        prompt = f"""You are a failure-analysis AI for an autonomous warehouse robot.

Given the event history and current telemetry, detect:
1. Stuck robot (position not changing)
2. Oscillating behavior (moving back and forth)
3. Repeated policy denials (same policy triggered multiple times)
4. Sensor anomalies (unusual readings)
5. Goal unreachability (robot cannot reach target)

CURRENT TELEMETRY: {json.dumps(telemetry, indent=1)}

EVENT HISTORY ({len(summary_events)} recent of {len(events)} total):
{event_summary}

Output STRICT JSON:
{{
  "failures": [{{"type": "<STUCK_ROBOT|OSCILLATION|REPEATED_DENIALS|SENSOR_ANOMALY|GOAL_UNREACHABLE|NONE>", "severity": "<LOW|MEDIUM|HIGH>", "description": "...", "mitigation": "..."}}],
  "total_events_analyzed": <int>,
  "health_status": "<OK|WARNING|CRITICAL>"
}}
"""
        cascade = self._get_cascade(preferred_model, fast=True)
        text, model = await self._race_models(cascade, prompt)
        if text:
            try:
                obj = _extract_json(text)
                obj["model_used"] = model
                return obj
            except Exception as e:
                logger.warning(f"Failure parse failed {model}: {e}")
        return self._deterministic_failure(events, telemetry)
