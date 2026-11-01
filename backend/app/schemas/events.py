from __future__ import annotations

from pydantic import BaseModel
from typing import Any, Dict, Optional
import datetime as dt


class EventOut(BaseModel):
    id: str
    run_id: str
    ts: dt.datetime
    type: str
    payload: Dict[str, Any]
    hash: str
    prev_hash: str = "0" * 64


class WsMessage(BaseModel):
    kind: str  # telemetry|event|alert|status
    data: Dict[str, Any]
