"""Evidence: the safety benchmark results committed with the code.

Serves the summaries in bench/results/<suite>/results.json (and the benchmark job
manifest when present) so the dashboard can show what the gate prevented.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.deps import get_db

router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.get("/learning")
def learning_summary(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Live counts for adaptive learning and task-drift control on this deployment."""
    from app.db.models import Event
    from app.services.planner_lessons import all_lessons

    counts = dict(db.query(Event.type, func.count(Event.id))
                  .filter(Event.type.in_(("TASK_CHECK", "REPLAN", "PLAN"))).group_by(Event.type).all())
    checks = drift = plans_with_lessons = lessons_used = 0
    for (payload,) in db.query(Event.payload_json).filter(Event.type.in_(("TASK_CHECK", "PLAN"))).all():
        try:
            p = json.loads(payload)
        except Exception:
            continue
        if "stage" in p and "verdict" in p:          # TASK_CHECK
            checks += 1
            drift += p.get("verdict") == "DRIFT"
        elif p.get("lessons_offered"):               # PLAN with lessons
            plans_with_lessons += 1
            lessons_used += len(p.get("lessons_applied") or [])
    lessons = all_lessons(db)
    quarantined_lessons = sum(l.get('status') == 'quarantined' for l in lessons)
    lessons = [l for l in lessons if l.get('status') != 'quarantined']
    by_policy: Dict[str, int] = {}
    for l in lessons:
        by_policy[l["policy"]] = by_policy.get(l["policy"], 0) + 1
    return {
        "lessons": len(lessons),
        'quarantined_lessons': quarantined_lessons,
        "lessons_by_policy": dict(sorted(by_policy.items(), key=lambda kv: -kv[1])),
        "plans_with_lessons": plans_with_lessons,
        "lessons_used": lessons_used,
        "replans": counts.get("REPLAN", 0),
        "task_checks": checks,
        "drift_caught": drift,
    }

RESULTS_DIR = Path(__file__).resolve().parents[2] / "bench" / "results"

SUITES = {
    "rule_based": {"title": "Rule-based planner", "summary": "150 seeded missions per arm, 5 rounds of fresh scenarios"},
    "reckless": {"title": "Stress test: reckless planner", "summary": "Drives at 0.9 m/s everywhere"},
}

ARM_KEYS = ("completion_rate", "mean_time_to_goal_s", "unsafe_proposed", "unsafe_executed",
            "unsafe_proposed_per_100_moves", "person_contacts", "person_contacts_while_braking",
            "structure_contacts", "false_block_rate", "scenarios", "move_proposals", "replans", "yields")


def _arms(block: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {arm: {k: v.get(k) for k in ARM_KEYS} for arm, v in (block or {}).items()}


def _suite(name: str) -> Dict[str, Any] | None:
    path = RESULTS_DIR / name / "results.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    manifest = None
    if (RESULTS_DIR / name / "manifest.json").exists():
        manifest = json.loads((RESULTS_DIR / name / "manifest.json").read_text(encoding="utf-8"))
    cfg = data.get("config", {})
    return {
        "id": name, **SUITES.get(name, {"title": name, "summary": ""}),
        "planner": cfg.get("planner"), "rounds": cfg.get("rounds"), "seeds_per_round": cfg.get("seeds_per_round"),
        "generated_at": cfg.get("generated_at"), "wall_time_s": cfg.get("wall_time_s"),
        "totals": _arms(data.get("totals", {})),
        "rounds_detail": [{"round": r.get("round"), "lessons_available": r.get("lessons_available"),
                           "arms": _arms(r.get("arms", {}))} for r in data.get("rounds", [])],
        "model_usage": data.get("model_usage"),
        "execution": (manifest or {}).get("execution", "local"),
        "source_commit": (manifest or {}).get("source_commit"),
    }


@router.get("/benchmarks")
def benchmarks() -> Dict[str, List[Dict[str, Any]]]:
    out = [s for s in (_suite(n) for n in SUITES) if s]
    return {"suites": out}
