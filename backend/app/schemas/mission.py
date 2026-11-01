from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List
import datetime as dt


class MissionCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    # Either a bay identifier (preferred) or explicit goal coordinates
    bay_id: Optional[str] = Field(None, description="Optional bay identifier (e.g. B-03)")
    goal: Optional[Dict[str, Any]] = Field(None, description="Goal object, e.g. {'x': 15, 'y': 7}")


class MissionUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    bay_id: Optional[str] = Field(None, description="Optional bay identifier (e.g. B-03)")
    goal: Optional[Dict[str, Any]] = None


class MissionOut(BaseModel):
    id: str
    title: str
    goal: Dict[str, Any]
    status: str = "draft"
    created_at: dt.datetime
    updated_at: Optional[dt.datetime] = None


class MissionAuditOut(BaseModel):
    id: int
    mission_id: str
    ts: dt.datetime
    action: str
    actor: Optional[str] = "system"
    old_values: Optional[Dict[str, Any]] = None
    new_values: Optional[Dict[str, Any]] = None
    details: Optional[str] = None
