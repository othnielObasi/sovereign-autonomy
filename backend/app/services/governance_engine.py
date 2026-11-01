from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.schemas.governance import ActionProposal, GovernanceDecision
from app.policies.rules_python import evaluate_policies
from app.db.models import GovernanceDecisionRecord, CircuitBreakerState
from app.utils.time import utc_now
from app.policies.params import active_params, params_hash
from app.policies.versioning import policy_version_hash  # noqa: F401  (re-exported; tests and callers use it)
from app.utils import signing

logger = logging.getLogger("app.governance")

# Escalation: consecutive denials before auto-escalation
CONSECUTIVE_DENIAL_ESCALATION = 3


class GovernanceEngine:
    """Runtime governance engine — evaluates, persists, and tracks decisions.

    Responsibilities:
    - Evaluate proposals against all active policies
    - Persist every decision to governance_decisions table
    - Track consecutive denials per run for circuit-breaker escalation
    - Provide queryable decision history
    """

    def __init__(self):
        self._consecutive_denials: Dict[str, int] = {}  # in-memory cache

    def _get_circuit_breaker(self, db: Session, run_id: str) -> int:
        """Get consecutive denial count — DB-backed with in-memory cache."""
        if run_id in self._consecutive_denials:
            return self._consecutive_denials[run_id]
        row = db.query(CircuitBreakerState).filter(
            CircuitBreakerState.run_id == run_id
        ).first()
        count = row.consecutive_denials if row else 0
        self._consecutive_denials[run_id] = count
        return count

    def _set_circuit_breaker(self, db: Session, run_id: str, count: int) -> None:
        """Persist consecutive denial count to DB and cache."""
        self._consecutive_denials[run_id] = count
        row = db.query(CircuitBreakerState).filter(
            CircuitBreakerState.run_id == run_id
        ).first()
        if row:
            row.consecutive_denials = count
            row.escalated = "true" if count >= CONSECUTIVE_DENIAL_ESCALATION else row.escalated
            row.last_updated = utc_now()
        else:
            row = CircuitBreakerState(
                run_id=run_id,
                consecutive_denials=count,
                escalated="false",
                last_updated=utc_now(),
            )
            db.add(row)
            # SessionLocal does not autoflush: without this, a second decision for the same
            # run before the next commit inserts a duplicate row and fails the unique index.
            db.flush()

    def evaluate(self, telemetry: Dict[str, Any], proposal: ActionProposal) -> GovernanceDecision:
        """Evaluate a proposal against policies. Stateless — does not persist."""
        return evaluate_policies(telemetry, proposal)

    def evaluate_and_record(
        self,
        db: Session,
        run_id: str,
        telemetry: Dict[str, Any],
        proposal: ActionProposal,
        was_executed: bool = False,
        event_hash: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> GovernanceDecision:
        """Evaluate a proposal, persist the decision, and handle escalation logic.

        `params` overrides the active rules (used by the benchmark to test a candidate
        rule set); live runs always use the active rules."""
        # Pin the rules for this decision so the recorded version is exactly what was enforced
        params = params if params is not None else active_params()
        decision = evaluate_policies(telemetry, proposal, params)

        # Circuit-breaker: track consecutive denials (persistent)
        escalated = False
        if decision.decision in ("DENIED", "NEEDS_REVIEW"):
            prev_count = self._get_circuit_breaker(db, run_id)
            new_count = prev_count + 1
            self._set_circuit_breaker(db, run_id, new_count)
            if new_count >= CONSECUTIVE_DENIAL_ESCALATION:
                escalated = True
                if "CIRCUIT_BREAKER" not in decision.reasons:
                    decision.reasons.append(
                        f"Circuit breaker: {new_count} consecutive denials — operator escalation required"
                    )
                if decision.decision == "DENIED":
                    decision.decision = "NEEDS_REVIEW"
                logger.warning(
                    "Run %s: circuit breaker triggered after %d consecutive denials",
                    run_id, new_count,
                )
        else:
            self._set_circuit_breaker(db, run_id, 0)

        # Build compact telemetry summary for storage
        tel_summary = {
            "x": round(float(telemetry.get("x", 0)), 2),
            "y": round(float(telemetry.get("y", 0)), 2),
            "speed": round(float(telemetry.get("speed", 0)), 3),
            "zone": telemetry.get("zone", "unknown"),
            "human_detected": bool(telemetry.get("human_detected", False)),
            "human_distance_m": round(float(telemetry.get("human_distance_m", 999)), 2),
            "nearest_obstacle_m": round(float(telemetry.get("nearest_obstacle_m", 999)), 2),
            # Kept so a decision can be replayed exactly under candidate rules
            "human_conf": round(float(telemetry.get("human_conf", 0.0)), 3),
            "walking_humans": [
                {"x": round(float(w.get("x", 0)), 2), "y": round(float(w.get("y", 0)), 2),
                 "conf": round(float(w.get("conf", 0.9)), 3)}
                for w in (telemetry.get("walking_humans") or [])[:10]
                if isinstance(w, dict)
            ],
        }
        if telemetry.get("site_constraints"):
            # Hazard zones in force for this decision (geometry and limits only)
            tel_summary["site_constraints"] = [
                {k: (round(float(z[k]), 3) if k in ("x", "y", "radius", "slow_radius", "max_speed") else z[k])
                 for k in ("id", "x", "y", "radius", "slow_radius", "max_speed", "label") if k in z}
                for z in (telemetry.get("site_constraints") or [])[:10] if isinstance(z, dict)
            ]

        # Persist decision record
        ts = utc_now()
        record = GovernanceDecisionRecord(
            run_id=run_id,
            ts=ts,
            decision=decision.decision,
            policy_state=decision.policy_state,
            risk_score=decision.risk_score,
            policy_hits=json.dumps(decision.policy_hits),
            reasons=json.dumps(decision.reasons),
            required_action=decision.required_action,
            proposal_intent=proposal.intent,
            proposal_json=json.dumps(proposal.model_dump()),
            telemetry_summary=json.dumps(tel_summary),
            was_executed="true" if was_executed else "false",
            event_hash=event_hash,
            escalated="true" if escalated else "false",
            policy_version=params_hash(params),
        )
        try:
            record.signature, record.signing_key_id = signing.sign(self.signing_payload(record))
        except Exception as e:  # signing must never block the safety decision itself
            logger.error("Receipt signing failed for run %s: %s", run_id, e)
        db.add(record)

        return decision

    @staticmethod
    def signing_payload(record: GovernanceDecisionRecord) -> Dict[str, Any]:
        """The decision content covered by the signature: what was proposed, what the
        gate saw, under which rules, and what it decided. `was_executed` and
        `event_hash` are set after the decision and are covered by the hash chain instead."""
        return {
            "run_id": record.run_id,
            "ts": signing.canonical_ts(record.ts),
            "decision": record.decision,
            "policy_state": record.policy_state,
            "risk_score": record.risk_score,
            "policy_hits": json.loads(record.policy_hits or "[]"),
            "reasons": json.loads(record.reasons or "[]"),
            "required_action": record.required_action,
            "proposal_intent": record.proposal_intent,
            "proposal": json.loads(record.proposal_json or "{}"),
            "telemetry": json.loads(record.telemetry_summary or "{}"),
            "escalated": record.escalated,
            "policy_version": record.policy_version,
        }

    def verify_receipt(self, db: Session, run_id: str, decision_id: int) -> Optional[Dict[str, Any]]:
        record = (
            db.query(GovernanceDecisionRecord)
            .filter(GovernanceDecisionRecord.run_id == run_id, GovernanceDecisionRecord.id == decision_id)
            .first()
        )
        if not record:
            return None
        if not record.signature:
            return {"receipt_id": record.id, "signed": False, "valid": False,
                    "reason": "decision recorded before receipt signing was enabled"}
        result = signing.verify(self.signing_payload(record), record.signature, record.signing_key_id or "")
        return {"receipt_id": record.id, "signed": True, "key_id": record.signing_key_id,
                "algorithm": signing.SIGNATURE_ALG, **result}

    def get_decisions(
        self,
        db: Session,
        run_id: str,
        decision_filter: Optional[str] = None,
        policy_state_filter: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Query governance decision history for a run."""
        q = db.query(GovernanceDecisionRecord).filter(
            GovernanceDecisionRecord.run_id == run_id
        )
        if decision_filter:
            q = q.filter(GovernanceDecisionRecord.decision == decision_filter)
        if policy_state_filter:
            q = q.filter(GovernanceDecisionRecord.policy_state == policy_state_filter)

        rows = q.order_by(GovernanceDecisionRecord.ts.desc()).offset(offset).limit(limit).all()
        return [self._decision_to_dict(r) for r in rows]

    def get_decision_stats(self, db: Session, run_id: str) -> Dict[str, Any]:
        """Aggregate statistics for governance decisions in a run."""
        rows = db.query(GovernanceDecisionRecord).filter(
            GovernanceDecisionRecord.run_id == run_id
        ).all()

        if not rows:
            return {"total": 0, "approved": 0, "denied": 0, "needs_review": 0,
                    "escalated": 0, "avg_risk_score": 0.0, "max_risk_score": 0.0,
                    "policy_hit_counts": {}, "policy_state_counts": {}}

        total = len(rows)
        approved = sum(1 for r in rows if r.decision == "APPROVED")
        denied = sum(1 for r in rows if r.decision == "DENIED")
        needs_review = sum(1 for r in rows if r.decision == "NEEDS_REVIEW")
        escalated_count = sum(1 for r in rows if r.escalated == "true")
        risk_scores = [r.risk_score for r in rows]

        # Count policy hits
        policy_counts: Dict[str, int] = {}
        for r in rows:
            for pid in json.loads(r.policy_hits or "[]"):
                policy_counts[pid] = policy_counts.get(pid, 0) + 1

        # Count policy states
        state_counts: Dict[str, int] = {}
        for r in rows:
            state_counts[r.policy_state] = state_counts.get(r.policy_state, 0) + 1

        return {
            "total": total,
            "approved": approved,
            "denied": denied,
            "needs_review": needs_review,
            "escalated": escalated_count,
            "approval_rate": round(approved / total, 3) if total else 0,
            "avg_risk_score": round(sum(risk_scores) / total, 3) if total else 0,
            "max_risk_score": round(max(risk_scores), 3) if risk_scores else 0,
            "policy_hit_counts": policy_counts,
            "policy_state_counts": state_counts,
        }

    def get_receipt(self, db: Session, run_id: str, decision_id: int) -> Optional[Dict[str, Any]]:
        """Get a single governance receipt — structured proof of a decision."""
        record = db.query(GovernanceDecisionRecord).filter(
            GovernanceDecisionRecord.id == decision_id,
            GovernanceDecisionRecord.run_id == run_id,
        ).first()
        if not record:
            return None
        return self._decision_to_receipt(record)

    def get_receipts(self, db: Session, run_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get all governance receipts for a run (structured decision proofs)."""
        rows = db.query(GovernanceDecisionRecord).filter(
            GovernanceDecisionRecord.run_id == run_id
        ).order_by(GovernanceDecisionRecord.ts.asc()).limit(limit).all()
        return [self._decision_to_receipt(r) for r in rows]

    @staticmethod
    def _decision_to_dict(record: GovernanceDecisionRecord) -> Dict[str, Any]:
        return {
            "id": record.id,
            "run_id": record.run_id,
            "ts": record.ts.isoformat() if record.ts else None,
            "decision": record.decision,
            "policy_state": record.policy_state,
            "risk_score": record.risk_score,
            "policy_hits": json.loads(record.policy_hits or "[]"),
            "reasons": json.loads(record.reasons or "[]"),
            "required_action": record.required_action,
            "proposal_intent": record.proposal_intent,
            "was_executed": record.was_executed == "true",
            "escalated": record.escalated == "true",
            "event_hash": record.event_hash,
        }

    @staticmethod
    def _decision_to_receipt(record: GovernanceDecisionRecord) -> Dict[str, Any]:
        """A governance receipt is structured proof of why an action was allowed or blocked."""
        policy_hits = json.loads(record.policy_hits or "[]")
        reasons = json.loads(record.reasons or "[]")
        proposal = json.loads(record.proposal_json or "{}")
        telemetry = json.loads(record.telemetry_summary or "{}")

        return {
            "receipt_id": record.id,
            "run_id": record.run_id,
            "timestamp": record.ts.isoformat() if record.ts else None,
            "verdict": {
                "decision": record.decision,
                "policy_state": record.policy_state,
                "risk_score": record.risk_score,
                "was_executed": record.was_executed == "true",
                "escalated": record.escalated == "true",
            },
            "proposal": {
                "intent": record.proposal_intent,
                "params": proposal.get("params", {}),
                "rationale": proposal.get("rationale", ""),
            },
            "policy_evaluation": {
                "policies_triggered": policy_hits,
                "reasons": reasons,
                "required_action": record.required_action,
            },
            "context": {
                "telemetry_snapshot": telemetry,
            },
            "integrity": {
                "event_hash": record.event_hash,
                "policy_version": record.policy_version,
                "signature": record.signature,
                "signing_key_id": record.signing_key_id,
                "signature_algorithm": "Ed25519" if record.signature else None,
            },
        }
