from __future__ import annotations

import json
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session

from app.db.models import TelemetrySample
from app.utils.time import utc_now


class TelemetryService:
    """Stores telemetry samples for later replay/debug.

    Note: For very high rates you'd store to object storage; Postgres/SQLite is OK for MVP.
    """

    def add_sample(self, db: Session, run_id: str, telemetry: Dict[str, Any]) -> None:
        sample = TelemetrySample(
            run_id=run_id,
            ts=utc_now(),
            payload_json=json.dumps(telemetry, ensure_ascii=False),
        )
        db.add(sample)
