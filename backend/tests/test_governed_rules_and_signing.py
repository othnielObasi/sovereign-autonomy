"""Signed receipts and the governed rule-change workflow."""
from __future__ import annotations

import json
import uuid

import pytest
from conftest import _TestSession
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app.db.models import GovernanceDecisionRecord, PolicyActivation, PolicyProposal, Run
from app.main import app
from app.policies import params as P
from app.policies import proposals as svc
from app.policies.rules_python import evaluate_policies
from app.policies.versioning import policy_version_hash
from app.schemas.governance import ActionProposal
from app.services.governance_engine import GovernanceEngine
from app.utils import signing
from app.utils.time import utc_now

AISLE = {"x": 12.3, "y": 8.1, "zone": "aisle", "speed": 0.3, "human_detected": False, "nearest_obstacle_m": 5.0}
NEAR_PERSON = dict(AISLE, human_detected=True, human_conf=0.9, human_distance_m=1.5)


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    monkeypatch.setenv("RECEIPT_SIGNING_KEY_FILE", str(tmp_path / "k.key"))
    monkeypatch.delenv("RECEIPT_SIGNING_KEY", raising=False)
    signing._reset_for_tests()
    P.reset_to_defaults_for_tests()
    db = _TestSession()
    db.query(PolicyProposal).delete()
    db.query(PolicyActivation).delete()
    db.query(Run).filter(Run.id.like("rp_%")).delete(synchronize_session=False)
    db.commit()
    yield db
    db.close()
    P.reset_to_defaults_for_tests()
    signing._reset_for_tests()


def _decide(db, telemetry, speed, run_id=None):
    run_id = run_id or f"rp_{uuid.uuid4().hex[:8]}"
    d = GovernanceEngine().evaluate_and_record(
        db, run_id, telemetry,
        ActionProposal(intent="MOVE_TO", params={"x": 14.0, "y": 8.0, "max_speed": speed}, rationale="t"))
    db.commit()
    rec = (db.query(GovernanceDecisionRecord).filter(GovernanceDecisionRecord.run_id == run_id)
           .order_by(GovernanceDecisionRecord.id.desc()).first())
    return d, rec


def _seed(db, n_safe=40, n_near=15):
    for _ in range(n_safe):
        _decide(db, AISLE, 0.4)
    for _ in range(n_near):
        _decide(db, NEAR_PERSON, 0.45)   # denied today (0.45 > 0.4 near people); floor-safe


# -- signed receipts -------------------------------------------------------------

def test_decisions_are_signed_and_verify(clean):
    _, rec = _decide(clean, AISLE, 0.9)
    assert rec.signature and rec.signing_key_id == signing.key_id()
    result = GovernanceEngine().verify_receipt(clean, rec.run_id, rec.id)
    assert result["valid"] is True and result["algorithm"] == "Ed25519"


def test_tampered_decision_fails_verification(clean):
    _, rec = _decide(clean, AISLE, 0.9)
    rec.decision = "APPROVED"            # someone edits the record after the fact
    clean.commit()
    result = GovernanceEngine().verify_receipt(clean, rec.run_id, rec.id)
    assert result["valid"] is False and "altered" in result["reason"]


def test_receipt_from_another_key_is_reported(clean):
    _, rec = _decide(clean, AISLE, 0.4)
    signing._reset_for_tests(Ed25519PrivateKey.generate())   # a different deployment key
    result = GovernanceEngine().verify_receipt(clean, rec.run_id, rec.id)
    assert result["valid"] is False and "signed by key" in result["reason"]


def test_unsigned_legacy_decision_is_reported(clean):
    _, rec = _decide(clean, AISLE, 0.4)
    rec.signature = None
    clean.commit()
    assert GovernanceEngine().verify_receipt(clean, rec.run_id, rec.id)["signed"] is False


def test_signing_endpoints(clean):
    _, rec = _decide(clean, AISLE, 0.4)
    with TestClient(app) as client:
        key = client.get("/governance/signing-key").json()
        ver = client.get(f"/governance/receipts/{rec.run_id}/{rec.id}/verify").json()
    assert key["algorithm"] == "Ed25519" and key["key_id"] == rec.signing_key_id
    assert "BEGIN PUBLIC KEY" in key["public_key_pem"]
    assert ver["valid"] is True


