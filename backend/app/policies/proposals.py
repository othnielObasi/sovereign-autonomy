"""Governed rule changes — the "slow loop" of Sovereign Autonomy learning.

The planner may learn freely; the gate's thresholds change only like this:

    create (draft) -> evaluate (replay gate) -> approve (a named person, not the
    creator) -> activate (no runs in progress; rules unchanged since the proposal)
    -> rollback at any time (a new activation restoring the previous rules)

Every activation is an append-only row in `policy_activations`; every decision
records the version hash it was judged under, and its receipt is signed.

Two checks. *Replay*: every recorded gate decision (what the robot saw, what
the planner proposed) is re-judged under the candidate and the active rules,
and each move is labelled safe or unsafe by SAFETY_FLOORS — fixed limits in
code that no proposal can change; the candidate fails if it would have allowed
any floor-unsafe move. *Benchmark* (bench/): seeded scenarios are driven under
both rule sets, which shows behaviour the new rules cause and replay cannot;
the candidate fails if it executes any unsafe move or the robot moves into a
person. The benchmark is required before any relaxation can be approved.
"""
from __future__ import annotations

import json
import logging
import math
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.models import GovernanceDecisionRecord, PolicyActivation, PolicyProposal, Run
from app.policies import params as P
from app.policies.retreat import is_slow_retreat
from app.policies.rules_python import evaluate_policies
from app.schemas.governance import ActionProposal
from app.utils.ids import new_id
from app.utils.time import utc_now

logger = logging.getLogger("app.policies.proposals")

# Fixed safety floors (code, not data): a move is unsafe if any holds.
SAFETY_FLOORS = {
    "person_within_m": 1.0,          # a person or worker closer than this
    "obstacle_within_m": 0.5,        # an obstacle closer than this
    "max_speed_mps": 1.0,            # faster than this anywhere
    "near_person_m": 2.0,            # with a person this close...
    "near_person_max_speed": 0.5,    # ...faster than this
    "geofence": dict(P.DEFAULT_PARAMS["GEOFENCE"]),
}
MIN_REPLAY_DECISIONS_FOR_RELAXATION = 50
REPLAY_LIMIT = 5000


class ProposalError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------
# Floors and replay
# ---------------------------------------------------------------------------

def _nearest_person(tel: Dict[str, Any]) -> float:
    d = float(tel.get("human_distance_m", 999.0))
    x, y = float(tel.get("x", 0.0)), float(tel.get("y", 0.0))
    for w in tel.get("walking_humans") or []:
        try:
            d = min(d, math.hypot(float(w["x"]) - x, float(w["y"]) - y))
        except (KeyError, TypeError, ValueError):
            continue
    return d


def unsafe_by_floor(tel: Dict[str, Any], proposal: Dict[str, Any]) -> Optional[str]:
    """Why a proposed move is unsafe by the fixed floors, or None if it is not."""
    if proposal.get("intent") != "MOVE_TO":
        return None
    p = proposal.get("params") or {}
    g = SAFETY_FLOORS["geofence"]
    for (px, py), what in (((tel.get("x", 0), tel.get("y", 0)), "position"),
                           ((p.get("x", tel.get("x", 0)), p.get("y", tel.get("y", 0))), "destination")):
        if not (g["min_x"] <= float(px) <= g["max_x"] and g["min_y"] <= float(py) <= g["max_y"]):
            return f"{what} outside the site boundary"
    person = _nearest_person(tel)
    speed = float(p.get("max_speed", 0.0) or 0.0)
    if person < SAFETY_FLOORS["person_within_m"]:
        return f"person {person:.2f} m away"
    if (float(tel.get("nearest_obstacle_m", 999.0)) < SAFETY_FLOORS["obstacle_within_m"]
            and not is_slow_retreat(tel, p)):
        return "obstacle closer than 0.5 m"
    if speed > SAFETY_FLOORS["max_speed_mps"]:
        return f"speed {speed:.2f} m/s above 1.0"
    if person < SAFETY_FLOORS["near_person_m"] and speed > SAFETY_FLOORS["near_person_max_speed"]:
        return f"speed {speed:.2f} m/s with a person {person:.2f} m away"
    return None


