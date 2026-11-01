from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Any, Dict, List, Literal, Optional


Decision = Literal["APPROVED", "DENIED", "NEEDS_REVIEW"]


class ActionProposal(BaseModel):
    intent: Literal["MOVE_TO", "STOP", "WAIT"] = "MOVE_TO"
    params: Dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""


class GovernanceDecision(BaseModel):
    decision: Decision
    policy_hits: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)
    required_action: Optional[str] = None
    risk_score: float = 0.0
    policy_state: Literal["SAFE", "SLOW", "STOP", "REPLAN"] = "SAFE"
    hard_fail: bool = False
    hard_fail_policies: List[str] = Field(default_factory=list)


class PolicyInfo(BaseModel):
    policy_id: str
    name: str
    description: str
    severity: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    parameters: Optional[Dict[str, Any]] = None
    trigger: Optional[str] = None
    action: Optional[str] = None


class GovernanceDecisionOut(BaseModel):
    """Response model for governance decision history queries."""
    id: int
    run_id: str
    ts: Optional[str] = None
    decision: str
    policy_state: str
    risk_score: float
    policy_hits: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)
    required_action: Optional[str] = None
    proposal_intent: str
    was_executed: bool = False
    escalated: bool = False
    event_hash: Optional[str] = None


class GovernanceReceiptOut(BaseModel):
    """Structured proof of why an action was allowed or blocked."""
    receipt_id: int
    run_id: str
    timestamp: Optional[str] = None
    verdict: Dict[str, Any]
    proposal: Dict[str, Any]
    policy_evaluation: Dict[str, Any]
    context: Dict[str, Any]
    integrity: Dict[str, Any]


class GovernanceStatsOut(BaseModel):
    """Aggregate governance statistics for a run."""
    total: int = 0
    approved: int = 0
    denied: int = 0
    needs_review: int = 0
    escalated: int = 0
    approval_rate: float = 0.0
    avg_risk_score: float = 0.0
    max_risk_score: float = 0.0
    policy_hit_counts: Dict[str, int] = Field(default_factory=dict)
    policy_state_counts: Dict[str, int] = Field(default_factory=dict)
