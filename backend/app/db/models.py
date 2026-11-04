from __future__ import annotations

"""SQLAlchemy ORM models — the persistent data model for Sovereign Autonomy.

Key entities:
- **Mission** — a high-level delivery/patrol objective.
- **Run** — a single execution attempt of a mission (many per mission).
- **Event** — hash-chained immutable event log per run (telemetry, decisions, alerts).
- **GovernanceDecisionRecord** — every governance evaluation, queryable for audits.
- **MissionAudit** — immutable changelog for mission mutations.
- **OperatorApproval** — human-in-the-loop approval records.
- **AgentMemoryEntry** — cross-run learning / persistent agent knowledge.
- **PolicyVersion** — immutable snapshots of policy parameters.
- **CircuitBreakerState** — persistent circuit-breaker for repeated denials.
- **TelemetrySample** — raw telemetry snapshots for analytics.
"""

from sqlalchemy import Column, String, DateTime, Text, ForeignKey, Integer, Float, Index
from sqlalchemy.orm import relationship

from app.db.session import Base


class Mission(Base):
    __tablename__ = "missions"

    id = Column(String, primary_key=True, index=True)
    title = Column(String, nullable=False)
    goal_json = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="draft")  # draft|executing|paused|completed|deleted
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=True)

    runs = relationship("Run", back_populates="mission", cascade="all, delete-orphan")
    audit_logs = relationship("MissionAudit", back_populates="mission", cascade="all, delete-orphan")


class MissionAudit(Base):
    """Immutable audit trail for every change to a mission."""
    __tablename__ = "mission_audit"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mission_id = Column(String, ForeignKey("missions.id"), index=True, nullable=False)
    ts = Column(DateTime(timezone=True), nullable=False)
    action = Column(String, nullable=False)  # CREATED|UPDATED|STATUS_CHANGE|DELETED|REPLAYED
    actor = Column(String, nullable=True, default="system")  # user or system
    old_values = Column(Text, nullable=True)  # JSON snapshot of changed fields before
    new_values = Column(Text, nullable=True)  # JSON snapshot of changed fields after
    details = Column(Text, nullable=True)  # human-readable description

    mission = relationship("Mission", back_populates="audit_logs")


class Run(Base):
    __tablename__ = "runs"

    id = Column(String, primary_key=True, index=True)
    mission_id = Column(String, ForeignKey("missions.id"), nullable=False)
    status = Column(String, nullable=False)  # running|paused|stopped|completed|failed
    started_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    policy_version = Column(String, nullable=True)  # hash of policy params at start
    planning_mode = Column(String, nullable=True)  # gemini|agentic|fallback
    safety_verdict = Column(String, nullable=True)  # PASSED|FAILED_SAFETY|PENDING
    safety_report_json = Column(Text, nullable=True)  # JSON post-run safety validation

    mission = relationship("Mission", back_populates="runs")
    events = relationship("Event", back_populates="run", cascade="all, delete-orphan")
    operator_approvals = relationship("OperatorApproval", back_populates="run", cascade="all, delete-orphan")
    governance_decisions = relationship("GovernanceDecisionRecord", back_populates="run", cascade="all, delete-orphan")


class Event(Base):
    __tablename__ = "events"

    id = Column(String, primary_key=True, index=True)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False, index=True)
    ts = Column(DateTime(timezone=True), nullable=False)
    type = Column(String, nullable=False)  # TELEMETRY|DECISION|ALERT|EXECUTION|PLAN|STAGNATION|INTERVENTION
    payload_json = Column(Text, nullable=False)
    hash = Column(String, nullable=False)
    prev_hash = Column(String, nullable=True, default="0" * 64)

    run = relationship("Run", back_populates="events")