def replay(db: Session, active: Dict[str, Any], candidate: Dict[str, Any], limit: int = REPLAY_LIMIT) -> Dict[str, Any]:
    rows = (db.query(GovernanceDecisionRecord)
            .order_by(GovernanceDecisionRecord.id.desc()).limit(limit).all())
    stats = {k: {"approved": 0, "unsafe_allowed": 0, "safe_blocked": 0} for k in ("active", "candidate")}
    n = partial = unsafe_total = 0
    newly_allowed: List[Dict[str, Any]] = []
    newly_blocked: List[Dict[str, Any]] = []
    unsafe_examples: List[Dict[str, Any]] = []
    runs = set()

    for r in rows:
        try:
            tel = json.loads(r.telemetry_summary or "{}")
            prop = json.loads(r.proposal_json or "{}")
            proposal = ActionProposal(**prop)
        except Exception:
            continue
        if "x" not in tel:
            continue
        if "human_conf" not in tel:
            partial += 1  # older record: confidence not stored; assume a confident detection
            tel = dict(tel, human_conf=0.9 if tel.get("human_detected") else 0.0)
        n += 1
        runs.add(r.run_id)
        floor = unsafe_by_floor(tel, prop)
        unsafe_total += bool(floor)
        out = {}
        for key, params in (("active", active), ("candidate", candidate)):
            ok = evaluate_policies(tel, proposal, params).decision == "APPROVED"
            out[key] = ok
            s = stats[key]
            s["approved"] += ok
            if ok and floor:
                s["unsafe_allowed"] += 1
            if not ok and not floor and proposal.intent == "MOVE_TO":
                s["safe_blocked"] += 1
        item = {"decision_id": r.id, "run_id": r.run_id, "unsafe": floor}
        if out["candidate"] and not out["active"]:
            newly_allowed.append(item)
        elif out["active"] and not out["candidate"]:
            newly_blocked.append(item)
        if out["candidate"] and floor and len(unsafe_examples) < 10:
            unsafe_examples.append(item)

    def rate(k: str) -> Optional[float]:
        safe_moves = n - unsafe_total
        return round(stats[k]["safe_blocked"] / safe_moves, 4) if safe_moves else None

    return {
        "method": "replay",
        "decisions_replayed": n,
        "runs_covered": len(runs),
        "partial_telemetry_records": partial,
        "floor_unsafe_proposals": unsafe_total,
        "active": {**stats["active"], "false_block_rate": rate("active")},
        "candidate": {**stats["candidate"], "false_block_rate": rate("candidate")},
        "newly_allowed": len(newly_allowed),
        "newly_blocked": len(newly_blocked),
        "newly_allowed_examples": newly_allowed[:10],
        "newly_blocked_examples": newly_blocked[:10],
        "unsafe_allowed_examples": unsafe_examples,
        "safety_floors": SAFETY_FLOORS,
    }


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------

def current_version() -> str:
    return P.params_hash(P.active_params())


def _changes(active: Dict[str, Any], changes: Dict[str, float]) -> List[Dict[str, Any]]:
    out = []
    for path, to in changes.items():
        if path not in P.PARAM_SPEC:
            raise ProposalError(f"'{path}' cannot be changed by proposal; changeable: {sorted(P.PARAM_SPEC)}")
        frm = float(P.get_path(active, path))
        to = float(to)
        if math.isclose(frm, to):
            continue
        tighter = (to < frm) if P.PARAM_SPEC[path]["tighter"] == "lower" else (to > frm)
        out.append({"path": path, "from": frm, "to": to, "direction": "tighten" if tighter else "relax",
                    "unit": P.PARAM_SPEC[path]["unit"]})
    if not out:
        raise ProposalError("no effective change: every value equals the active rules")
    return out


