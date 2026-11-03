from __future__ import annotations

"""Operator approval service — human-in-the-loop governance overrides.

When the governance engine escalates a decision to NEEDS_REVIEW, the operator
must explicitly approve the proposal before execution can proceed.  Approvals
are recorded per (run_id, proposal_hash) and are checked by the run loop.

Note: Each function creates its own DB session (rather than accepting one as
a parameter) because approvals may be issued from HTTP endpoints that run
outside the run loop’s session scope.
"""

import json
from typing import Dict, Any
from datetime import datetime, timedelta, timezone

from app.db.session import SessionLocal
from app.db.models import OperatorApproval


APPROVAL_TTL_S = 120   # an approval covers a decision made now, not one made later


def approve(run_id: str, proposal_hash: str, approved_by: str | None = None, notes: str | None = None,
            ttl_s: float = APPROVAL_TTL_S) -> None:
    """Record operator approval for a specific governance proposal.

    Args:
        run_id: The run that generated the proposal.
        proposal_hash: SHA-256 hash identifying the proposal being approved.
        approved_by: Optional operator identifier (username or ID).
        notes: Optional free-text justification for the approval.
    """
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        oa = OperatorApproval(
            run_id=run_id,
            proposal_hash=proposal_hash,
            approved_by=approved_by,
            approved_at=now,
            expires_at=now + timedelta(seconds=ttl_s),
            notes=notes,
        )
        db.add(oa)
        db.commit()
    finally:
        db.close()


def revoke(run_id: str, proposal_hash: str) -> None:
    """Remove an existing approval (e.g. operator changed their mind)."""
    db = SessionLocal()
    try:
        db.query(OperatorApproval).filter(
            OperatorApproval.run_id == run_id,
            OperatorApproval.proposal_hash == proposal_hash,
        ).delete()
        db.commit()
    finally:
        db.close()


def is_approved(run_id: str, proposal_hash: str) -> bool:
    """Check whether a proposal has an operator approval that has not expired."""
    db = SessionLocal()
    try:
        rows = db.query(OperatorApproval).filter(
            OperatorApproval.run_id == run_id,
            OperatorApproval.proposal_hash == proposal_hash,
        ).all()
        now = datetime.now(timezone.utc)
        for row in rows:
            exp = row.expires_at
            if exp is None:
                continue   # older rows without an expiry no longer count
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp > now:
                return True
        return False
    finally:
        db.close()


def list_for_run(run_id: str) -> Dict[str, Any]:
    """Return all approvals for a run, keyed by proposal_hash."""
    db = SessionLocal()
    try:
        rows = db.query(OperatorApproval).filter(OperatorApproval.run_id == run_id).all()
        result = {}
        for row in rows:
            notes = row.notes
            try:
                metadata = json.loads(notes or '{}')
                if isinstance(metadata,dict) and metadata.get('schema') == 'operator-review-v1':
                    notes = metadata.get('reason')
            except (ValueError,TypeError):
                pass
            result[row.proposal_hash] = {'approved_by':row.approved_by,
                'approved_at':row.approved_at.isoformat(), 'notes':notes,
                'expires_at':row.expires_at.isoformat() if row.expires_at else None}
        return result
    finally:
        db.close()


# Review is an exception for uncertainty, never permission to break a limit.
REVIEWABLE_POLICIES = frozenset({'UNCERTAINTY_04', 'HITL_05'})


def reviewable(decision) -> bool:
    return (decision.decision == 'NEEDS_REVIEW' and not decision.hard_fail
            and bool(decision.policy_hits)
            and set(decision.policy_hits) <= REVIEWABLE_POLICIES)


def review_key(telemetry, proposal, decision, policy_version):
    from app.autonomy.permit import controller_context
    from app.services.execution_authority import get_authority
    from app.services.environment_lifecycle import constraints_key
    from app.utils.hashing import sha256_canonical
    context = controller_context(telemetry)
    if context is None:
        return None
    return sha256_canonical({'kind': 'operator-review-v1',
        'robot_id': telemetry.get('robot_id'), 'controller': context,
        'authority_epoch': get_authority().kills.epoch,
        'constraints': constraints_key(telemetry), 'policy_version': policy_version,
        'intent': proposal.intent, 'params': proposal.params,
        'policy_hits': sorted(decision.policy_hits)})


def matching_review(db, run_id, telemetry, proposal, decision, policy_version):
    if not reviewable(decision):
        return None
    key = review_key(telemetry, proposal, decision, policy_version)
    if not key:
        return None
    now = datetime.now(timezone.utc)
    rows = db.query(OperatorApproval).filter(OperatorApproval.run_id == run_id,
        OperatorApproval.proposal_hash == key).order_by(OperatorApproval.id.desc()).all()
    for row in rows:
        exp = row.expires_at
        if exp and (exp.replace(tzinfo=timezone.utc) if exp.tzinfo is None else exp) > now:
            try:
                metadata = json.loads(row.notes or '{}')
                from app.utils import signing
                if (isinstance(metadata,dict) and metadata.get('schema') == 'operator-review-v1' and row.approved_by
                        and signing.verify(lease_payload(row, metadata), metadata['signature'], metadata['key_id'])['valid']):
                    return row
            except (ValueError,TypeError,KeyError):
                continue
    return None


def lease_payload(row, metadata):
    from app.utils.signing import canonical_ts
    return {'kind':'operator-review-v1','id':row.id,'run_id':row.run_id,
            'proposal_hash':row.proposal_hash,'approved_by':row.approved_by,
            'approved_at':canonical_ts(row.approved_at),'expires_at':canonical_ts(row.expires_at),
            'decision_event_id':metadata['decision_event_id'],'reason':metadata['reason']}


def seal_review(row, decision_event_id, reason):
    from app.utils import signing
    metadata={'schema':'operator-review-v1','decision_event_id':decision_event_id,'reason':reason}
    metadata['signature'],metadata['key_id']=signing.sign(lease_payload(row,metadata))
    row.notes=json.dumps(metadata)