class GovernanceDecisionRecord(Base):
    """Persisted record of every governance evaluation — queryable, auditable."""
    __tablename__ = "governance_decisions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, ForeignKey("runs.id"), index=True, nullable=False)
    ts = Column(DateTime(timezone=True), nullable=False)
    decision = Column(String, nullable=False)  # APPROVED|DENIED|NEEDS_REVIEW
    policy_state = Column(String, nullable=False, default="SAFE")  # SAFE|SLOW|STOP|REPLAN
    risk_score = Column(Float, nullable=False, default=0.0)
    policy_hits = Column(Text, nullable=False, default="[]")  # JSON array of policy IDs
    reasons = Column(Text, nullable=False, default="[]")  # JSON array of reason strings
    required_action = Column(Text, nullable=True)
    proposal_intent = Column(String, nullable=False, default="MOVE_TO")
    proposal_json = Column(Text, nullable=False, default="{}")
    telemetry_summary = Column(Text, nullable=True)  # compact telemetry snapshot
    was_executed = Column(String, nullable=False, default="false")  # "true"|"false"
    event_hash = Column(String, nullable=True)  # links to chain-of-trust Event.hash
    escalated = Column(String, nullable=False, default="false")  # "true" if escalated to operator
    policy_version = Column(String, nullable=True)  # SHA256 prefix of active policy params
    signature = Column(Text, nullable=True)  # Ed25519 signature (base64) over the decision content
    signing_key_id = Column(String, nullable=True)  # which deployment key signed it

    run = relationship("Run", back_populates="governance_decisions")

    __table_args__ = (
        Index("ix_gov_decisions_run_ts", "run_id", "ts"),
        Index("ix_gov_decisions_policy_state", "policy_state"),
        Index("ix_gov_decisions_decision", "decision"),
    )


class TelemetrySample(Base):
    __tablename__ = "telemetry_samples"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, ForeignKey("runs.id"), index=True, nullable=False)
    ts = Column(DateTime(timezone=True), nullable=False)
    payload_json = Column(Text, nullable=False)


class OperatorApproval(Base):
    __tablename__ = "operator_approvals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, ForeignKey("runs.id"), index=True, nullable=False)
    proposal_hash = Column(String, index=True, nullable=False)
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)

    run = relationship("Run", back_populates="operator_approvals")


class AgentMemoryEntry(Base):
    """Persistent agent memory — survives across runs and restarts."""
    __tablename__ = "agent_memory"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, index=True, nullable=True)
    category = Column(String, index=True, nullable=False)  # decision|denial|learning|strategy
    ts = Column(DateTime(timezone=True), nullable=False)
    content_json = Column(Text, nullable=False)
    importance = Column(Float, nullable=False, default=0.5)

    __table_args__ = (
        Index("ix_agent_memory_cat_importance", "category", "importance"),
    )


class PolicyVersion(Base):
    """Immutable snapshot of policy parameters at a point in time."""
    __tablename__ = "policy_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    version_hash = Column(String, nullable=False, unique=True, index=True)
    parameters_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    description = Column(Text, nullable=True)


class CircuitBreakerState(Base):
    """Persistent circuit breaker state — survives process restarts."""
    __tablename__ = "circuit_breaker_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, index=True, nullable=False, unique=True)
    consecutive_denials = Column(Integer, nullable=False, default=0)
    escalated = Column(String, nullable=False, default="false")
    last_updated = Column(DateTime(timezone=True), nullable=False)


class PolicyProposal(Base):
    """A proposed change to the gate's thresholds. Never takes effect by itself:
    draft -> evaluated (replay gate) -> approved (named person) -> active,
    or rejected / superseded."""
    __tablename__ = "policy_proposals"

    id = Column(String, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    created_by = Column(String, nullable=False)
    source = Column(String, nullable=False, default="manual")  # manual|tuning
    description = Column(Text, nullable=True)
    base_version = Column(String, nullable=False)
    changes_json = Column(Text, nullable=False)          # [{"path","from","to","direction"}]
    candidate_params_json = Column(Text, nullable=False)
    candidate_version = Column(String, nullable=False)
    status = Column(String, nullable=False, default="draft", index=True)
    evaluation_json = Column(Text, nullable=True)
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    approval_note = Column(Text, nullable=True)
    activated_at = Column(DateTime(timezone=True), nullable=True)
    rejected_reason = Column(Text, nullable=True)


class PolicyActivation(Base):
    """Append-only log of which parameter set the gate enforces. The latest row is active;
    a rollback is a new row restoring earlier parameters."""
    __tablename__ = "policy_activations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    version_hash = Column(String, nullable=False, index=True)
    parameters_json = Column(Text, nullable=False)
    activated_at = Column(DateTime(timezone=True), nullable=False)
    activated_by = Column(String, nullable=False)
    proposal_id = Column(String, nullable=True)
    previous_version = Column(String, nullable=True)
    reason = Column(Text, nullable=True)


class PilotRequest(Base):
    """A pilot enquiry from the public site. Contact details are kept for follow-up only."""
    __tablename__ = "pilot_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    reference = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    organisation = Column(String, nullable=False)
    role = Column(String, nullable=True)
    site_type = Column(String, nullable=False)
    fleet_size = Column(String, nullable=True)
    message = Column(Text, nullable=True)
    source_hash = Column(String, nullable=True)   # salted hash of the sender's address, for abuse limits only
