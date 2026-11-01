from __future__ import annotations

"""Operator approval service — human-in-the-loop governance overrides.

When the governance engine escalates a decision to NEEDS_REVIEW, the operator
must explicitly approve the proposal before execution can proceed.  Approvals
are recorded per (run_id, proposal_hash) and are checked by the run loop.

Note: Each function creates its own DB session (rather than accepting one as
a parameter) because approvals may be issued from HTTP endpoints that run
outside the run loop’s session scope.
"""

from typing import Dict, Any
from datetime import datetime, timezone

from app.db.session import SessionLocal
from app.db.models import OperatorApproval


def approve(run_id: str, proposal_hash: str, approved_by: str | None = None, notes: str | None = None) -> None:
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
    """Check whether a proposal has been approved by an operator."""
    db = SessionLocal()
    try:
        cnt = db.query(OperatorApproval).filter(
            OperatorApproval.run_id == run_id,
            OperatorApproval.proposal_hash == proposal_hash,
        ).count()
        return cnt > 0
    finally:
        db.close()


def list_for_run(run_id: str) -> Dict[str, Any]:
    """Return all approvals for a run, keyed by proposal_hash."""
    db = SessionLocal()
    try:
        rows = db.query(OperatorApproval).filter(OperatorApproval.run_id == run_id).all()
        return {r.proposal_hash: {"approved_by": r.approved_by, "approved_at": r.approved_at.isoformat(), "notes": r.notes} for r in rows}
    finally:
        db.close()