def test_decision_records_the_rules_it_was_judged_under(clean):
    _, rec = _decide(clean, AISLE, 0.4)
    assert rec.policy_version == policy_version_hash()
    assert "human_conf" in json.loads(rec.telemetry_summary)     # replayable


# -- proposals: creation -----------------------------------------------------------

def test_create_tightening_proposal(clean):
    row = svc.create(clean, {"ZONE_SPEED_LIMITS.aisle": 0.45}, "alice", "slow the aisles")
    changes = json.loads(row.changes_json)
    assert row.status == "draft"
    assert changes == [{"path": "ZONE_SPEED_LIMITS.aisle", "from": 0.5, "to": 0.45,
                        "direction": "tighten", "unit": "m/s"}]
    assert row.base_version == policy_version_hash() != row.candidate_version


@pytest.mark.parametrize("changes, message", [
    ({"HUMAN_STOP_RADIUS_M": 0.5}, "outside hard bounds"),
    ({"GEOFENCE.max_x": 99}, "cannot be changed"),
    ({"ZONE_SPEED_LIMITS.aisle": 0.5}, "no effective change"),
    ({"HUMAN_STOP_RADIUS_M": 3.0}, "smaller than HUMAN_SLOW_RADIUS_M"),
])
def test_invalid_proposals_are_refused(clean, changes, message):
    with pytest.raises(svc.ProposalError, match=message):
        svc.create(clean, changes, "alice")


# -- proposals: evaluation gate --------------------------------------------------------

def test_relaxation_without_enough_evidence_fails(clean):
    _seed(clean)
    row = svc.create(clean, {"MAX_SPEED_NEAR_HUMAN": 0.5}, "alice")
    row = svc.evaluate(clean, row.id, limit=10)
    ev = json.loads(row.evaluation_json)
    assert row.status == "failed_evaluation"
    assert ev["relaxes_any_rule"] and "at least 50" in ev["failures"][0]


def test_safe_relaxation_passes_replay_and_reports_impact(clean):
    _seed(clean)
    row = svc.evaluate(clean, svc.create(clean, {"MAX_SPEED_NEAR_HUMAN": 0.5}, "alice").id)
    ev = json.loads(row.evaluation_json)
    assert row.status == "evaluated" and ev["passed"]
    assert ev["candidate"]["unsafe_allowed"] == 0
    assert ev["newly_allowed"] >= 15                      # the seeded 0.45 m/s moves near a person
    assert ev["candidate"]["false_block_rate"] < ev["active"]["false_block_rate"]
    assert ev["benchmark"]["status"] == "not_run" and ev["benchmark"]["required"] is True


def test_replay_blocks_a_change_that_would_allow_unsafe_moves(clean, monkeypatch):
    _seed(clean)
    # Stricter floor: 0.45 m/s with a person 1.5 m away now counts as unsafe
    monkeypatch.setitem(svc.SAFETY_FLOORS, "near_person_max_speed", 0.3)
    row = svc.evaluate(clean, svc.create(clean, {"MAX_SPEED_NEAR_HUMAN": 0.5}, "alice").id)
    ev = json.loads(row.evaluation_json)
    assert row.status == "failed_evaluation"
    assert ev["candidate"]["unsafe_allowed"] >= 15 and "unsafe move" in ev["failures"][0]


# -- proposals: approval, activation, rollback ---------------------------------------------

def _evaluated(db, changes=None):
    row = svc.create(db, changes or {"ZONE_SPEED_LIMITS.aisle": 0.45}, "alice")
    return svc.evaluate(db, row.id)


def test_creator_cannot_approve_and_unevaluated_cannot_be_approved(clean):
    draft = svc.create(clean, {"ZONE_SPEED_LIMITS.aisle": 0.45}, "alice")
    with pytest.raises(svc.ProposalError, match="separation of duties"):
        svc.approve(clean, draft.id, "Alice")
    with pytest.raises(svc.ProposalError, match="passed evaluation"):
        svc.approve(clean, draft.id, "bob")


