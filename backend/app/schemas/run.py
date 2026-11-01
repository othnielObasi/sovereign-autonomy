from __future__ import annotations

from pydantic import BaseModel
import datetime as dt
from typing import Optional


class RunOut(BaseModel):
    id: str
    mission_id: str
    status: str
    started_at: dt.datetime
    ended_at: Optional[dt.datetime] = None


class RunStartResponse(BaseModel):
    run_id: str