def create(db: Session, changes: Dict[str, float], created_by: str,
           description: str = "", source: str = "manual") -> PolicyProposal:
    if not created_by.strip():
        raise ProposalError("created_by is required")
    active = P.active_params()
    diff = _changes(active, changes)
    candidate = P.with_changes(active, {c["path"]: c["to"] for c in diff})
    problems = P.validate(candidate)
    if problems:
        raise ProposalError("candidate rules rejected: " + "; ".join(problems))
    row = PolicyProposal(
        id=new_id("prop"), created_at=utc_now(), created_by=created_by.strip(), source=source,
        description=description, base_version=P.params_hash(active), changes_json=json.dumps(diff),
        candidate_params_json=json.dumps(candidate), candidate_version=P.params_hash(candidate), status="draft",
    )
    db.add(row)
    db.commit()
    return row


TUNING_PATHS = {
    "max_speed_aisle": "ZONE_SPEED_LIMITS.aisle",
    "max_speed_loading": "ZONE_SPEED_LIMITS.loading_bay",
    "max_speed_open": "ZONE_SPEED_LIMITS.corridor",
    "max_speed_near_human": "MAX_SPEED_NEAR_HUMAN",
    "human_stop_radius_m": "HUMAN_STOP_RADIUS_M",
    "human_slow_radius_m": "HUMAN_SLOW_RADIUS_M",
    "obstacle_clearance_m": "MIN_OBSTACLE_CLEARANCE_M",
}


def create_from_tuning(db: Session, created_by: str) -> PolicyProposal:
    from app.services.adaptive_tuning import compute_tuning_recommendations

    rec = compute_tuning_recommendations(db)
    changes = {}
    for r in rec.get("recommendations", []):
        path = TUNING_PATHS.get(r.get("param"))
        if path:
            changes[path] = r["suggested"]  # later recommendations for the same path win
    if not changes:
        raise ProposalError(f"no applicable tuning recommendations ({rec.get('status')}: "
                            f"{rec.get('message', 'nothing to change')})", status=409)
    reasons = "; ".join(sorted({r.get("reason", "") for r in rec["recommendations"]}))
    return create(db, changes, created_by, description=f"From tuning: {reasons}", source="tuning")


def _get(db: Session, proposal_id: str) -> PolicyProposal:
    row = db.query(PolicyProposal).filter(PolicyProposal.id == proposal_id).first()
    if not row:
        raise ProposalError("proposal not found", status=404)
    return row


def evaluate(db: Session, proposal_id: str, limit: int = REPLAY_LIMIT) -> PolicyProposal:
    row = _get(db, proposal_id)
    if row.status not in ("draft", "evaluated", "failed_evaluation"):
        raise ProposalError(f"cannot evaluate a proposal that is {row.status}", status=409)
    diff = json.loads(row.changes_json)
    result = replay(db, P.active_params(), json.loads(row.candidate_params_json), limit=limit)
    relaxes = any(c["direction"] == "relax" for c in diff)
    failures = []
    if result["candidate"]["unsafe_allowed"] > 0:
        failures.append(f"would have allowed {result['candidate']['unsafe_allowed']} unsafe move(s)")
    if relaxes and result["decisions_replayed"] < MIN_REPLAY_DECISIONS_FOR_RELAXATION:
        failures.append(f"a relaxation needs at least {MIN_REPLAY_DECISIONS_FOR_RELAXATION} recorded "
                        f"decisions to replay; found {result['decisions_replayed']}")
    result.update({
        "evaluated_against_version": current_version(),
        "relaxes_any_rule": relaxes,
        "passed": not failures,
        "failures": failures,
        "benchmark": {"status": "not_run",
                      "required": relaxes,
                      "note": "POST /policies/proposals/{id}/benchmark drives seeded scenarios under both rule sets"},
        "evaluated_at": utc_now().isoformat(),
    })
    row.evaluation_json = json.dumps(result)
    row.status = "evaluated" if not failures else "failed_evaluation"
    db.commit()
    return row


BENCHMARK_SEEDS = 20
BENCHMARK_FIRST_SEED = 9000   # a block no learning run uses


