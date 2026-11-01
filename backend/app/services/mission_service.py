from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
import math

import httpx
from app.config import settings
from sqlalchemy.orm import Session

from app.db.models import Mission, MissionAudit
from app.services.gemini_planner import resolve_bay_from_instruction
from app.schemas.mission import MissionCreate, MissionUpdate
from app.utils.ids import new_id
from app.utils.time import utc_now


class MissionService:
    """Manages mission CRUD, goal normalisation, and audit logging.

    A *mission* represents a high-level objective (e.g. "deliver to Bay C3").
    The service handles:
    - Creating missions with auto-resolved bay coordinates.
    - Updating missions (only when in draft/paused state).
    - Normalising goal coordinates: clamping to geofence, snapping to
      the nearest bay, and resolving bay names from natural-language titles.
    - Recording every mutation in the immutable ``mission_audit`` table.
    """

    # ── helpers ──────────────────────────────────────────────

    def _audit(
        self,
        db: Session,
        mission_id: str,
        action: str,
        *,
        old_values: Optional[Dict[str, Any]] = None,
        new_values: Optional[Dict[str, Any]] = None,
        details: Optional[str] = None,
        actor: str = "operator",
    ) -> MissionAudit:
        """Write an immutable audit-trail entry for a mission mutation."""
        entry = MissionAudit(
            mission_id=mission_id,
            ts=utc_now(),
            action=action,
            actor=actor,
            old_values=json.dumps(old_values, ensure_ascii=False) if old_values else None,
            new_values=json.dumps(new_values, ensure_ascii=False) if new_values else None,
            details=details,
        )
        db.add(entry)
        return entry

    # ── CRUD ─────────────────────────────────────────────────

    def create(self, db: Session, payload: MissionCreate) -> Mission:
        # Resolve bay_id if provided, otherwise normalize provided goal
        if getattr(payload, "bay_id", None):
            goal = self._resolve_bay_coords(payload.bay_id)
        else:
            goal = self._normalize_goal(payload.goal or {})

        m = Mission(
            id=new_id("mis"),
            title=payload.title,
            goal_json=json.dumps(goal, ensure_ascii=False),
            status="draft",
            created_at=utc_now(),
        )
        db.add(m)
        self._audit(
            db, m.id, "CREATED",
            new_values={"title": m.title, "goal": payload.goal, "status": "draft"},
            details=f"Mission created: {m.title}",
        )
        db.commit()
        db.refresh(m)
        return m

    def update(self, db: Session, mission_id: str, payload: MissionUpdate) -> Mission | None:
        m = self.get(db, mission_id)
        if not m:
            return None
        if m.status not in ("draft", "paused"):
            return None  # can only edit draft or paused missions

        old_vals: Dict[str, Any] = {}
        new_vals: Dict[str, Any] = {}

        if payload.title is not None and payload.title != m.title:
            old_vals["title"] = m.title
            new_vals["title"] = payload.title
            m.title = payload.title

            # If no explicit goal was provided, attempt to resolve a bay ID from
            # the new title and snap the mission goal to that bay (best-effort).
            if payload.goal is None:
                try:
                    # Try to fetch world (reuse same fallbacks as _normalize_goal)
                    world = None
                    try:
                        backend_url = f"http://127.0.0.1:{settings.backend_port}/sim/world"
                        with httpx.Client(timeout=1.0) as client:
                            r = client.get(backend_url)
                            r.raise_for_status()
                            world = r.json()
                    except Exception:
                        world = None
                    if world is None:
                        try:
                            url = settings.sim_base_url.rstrip("/") + "/world"
                            with httpx.Client(timeout=1.0) as client:
                                r = client.get(url)
                                r.raise_for_status()
                                world = r.json()
                        except Exception:
                            world = None
                    if world is None:
                        # last resort local file
                        from pathlib import Path

                        repo_root = Path(__file__).resolve().parents[4]
                        world_path = repo_root / "sim" / "mock_sim" / "world.json"
                        if world_path.exists():
                            with world_path.open() as fh:
                                world = json.load(fh)
                    bays = (world or {}).get("bays") or []
                    resolved = resolve_bay_from_instruction(payload.title or "", bays)
                    if resolved:
                        new_vals["goal"] = resolved
                        m.goal_json = json.dumps(resolved, ensure_ascii=False)
                except Exception:
                    # best-effort only; ignore any errors
                    pass

        # Handle explicit bay_id update (preferred) or explicit goal
        if getattr(payload, "bay_id", None):
            old_goal = json.loads(m.goal_json)
            new_goal = self._resolve_bay_coords(payload.bay_id)
            if new_goal != old_goal:
                old_vals["goal"] = old_goal
                new_vals["goal"] = new_goal
                m.goal_json = json.dumps(new_goal, ensure_ascii=False)

        elif payload.goal is not None:
            old_goal = json.loads(m.goal_json)
            new_goal = self._normalize_goal(payload.goal)
            if new_goal != old_goal:
                old_vals["goal"] = old_goal
                new_vals["goal"] = new_goal
                m.goal_json = json.dumps(new_goal, ensure_ascii=False)

        if new_vals:
            m.updated_at = utc_now()
            changes = ", ".join(new_vals.keys())
            self._audit(
                db, m.id, "UPDATED",
                old_values=old_vals,
                new_values=new_vals,
                details=f"Updated: {changes}",
            )
            db.commit()
            db.refresh(m)
        return m

    # --- Goal normalization helpers ---

    @staticmethod
    def _zone_for(x: float, y: float, world: Dict[str, Any]) -> str:
        """Determine the warehouse zone name for a coordinate pair.

        Used during goal normalisation to tag destinations with their zone
        (e.g. 'loading_dock', 'aisle'), which affects speed-limit policies.
        Falls back to 'aisle' if no zone boundary contains the point.
        """
        for z in (world or {}).get("zones", []):
            r = z.get("rect", {})
            if (r.get("min_x", 0) <= x <= r.get("max_x", 0)
                    and r.get("min_y", 0) <= y <= r.get("max_y", 0)):
                return z["name"]
        return "aisle"

    def _normalize_goal(self, goal: Dict[str, Any]) -> Dict[str, Any]:
        """Clamp goal to geofence and snap to nearest bay if within threshold.

        This function makes a best-effort attempt to fetch the world from the
        simulator (using settings.sim_base_url). If the world cannot be fetched
        the original goal is returned unchanged.
        """
        try:
            x = float(goal.get("x", 0))
            y = float(goal.get("y", 0))
        except Exception:
            return goal

        # Try to fetch world definition. Prefer internal backend proxy (/sim/world)
        world = None
        # First try local backend proxy to sim
        try:
            backend_url = f"http://127.0.0.1:{settings.backend_port}/sim/world"
            with httpx.Client(timeout=2.0) as client:
                r = client.get(backend_url)
                r.raise_for_status()
                world = r.json()
        except Exception:
            world = None

        # Fallback: call simulator base URL directly
        if world is None:
            try:
                url = settings.sim_base_url.rstrip("/") + "/world"
                with httpx.Client(timeout=2.0) as client:
                    r = client.get(url)
                    r.raise_for_status()
                    world = r.json()
            except Exception:
                world = None

        if world is None:
            # Fallback: try to read local sim/mock_sim/world.json from repository (useful in dev)
            try:
                from pathlib import Path

                repo_root = Path(__file__).resolve().parents[4]
                world_path = repo_root / "sim" / "mock_sim" / "world.json"
                if world_path.exists():
                    with world_path.open() as fh:
                        world = json.load(fh)
            except Exception:
                world = None

        if world is None:
            return {"x": x, "y": y}

        # Clamp to geofence if present
        gf = world.get("geofence") or {}
        try:
            min_x = float(gf.get("min_x", x))
            max_x = float(gf.get("max_x", x))
            min_y = float(gf.get("min_y", y))
            max_y = float(gf.get("max_y", y))
            x = max(min_x, min(x, max_x))
            y = max(min_y, min(y, max_y))
        except Exception:
            pass

        # Snap to nearest bay if within threshold
        bays = world.get("bays") or []
        best = None
        best_d = None
        for b in bays:
            try:
                bx = float(b.get("x", 0))
                by = float(b.get("y", 0))
            except Exception:
                continue
            d = math.hypot(bx - x, by - y)
            if best is None or d < best_d:
                best = (bx, by)
                best_d = d

        # Snap threshold (meters in sim units)
        SNAP_THRESHOLD = 1.5
        if best is not None and best_d is not None and best_d <= SNAP_THRESHOLD:
            x, y = best

        zone = self._zone_for(x, y, world)
        return {"x": x, "y": y, "zone": zone}

    def _resolve_bay_coords(self, bay_id: str) -> Dict[str, Any]:
        """Resolve a bay ID to canonical coordinates using the world definition.

        Best-effort: try backend sim proxy -> sim_base_url -> local world.json
        """
        try:
            # Try fetching world similar to _normalize_goal
            world = None
            try:
                backend_url = f"http://127.0.0.1:{settings.backend_port}/sim/world"
                with httpx.Client(timeout=1.0) as client:
                    r = client.get(backend_url)
                    r.raise_for_status()
                    world = r.json()
            except Exception:
                world = None
            if world is None:
                try:
                    url = settings.sim_base_url.rstrip("/") + "/world"
                    with httpx.Client(timeout=1.0) as client:
                        r = client.get(url)
                        r.raise_for_status()
                        world = r.json()
                except Exception:
                    world = None
            if world is None:
                from pathlib import Path

                repo_root = Path(__file__).resolve().parents[4]
                world_path = repo_root / "sim" / "mock_sim" / "world.json"
                if world_path.exists():
                    with world_path.open() as fh:
                        world = json.load(fh)
            bays = (world or {}).get("bays") or []
            for b in bays:
                if str(b.get("id", "")).upper() == str(bay_id).upper():
                    bx, by = float(b.get("x", 0)), float(b.get("y", 0))
                    zone = self._zone_for(bx, by, world)
                    return {"x": bx, "y": by, "zone": zone}
        except Exception:
            pass
        # Fallback: return origin
        return {"x": 0.0, "y": 0.0}

    def set_status(
        self, db: Session, mission_id: str, new_status: str,
        *, details: Optional[str] = None, actor: str = "operator",
    ) -> Mission | None:
        m = self.get(db, mission_id)
        if not m:
            return None
        old_status = m.status
        m.status = new_status
        m.updated_at = utc_now()
        self._audit(
            db, m.id, "STATUS_CHANGE",
            old_values={"status": old_status},
            new_values={"status": new_status},
            details=details or f"Status: {old_status} → {new_status}",
            actor=actor,
        )
        db.commit()
        db.refresh(m)
        return m

    def soft_delete(self, db: Session, mission_id: str) -> Mission | None:
        return self.set_status(db, mission_id, "deleted", details="Mission soft-deleted")

    def replay(self, db: Session, mission_id: str) -> Mission | None:
        """Reset a completed/failed mission back to draft so it can be re-executed."""
        m = self.get(db, mission_id)
        if not m:
            return None
        if m.status not in ("completed", "failed", "paused"):
            return None
        old_status = m.status
        m.status = "draft"
        m.updated_at = utc_now()
        self._audit(
            db, m.id, "REPLAYED",
            old_values={"status": old_status},
            new_values={"status": "draft"},
            details=f"Mission replayed from {old_status}",
        )
        db.commit()
        db.refresh(m)
        return m

    def list(
        self, db: Session, limit: int = 50, offset: int = 0,
        include_deleted: bool = False,
    ) -> List[Mission]:
        q = db.query(Mission)
        if not include_deleted:
            q = q.filter(Mission.status != "deleted")
        return q.order_by(Mission.created_at.desc()).offset(offset).limit(limit).all()

    def get(self, db: Session, mission_id: str) -> Mission | None:
        return db.query(Mission).filter(Mission.id == mission_id).first()

    def get_audit_trail(
        self, db: Session, mission_id: Optional[str] = None,
        limit: int = 100, offset: int = 0,
    ) -> List[MissionAudit]:
        q = db.query(MissionAudit)
        if mission_id:
            q = q.filter(MissionAudit.mission_id == mission_id)
        return q.order_by(MissionAudit.ts.desc()).offset(offset).limit(limit).all()
