"""
Compliance API Routes
Endpoints for generating and exporting compliance reports.
"""

import json
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, Query, HTTPException, Depends
from fastapi.responses import PlainTextResponse, JSONResponse
from sqlalchemy.orm import Session

from app.deps import get_db
from app.db.models import Event, Run
from app.services.compliance_report import compliance_service, ComplianceReport
from app.utils.time import utc_now

router = APIRouter(prefix="/compliance", tags=["compliance"])


def _load_events_from_db(db: Session, run_id: str) -> List[Dict[str, Any]]:
    """Load real events from the database and convert to compliance format."""
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    rows = db.query(Event).filter(Event.run_id == run_id).order_by(Event.ts.asc()).all()
    events: List[Dict[str, Any]] = []
    for row in rows:
        payload = json.loads(row.payload_json)
        gov = payload.get("governance", {})
        proposal = payload.get("proposal", {})
        violations = []
        for hit in gov.get("policy_hits", []):
            violations.append({"policy_id": hit, "severity": "HIGH"})
        events.append({
            "id": row.id,
            "timestamp": row.ts.isoformat() if row.ts else "",
            "action_type": proposal.get("intent", row.type).lower(),
            "approved": gov.get("decision") == "APPROVED",
            "risk_score": gov.get("risk_score", 0.0),
            "violations": violations,
        })
    return events


def _validate_framework(framework: str) -> None:
    valid_frameworks = ["ISO_42001", "EU_AI_ACT", "NIST_AI_RMF"]
    if framework not in valid_frameworks:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid framework. Must be one of: {valid_frameworks}",
        )


@router.get(
    "/report/{run_id}",
    response_model=ComplianceReport,
    summary="Generate a compliance report (JSON)",
)
async def get_compliance_report(
    run_id: str,
    framework: str = Query("ISO_42001", description="Compliance framework"),
    db: Session = Depends(get_db),
) -> ComplianceReport:
    """
    Generate a compliance report for a specific run (JSON).
    """
    _validate_framework(framework)
    events = _load_events_from_db(db, run_id)

    report = compliance_service.generate_report(
        run_id=run_id,
        events=events,
        framework=framework,
    )
    return report


@router.get(
    "/report/{run_id}.txt",
    response_class=PlainTextResponse,
    summary="Generate a compliance report (plain text)",
)
async def get_compliance_report_text(
    run_id: str,
    framework: str = Query("ISO_42001", description="Compliance framework"),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    """
    Generate a compliance report for a specific run (plain text summary).
    """
    _validate_framework(framework)
    events = _load_events_from_db(db, run_id)

    report = compliance_service.generate_report(
        run_id=run_id,
        events=events,
        framework=framework,
    )
    summary = compliance_service.export_summary(report)
    return PlainTextResponse(content=summary)


@router.get("/report/{run_id}/export")
async def export_compliance_report(
    run_id: str,
    framework: str = Query("ISO_42001"),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Export compliance report as downloadable JSON.
    """
    _validate_framework(framework)
    events = _load_events_from_db(db, run_id)

    report = compliance_service.generate_report(
        run_id=run_id,
        events=events,
        framework=framework,
    )

    return JSONResponse(
        content=report.model_dump(),
        headers={
            "Content-Disposition": f"attachment; filename=compliance-report-{run_id}.json"
        },
    )


@router.get("/frameworks")
async def list_frameworks():
    return {
        "frameworks": [
            {
                "id": "ISO_42001",
                "name": "ISO/IEC 42001:2023",
                "description": "AI Management System Standard",
            },
            {
                "id": "EU_AI_ACT",
                "name": "EU AI Act",
                "description": "European Union AI Regulation",
            },
            {
                "id": "NIST_AI_RMF",
                "name": "NIST AI RMF",
                "description": "US AI Risk Management Framework",
            },
        ]
    }


@router.get("/verify/{run_id}")
async def verify_audit_chain(run_id: str, db: Session = Depends(get_db)):
    events = _load_events_from_db(db, run_id)
    report = compliance_service.generate_report(
        run_id=run_id,
        events=events,
    )

    return {
        "run_id": run_id,
        "chain_valid": report.chain_valid,
        "total_entries": len(report.audit_entries),
        "first_hash": report.audit_entries[0].hash[:16] + "..." if report.audit_entries else None,
        "last_hash": report.audit_entries[-1].hash[:16] + "..." if report.audit_entries else None,
        "verified_at": utc_now().isoformat() + "Z",
    }