def benchmark(db: Session, proposal_id: str, seeds: int = BENCHMARK_SEEDS) -> PolicyProposal:
    """Drive seeded scenarios under the active rules and under the candidate, with the gate on.

    Unlike replay, this shows behaviour the candidate rules *cause* (different speeds,
    different denials, different routes). Passes only if the candidate executes zero
    floor-unsafe moves and the robot never moves into a person. Required before a
    relaxation can be approved.
    """
    from bench.planners import RuleBased
    from bench.runner import aggregate, run_arm
    from bench.scenarios import generate
    from bench.world import Layout

    row = _get(db, proposal_id)
    if row.status not in ("evaluated", "failed_evaluation"):
        raise ProposalError(f"run the replay evaluation first (proposal is {row.status})", status=409)
    candidate = json.loads(row.candidate_params_json)
    active = P.active_params()
    layout = Layout()
    out: Dict[str, Any] = {}
    for label, rules in (("active", active), ("candidate", candidate)):
        planner = RuleBased(layout)
        planner.rules = rules
        rows = [run_arm(generate(s, layout), layout, planner, "governed", params=rules).as_dict()
                for s in range(BENCHMARK_FIRST_SEED, BENCHMARK_FIRST_SEED + seeds)]
        out[label] = aggregate(rows)
    c = out["candidate"]
    robot_caused = c["person_contacts"] - c["person_contacts_while_braking"]
    failures = []
    if c["unsafe_executed"]:
        failures.append(f"executed {c['unsafe_executed']} unsafe move(s)")
    if robot_caused:
        failures.append(f"robot moved into a person {robot_caused} time(s)")
    result = {
        "status": "passed" if not failures else "failed", "failures": failures,
        "planner": "rule_based", "seeds": [BENCHMARK_FIRST_SEED, BENCHMARK_FIRST_SEED + seeds - 1],
        "active": out["active"], "candidate": c,
        "completion_change": round(c["completion_rate"] - out["active"]["completion_rate"], 4),
        "false_block_rate_change": (round(c["false_block_rate"] - out["active"]["false_block_rate"], 4)
                                    if c["false_block_rate"] is not None and out["active"]["false_block_rate"] is not None
                                    else None),
        "ran_at": utc_now().isoformat(), "against_version": current_version(),
    }
    ev = json.loads(row.evaluation_json or "{}")
    ev["benchmark"] = result
    if failures:
        ev["passed"] = False
        ev.setdefault("failures", []).extend(f"benchmark: {f}" for f in failures)
        row.status = "failed_evaluation"
    row.evaluation_json = json.dumps(ev)
    db.commit()
    return row


def approve(db: Session, proposal_id: str, approver: str, note: str = "") -> PolicyProposal:
    row = _get(db, proposal_id)
    approver = (approver or "").strip()
    if not approver:
        raise ProposalError("approver is required")
    if approver.lower() == row.created_by.lower():
        raise ProposalError("separation of duties: the creator cannot approve their own proposal", status=403)
    if row.status != "evaluated":
        raise ProposalError(f"only a proposal that passed evaluation can be approved (this one is {row.status})",
                            status=409)
    ev = json.loads(row.evaluation_json or "{}")
    if ev.get("evaluated_against_version") != current_version():
        raise ProposalError("the active rules changed after evaluation; evaluate again", status=409)
    bench_result = ev.get("benchmark") or {}
    if ev.get("relaxes_any_rule") and bench_result.get("status") != "passed":
        raise ProposalError("a relaxation needs a passing safety benchmark: POST /policies/proposals/{id}/benchmark",
                            status=409)
    if bench_result.get("status") == "passed" and bench_result.get("against_version") != current_version():
        raise ProposalError("the active rules changed after the benchmark; run it again", status=409)
    row.status, row.approved_by, row.approved_at, row.approval_note = "approved", approver, utc_now(), note
    db.commit()
    return row


