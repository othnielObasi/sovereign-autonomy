"""Read-only run milestones and latest execution outcome, independent of UI windows."""
import json
from app.db.models import Event, Run


def run_presentation(db, run_id):
    run = db.get(Run, run_id)
    if run is None:
        return None
    query = db.query(Event).filter(Event.run_id == run_id)
    def latest(kind):
        row = query.filter(Event.type == kind).order_by(Event.ts.desc()).first()
        return None if row is None else dict(id=row.id, ts=row.ts.isoformat(), type=row.type,
                                            payload=json.loads(row.payload_json))
    plan, decision, authority, execution = [latest(k) for k in ('PLAN', 'DECISION', 'AUTHORITY', 'EXECUTION')]
    candidates = query.filter(Event.type == 'AUTHORITY', Event.payload_json.contains('"permit_used"')).order_by(Event.ts.asc())
    admitted = next((row for row in candidates.yield_per(100) if json.loads(row.payload_json).get('event') == 'permit_used'), None)
    return dict(run_id=run_id, status=run.status, plan=plan, decision=decision,
                authority=authority, execution=execution,
                first_admission=None if admitted is None else dict(id=admitted.id, ts=admitted.ts.isoformat()),
                scope='Stored milestones and latest recorded outcome; movement requires fresh telemetry')
