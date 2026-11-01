"""Active temporary site constraints (exclusion zones round hazards).

A constraint can only restrict motion: there is no field that grants
permission. Updating one keeps the stricter of old and new values, so outside
information can tighten a zone but never loosen it. A constraint ends when its
hazard is gone from the site.
"""
from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional


@dataclass
class SiteConstraint:
    id: str                 # e.g. "zone-spill-3"
    hazard_id: str
    label: str              # e.g. "isopropyl alcohol spill"
    x: float
    y: float
    radius: float           # no entry
    slow_radius: float      # speed cap inside this
    max_speed: float
    basis: str
    sources: List[str] = field(default_factory=list)   # domains that corroborated
    live: bool = False      # False when built from offline samples / baseline
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def as_dict(self) -> Dict:
        return asdict(self)

    def gate_view(self) -> Dict:
        """What the gate sees: geometry and limits only, never any outside text."""
        return {"id": self.id, "x": self.x, "y": self.y, "radius": self.radius,
                "slow_radius": self.slow_radius, "max_speed": self.max_speed, "label": self.label}


class ConstraintStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_hazard: Dict[str, SiteConstraint] = {}

    def upsert(self, c: SiteConstraint) -> SiteConstraint:
        """Insert, or tighten an existing constraint for the same hazard (never loosen)."""
        with self._lock:
            old = self._by_hazard.get(c.hazard_id)
            if old:
                c.radius = max(old.radius, c.radius)
                c.slow_radius = max(old.slow_radius, c.slow_radius)
                c.max_speed = min(old.max_speed, c.max_speed)
                c.created_at = old.created_at
                if c.basis.startswith("Baseline") and not old.basis.startswith("Baseline"):
                    c.basis, c.sources, c.live = old.basis, old.sources, old.live
            c.updated_at = time.time()
            self._by_hazard[c.hazard_id] = c
            return c

    def retain(self, present_hazard_ids: List[str]) -> List[SiteConstraint]:
        """Drop constraints whose hazard has gone; return the ones removed."""
        keep = set(present_hazard_ids)
        with self._lock:
            gone = [c for h, c in self._by_hazard.items() if h not in keep]
            for c in gone:
                del self._by_hazard[c.hazard_id]
            return gone

    def get(self, hazard_id: str) -> Optional[SiteConstraint]:
        return self._by_hazard.get(hazard_id)

    def active(self) -> List[SiteConstraint]:
        with self._lock:
            return list(self._by_hazard.values())

    def clear(self) -> None:
        with self._lock:
            self._by_hazard.clear()


store = ConstraintStore()