def test_activation_changes_what_the_gate_enforces(clean):
    row = svc.approve(clean, _evaluated(clean).id, "bob", "agreed at safety review")
    before = policy_version_hash()
    move = ActionProposal(intent="MOVE_TO", params={"x": 14, "y": 8, "max_speed": 0.47}, rationale="t")
    assert evaluate_policies(AISLE, move).decision == "APPROVED"

    act = svc.activate(clean, row.id, "bob")
    assert act.version_hash == policy_version_hash() != before
    assert act.previous_version == before
    assert evaluate_policies(AISLE, move).decision != "APPROVED"      # 0.47 > new 0.45 limit
    assert clean.get(PolicyProposal, row.id).status == "active"
    _, rec = _decide(clean, AISLE, 0.4)
    assert rec.policy_version == act.version_hash


def test_activation_waits_for_runs_to_finish(clean):
    row = svc.approve(clean, _evaluated(clean).id, "bob")
    clean.add(Run(id="rp_busy", mission_id="m", status="running", started_at=utc_now()))
    clean.commit()
    with pytest.raises(svc.ProposalError, match="in progress"):
        svc.activate(clean, row.id, "bob")


def test_stale_proposal_cannot_activate(clean):
    a = svc.approve(clean, _evaluated(clean, {"ZONE_SPEED_LIMITS.aisle": 0.45}).id, "bob")
    b = svc.approve(clean, _evaluated(clean, {"ZONE_SPEED_LIMITS.corridor": 0.6}).id, "bob")
    svc.activate(clean, a.id, "bob")
    with pytest.raises(svc.ProposalError, match="changed since this proposal"):
        svc.activate(clean, b.id, "bob")


def test_rollback_restores_previous_rules_and_survives_restart(clean):
    row = svc.approve(clean, _evaluated(clean).id, "bob")
    default_version = policy_version_hash()
    svc.activate(clean, row.id, "bob")

    P.reset_to_defaults_for_tests()                       # simulate a restart...
    assert P.load_active_from_db(clean) == policy_version_hash() != default_version   # ...rules reload

    svc.rollback(clean, "carol", "aisle throughput dropped too far")
    assert policy_version_hash() == default_version
    assert clean.get(PolicyProposal, row.id).status == "rolled_back"
    assert clean.query(PolicyActivation).count() == 2     # append-only history


def test_full_flow_over_the_api(clean):
    with TestClient(app) as client:
        r = client.post("/policies/proposals", json={"changes": {"ZONE_SPEED_LIMITS.aisle": 0.45},
                                                     "created_by": "alice", "description": "test"})
        pid = r.json()["id"]
        assert client.post(f"/policies/proposals/{pid}/evaluate", json={}).json()["status"] == "evaluated"
        assert client.post(f"/policies/proposals/{pid}/approve", json={"approver": "alice"}).status_code == 403
        assert client.post(f"/policies/proposals/{pid}/approve", json={"approver": "bob"}).json()["status"] == "approved"
        act = client.post(f"/policies/proposals/{pid}/activate", json={"by": "bob"}).json()
        active = client.get("/policies/active").json()
        assert active["version"] == act["version_hash"] and active["is_default"] is False
        assert active["parameters"]["ZONE_SPEED_LIMITS"]["aisle"] == 0.45
        rb = client.post("/policies/rollback", json={"by": "carol", "reason": "test rollback"})
        assert rb.status_code == 200 and client.get("/policies/active").json()["is_default"] is True


def test_tuning_is_honest_about_being_recommend_only(clean):
    from app.services.adaptive_tuning import compute_tuning_recommendations
    out = compute_tuning_recommendations(clean)
    if out["status"] == "ok":
        assert out["auto_tuning_active"] is False and out["mode"] == "recommend_only"
    assert policy_version_hash() == P.params_hash(P.DEFAULT_PARAMS)   # nothing applied
