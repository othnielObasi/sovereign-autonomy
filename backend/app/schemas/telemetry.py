from __future__ import annotations

from pydantic import BaseModel
from typing import Any, Dict, List, Optional


class TelemetryState(BaseModel):
    # A minimal, simulation-friendly state model
    x: float
    y: float
    theta: float
    speed: float

    zone: str = "aisle"  # aisle|loading_bay|corridor
    nearest_obstacle_m: float = 1.0

    human_detected: bool = False
    human_conf: float = 0.0

    events: List[str] = []  # e.g. ["near_miss"]

    raw: Optional[Dict[str, Any]] = None
