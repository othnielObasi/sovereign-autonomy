from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class Point(BaseModel):
    x: float
    y: float


class CircleObstacle(BaseModel):
    x: float
    y: float
    r: float


class Geofence(BaseModel):
    min_x: float
    max_x: float
    min_y: float
    max_y: float


class ZoneRect(BaseModel):
    min_x: float
    max_x: float
    min_y: float
    max_y: float


class Zone(BaseModel):
    name: str
    rect: ZoneRect


class Human(BaseModel):
    x: float
    y: float


class SimWorld(BaseModel):
    site: Optional[Dict[str, str]] = None
    site_id: Optional[str] = None
    map_version: Optional[str] = None
    capability_profile_version: Optional[str] = None
    geofence: Geofence
    zones: List[Zone] = []
    obstacles: List[Dict[str, Any]] = []  # kept flexible for MVP
    human: Optional[Human] = None
    walking_humans: List[Dict[str, Any]] = []
    idle_robots: List[Dict[str, Any]] = []
    bays: List[Dict[str, Any]] = []
    racks: List[Dict[str, Any]] = []
    features: List[Dict[str, Any]] = []
    hotspots: List[Dict[str, Any]] = []
    mode: Optional[str] = None
    seed: Optional[int] = None


class PathPreview(BaseModel):
    points: List[Point]
    note: str = ""