def reject(db: Session, proposal_id: str, by: str, reason: str) -> PolicyProposal:
    row = _get(db, proposal_id)
    if row.status in ("active", "rolled_back", "superseded", "rejected"):
        raise ProposalError(f"cannot reject a proposal that is {row.status}", status=409)
    row.status, row.rejected_reason = "rejected", f"{by}: {reason}"
    db.commit()
    return row


def _runs_in_progress(db: Session) -> int:
    return db.query(Run).filter(Run.status.in_(["running", "paused"])).count()


def _record_activation(db: Session, params: Dict[str, Any], by: str, proposal_id: Optional[str],
                       reason: str) -> PolicyActivation:
    problems = P.validate(params)
    if problems:
        raise ProposalError("refusing to activate invalid rules: " + "; ".join(problems), status=409)
    prev = current_version()
    act = PolicyActivation(version_hash=P.params_hash(params), parameters_json=json.dumps(params),
                           activated_at=utc_now(), activated_by=by, proposal_id=proposal_id,
                           previous_version=prev, reason=reason)
    db.add(act)
    db.flush()
    P._set_active(params)
    return act


def activate(db: Session, proposal_id: str, by: str) -> PolicyActivation:
    row = _get(db, proposal_id)
    if not (by or "").strip():
        raise ProposalError("'by' is required")
    if row.status != "approved":
        raise ProposalError(f"only an approved proposal can be activated (this one is {row.status})", status=409)
    if row.base_version != current_version():
        raise ProposalError("the active rules changed since this proposal was made; create a new one", status=409)
    busy = _runs_in_progress(db)
    if busy:
        raise ProposalError(f"{busy} run(s) in progress; rules change only between runs", status=409)
    act = _record_activation(db, json.loads(row.candidate_params_json), by.strip(), row.id,
                             f"Proposal {row.id} approved by {row.approved_by}")
    for other in db.query(PolicyProposal).filter(PolicyProposal.status == "active").all():
        other.status = "superseded"
    row.status, row.activated_at = "active", act.activated_at
    db.commit()
    logger.warning("Policy version %s activated by %s (proposal %s)", act.version_hash, by, row.id)
    return act


def rollback(db: Session, by: str, reason: str) -> PolicyActivation:
    if not (by or "").strip() or not (reason or "").strip():
        raise ProposalError("'by' and 'reason' are required")
    busy = _runs_in_progress(db)
    if busy:
        raise ProposalError(f"{busy} run(s) in progress; rules change only between runs", status=409)
    history = db.query(PolicyActivation).order_by(PolicyActivation.id.desc()).limit(2).all()
    if not history:
        raise ProposalError("nothing to roll back: the default rules are active", status=409)
    target = json.loads(history[1].parameters_json) if len(history) > 1 else P.DEFAULT_PARAMS
    act = _record_activation(db, target, by.strip(), None, f"Rollback: {reason}")
    if history[0].proposal_id:
        rolled = db.query(PolicyProposal).filter(PolicyProposal.id == history[0].proposal_id).first()
        if rolled:
            rolled.status = "rolled_back"
    db.commit()
    logger.warning("Policy rolled back to %s by %s: %s", act.version_hash, by, reason)
    return act


def to_dict(row: PolicyProposal) -> Dict[str, Any]:
    return {
        "id": row.id, "status": row.status, "source": row.source, "description": row.description,
        "created_by": row.created_by, "created_at": row.created_at.isoformat() if row.created_at else None,
        "base_version": row.base_version, "candidate_version": row.candidate_version,
        "changes": json.loads(row.changes_json),
        "evaluation": json.loads(row.evaluation_json) if row.evaluation_json else None,
        "approved_by": row.approved_by, "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "approval_note": row.approval_note,
        "activated_at": row.activated_at.isoformat() if row.activated_at else None,
        "rejected_reason": row.rejected_reason,
    }


def activation_dict(a: PolicyActivation) -> Dict[str, Any]:
    return {"id": a.id, "version_hash": a.version_hash, "activated_at": a.activated_at.isoformat(),
            "activated_by": a.activated_by, "proposal_id": a.proposal_id,
            "previous_version": a.previous_version, "reason": a.reason}
