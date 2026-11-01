"""
Replay Service
Reconstructs the full timeline of a run for audit / replay / export.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.db.models import Event, Run, TelemetrySample
from app.utils.hashing import sha256_canonical


def get_run_timeline(
    db: Session,
    run_id: str,
    *,
    include_telemetry: bool = False,
) -> Dict[str, Any]:
    """Return a full timeline of a run, suitable for audit replay.

    Returns:
        {
            "run_id": "...",
            "status": "...",
            "started_at": "...",
            "ended_at": "...",
            "events": [ ... ordered by ts ],
            "telemetry": [ ... if requested ],
            "chain_valid": true/false,
        }
    """
    run = db.query(Run).filter(Run.id == run_id).first()
    if run is None:
        return {}

    # Build event list
    event_rows = (
        db.query(Event)
        .filter(Event.run_id == run_id)
        .order_by(Event.ts.asc())
        .all()
    )

    events: List[Dict[str, Any]] = []
    for row in event_rows:
        events.append({
            "id": row.id,
            "ts": row.ts.isoformat(),
            "type": row.type,
            "payload": json.loads(row.payload_json),
            "hash": row.hash,
            "prev_hash": row.prev_hash or "0" * 64,
        })

    # Optionally include raw telemetry samples
    telemetry: List[Dict[str, Any]] = []
    if include_telemetry:
        telem_rows = (
            db.query(TelemetrySample)
            .filter(TelemetrySample.run_id == run_id)
            .order_by(TelemetrySample.ts.asc())
            .all()
        )
        for t in telem_rows:
            telemetry.append({
                "ts": t.ts.isoformat(),
                "payload": json.loads(t.payload_json),
            })

    # Verify chain integrity
    chain_valid = verify_chain(events)

    return {
        "run_id": run.id,
        "mission_id": run.mission_id,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "ended_at": run.ended_at.isoformat() if run.ended_at else None,
        "events": events,
        "telemetry": telemetry if include_telemetry else None,
        "event_count": len(events),
        "chain_valid": chain_valid,
    }


def verify_chain(events: List[Dict[str, Any]]) -> bool:
    """Walk the event list and verify prev_hash linkage.

    Returns True if:
    - The list is empty (vacuously true)
    - The first event's prev_hash is the zero hash
    - Each subsequent event's prev_hash equals the previous event's hash
    """
    if not events:
        return True

    zero_hash = "0" * 64
    if events[0].get("prev_hash", zero_hash) != zero_hash:
        return False

    for i in range(1, len(events)):
        if events[i].get("prev_hash") != events[i - 1].get("hash"):
            return False

    return True


def export_audit_bundle(
    db: Session,
    run_id: str,
) -> Dict[str, Any]:
    """Generate a self-contained audit bundle for regulatory submission.

    The bundle includes the full timeline plus a top-level
    integrity hash so the entire package can be independently verified.
    """
    timeline = get_run_timeline(db, run_id, include_telemetry=True)
    if not timeline:
        return {}

    # Compute a summary hash over all event hashes
    all_hashes = [e["hash"] for e in timeline.get("events", [])]
    bundle_hash = sha256_canonical({"event_hashes": all_hashes, "run_id": run_id})

    return {
        **timeline,
        "bundle_hash": bundle_hash,
        "format_version": "1.0",
    }
