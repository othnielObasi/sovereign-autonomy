"""Controller admission, revocation ordering, and uncertain-outcome regressions."""
import asyncio
import json
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException

from app.autonomy import permit as wire
from app.autonomy.controller import ControllerJournal
from app.autonomy.core import Rejected
from app.autonomy.operations import Budget, SafeDispatcher, Watchdog
from app.services.execution_authority import ExecutionAuthority
from test_execution_authority import sim_module, sim, authority, _issue, _observe, _raw_command, SECRET


def run(coro):
    return asyncio.run(coro)


def prepare(authority, action, token):
    # Stop precisely at the dispatch/network boundary; no fake permit creation.
    SafeDispatcher(authority.permits, authority.checkpoints, None, Budget(5), Watchdog(10),
                   authority.evidence)._prepare(token, action)


def spent(authority, token):
    pid = json.loads(token)["payload"]["id"]
    with sqlite3.connect(authority.db_path) as conn:
        return conn.execute("SELECT used FROM permits WHERE id=?", (pid,)).fetchone()[0]


def test_only_the_controller_spends_a_prepared_permit(authority, sim):
    action, token = run(_issue(authority, sim, {"x": 6, "y": 3.5, "max_speed": 0.2}))
    prepare(authority, action, token)
    assert spent(authority, token) == 0
    result = run(sim.send_command(_raw_command(action, token)))
    assert result["ok"] and spent(authority, token) == 1
    assert action.action_id in run(sim.get_telemetry())["accepted_actions"]


def test_a_valid_but_unprepared_permit_cannot_bypass_dispatch(authority, sim):
    action, token = run(_issue(authority, sim, {"x": 6, "y": 3.5}))
    result = run(sim.send_command(_raw_command(action, token)))
    assert result["reason"] == "action_not_pending_dispatch"
    assert spent(authority, token) == 0
    assert action.action_id not in run(sim.get_telemetry())["accepted_actions"]


@pytest.mark.parametrize("scope,ident", [("mission", "mis-1"), ("agent", "planner:test")])
def test_mission_and_agent_kills_refuse_direct_delivery(authority, sim, scope, ident):
    action, token = run(_issue(authority, sim, {"x": 6, "y": 3.5}))
    prepare(authority, action, token)
    payload = json.loads(token)["payload"]
    request = wire.redemption_request(authority.secret, token, action.as_dict(), payload["controller"])
    assert run(authority.kill(scope, ident, reason="test", actor="op", sim=sim))["stop_verified"]
    with pytest.raises(Rejected, match="kill"):
        authority.redeem(request)
    result = run(sim.send_command(_raw_command(action, token)))
    assert result["rejected"]
    assert action.action_id not in run(sim.get_telemetry())["accepted_actions"]


@pytest.mark.parametrize("scope,ident", [("global", "*"), ("robot", "robot-1"),
                                         ("mission", "mis-1"), ("agent", "planner:test")])
def test_reset_never_revives_unused_permits(authority, sim, scope, ident):
    action, token = run(_issue(authority, sim, {"x": 6, "y": 3.5}))
    prepare(authority, action, token)
    run(authority.kill(scope, ident, reason="test", actor="op", sim=sim))
    run(authority.reset(scope, ident, actor="op", sim=sim))
    assert run(sim.send_command(_raw_command(action, token)))["rejected"]
    fresh, fresh_token = run(_issue(authority, sim, {"x": 6, "y": 3.5}))
    assert run(authority.dispatch("run-1", fresh, fresh_token, sim))["ok"]


def test_authority_restart_fences_old_tokens_even_when_world_version_repeats(authority, sim, sim_module, bind_redemption):
    action, token = run(_issue(authority, sim, {"x": 6, "y": 3.5}))
    prepare(authority, action, token)
    before = authority.kills.epoch
    restarted = ExecutionAuthority(secret=SECRET, db_path=authority.db_path)
    bind_redemption(sim_module, restarted)
    run(_observe(restarted, sim))
    assert restarted.world.current_version("robot-1") == action.world_version
    assert restarted.kills.epoch > before
    result = run(sim.send_command(_raw_command(action, token)))
    assert result["reason"] == "authority_epoch_changed"


def test_old_permit_rejected_after_policy_change(authority, sim):
    from app.policies import params as P
    action, token = run(_issue(authority, sim, {"x": 6, "y": 3.5}))
    prepare(authority, action, token)
    original = P.active_params()
    changed = dict(original, test_revision="new")
    try:
        P._set_active(changed)
        result = run(sim.send_command(_raw_command(action, token)))
        assert result["reason"] == "policy_version_changed"
    finally:
        P._set_active(original)


def test_old_world_permit_rejected_at_redemption(authority, sim):
    action, token = run(_issue(authority, sim, {"x": 6, "y": 3.5}))
    prepare(authority, action, token)
    run(_observe(authority, sim))
    assert run(sim.send_command(_raw_command(action, token)))["reason"] == "world_version_mismatch"


def test_concurrent_duplicate_delivery_admits_exactly_one_move(authority, sim):
    action, token = run(_issue(authority, sim, {"x": 6, "y": 3.5}))
    prepare(authority, action, token)

    async def race():
        return await asyncio.gather(*(sim.send_command(_raw_command(action, token)) for _ in range(8)))

    results = run(race())
    assert sum(bool(r.get("ok")) for r in results) == 1
    assert spent(authority, token) == 1
    assert run(sim.get_telemetry())["accepted_actions"].count(action.action_id) == 1


@pytest.mark.parametrize("redeem_first", [False, True])
def test_callback_outage_never_moves_or_retries(authority, sim, sim_module, monkeypatch, redeem_first):
    action, token = run(_issue(authority, sim, {"x": 6, "y": 3.5}))
    real = sim_module._post_redemption

    def unavailable(envelope):
        if redeem_first:
            real(envelope)  # response lost after the atomic single use
        raise HTTPException(503, "authority_unavailable")

    monkeypatch.setattr(sim_module, "_post_redemption", unavailable)
    result = run(authority.dispatch("run-1", action, token, sim))
    assert result["rejected"] and result["status"] == 503
    assert authority.checkpoints.status(action.action_id) == "NOT_EXECUTED"
    assert action.action_id not in run(sim.get_telemetry())["accepted_actions"]
    assert spent(authority, token) == int(redeem_first)
    assert run(sim.get_telemetry())["target"] is None
    monkeypatch.setattr(sim_module, "_post_redemption", real)
    assert run(sim.send_command(_raw_command(action, token)))["rejected"]


@pytest.mark.parametrize("stop_kind", ["STOP", "estop_reset", "mission_kill", "robot_reset", "seed"])
def test_stop_or_reset_overtakes_a_redeemed_reply(authority, sim, sim_module, monkeypatch, stop_kind):
    action, token = run(_issue(authority, sim, {"x": 6, "y": 3.5}))
    ready, release = threading.Event(), threading.Event()
    real = sim_module._post_redemption

    def delayed(envelope):
        response = real(envelope)
        ready.set()
        assert release.wait(10), "test did not release redemption reply"
        return response

    monkeypatch.setattr(sim_module, "_post_redemption", delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(lambda: run(authority.dispatch("run-1", action, token, sim)))
        try:
            assert ready.wait(10), "controller did not reach redemption boundary"
            # These must finish while the network reply is still blocked.
            if stop_kind == "STOP":
                assert run(sim.send_command({"intent": "STOP", "params": {}}))["ok"]
            elif stop_kind == "estop_reset":
                run(sim.estop(engaged=True))
                run(sim.estop(engaged=False, release_token=wire.release_token(authority.secret, "*")))
            elif stop_kind == "mission_kill":
                assert run(authority.kill("mission", "mis-1", reason="test", actor="op", sim=sim))["stop_verified"]
            elif stop_kind == "robot_reset":
                run(sim.reset_robot())
            else:
                run(sim.load_seed(42, "live"))
        finally:
            release.set()
        result = future.result(timeout=10)
    assert result["rejected"] and result["reason"] == "controller_context_changed"
    assert action.action_id not in run(sim.get_telemetry())["accepted_actions"]


def test_controller_restart_keeps_acceptance_evidence_and_replay_protection(authority, sim, sim_module, monkeypatch):
    action, token = run(_issue(authority, sim, {"x": 6, "y": 3.5}))
    assert run(authority.dispatch("run-1", action, token, sim))["ok"]
    monkeypatch.setattr(sim_module, "_journal", ControllerJournal(sim_module._journal.path))
    monkeypatch.setattr(sim_module, "_boot_id", uuid.uuid4().hex)
    monkeypatch.setattr(sim_module, "_used_permits", {})
    assert run(sim.send_command(_raw_command(action, token)))["reason"] == "permit_replayed"
    assert action.action_id in run(sim.get_telemetry())["accepted_actions"]
    fresh, fresh_token = run(_issue(authority, sim, {"x": 6, "y": 3.5}))
    assert run(authority.dispatch("run-1", fresh, fresh_token, sim))["ok"]


def test_lost_ack_then_stop_is_reconciled_from_durable_admission_evidence(authority, sim, sim_module, monkeypatch):
    action, token = run(_issue(authority, sim, {"x": 6, "y": 3.5}))

    class LostAck:
        async def send_command(self, command):
            assert (await sim.send_command(command))["ok"]
            raise TimeoutError("lost command response")

    with pytest.raises(Rejected, match="unknown"):
        run(authority.dispatch("run-1", action, token, LostAck()))
    run(sim.send_command({"intent": "STOP", "params": {}}))
    monkeypatch.setattr(sim_module, "_journal", ControllerJournal(sim_module._journal.path))
    telemetry = run(sim.get_telemetry())
    assert telemetry["target"] is None
    assert authority.reconcile_in_doubt("mis-1", telemetry) == [{"action_id": action.action_id, "executed": True}]


def test_spent_permit_without_controller_evidence_stays_uncertain(authority, sim):
    action, token = run(_issue(authority, sim, {"x": 6, "y": 3.5}))
    prepare(authority, action, token)
    payload = json.loads(token)["payload"]
    authority.redeem(wire.redemption_request(authority.secret, token, action.as_dict(), payload["controller"]))
    with pytest.raises(Rejected, match="admission_unknown"):
        authority.reconcile_in_doubt("mis-1", run(sim.get_telemetry()))
    assert authority.checkpoints.status(action.action_id) == "IN_DOUBT"


def test_reconciliation_retires_unsent_permit_before_allowing_resume(authority, sim):
    action, token = run(_issue(authority, sim, {"x": 6, "y": 3.5}))
    prepare(authority, action, token)
    assert authority.reconcile_in_doubt("mis-1", run(sim.get_telemetry())) == [
        {"action_id": action.action_id, "executed": False}]
    assert spent(authority, token) == 2
    assert run(sim.send_command(_raw_command(action, token)))["rejected"]


def test_retirement_survives_crash_before_reconciliation_checkpoint(authority, sim):
    action, token = run(_issue(authority, sim, {"x": 6, "y": 3.5}))
    prepare(authority, action, token)
    assert authority.permits.retire(action)
    assert authority.checkpoints.status(action.action_id) == "IN_DOUBT"
    restarted = ExecutionAuthority(secret=SECRET, db_path=authority.db_path)
    assert restarted.reconcile_in_doubt("mis-1", run(sim.get_telemetry())) == [
        {"action_id": action.action_id, "executed": False}]


def test_redemption_response_is_bound_to_the_exact_request(authority, sim, sim_module, monkeypatch):
    action, token = run(_issue(authority, sim, {"x": 6, "y": 3.5}))
    real = sim_module._post_redemption

    def altered(envelope):
        response = real(envelope)
        payload, _ = wire.open_envelope(authority.secret, response)
        payload["request_digest"] = "another-request"
        return wire.sign(authority.secret, payload)

    monkeypatch.setattr(sim_module, "_post_redemption", altered)
    result = run(authority.dispatch("run-1", action, token, sim))
    assert result["reason"] == "redemption_response_mismatch"
    assert action.action_id not in run(sim.get_telemetry())["accepted_actions"]


def test_release_token_is_single_use_and_stop_state_is_durable(authority, sim, sim_module):
    token = wire.release_token(authority.secret, "*")
    run(sim.estop(engaged=True, reason="first stop"))
    assert "*" in ControllerJournal(sim_module._journal.path).stops()
    run(sim.estop(engaged=False, release_token=token))
    run(sim.estop(engaged=True, reason="new stop"))
    try:
        import httpx
        with pytest.raises(httpx.HTTPStatusError) as error:
            run(sim.estop(engaged=False, release_token=token))
        assert error.value.response.json()["detail"] == "release_replayed"
        assert "*" in ControllerJournal(sim_module._journal.path).stops()
    finally:
        run(sim.estop(engaged=False, release_token=wire.release_token(authority.secret, "*")))


def test_unsigned_redemption_cannot_be_authorized_by_an_operator_token(authority):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_authority import router
    from app.auth.jwt import create_access_token
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    response = client.post("/authority/redeem", json={"request": "{}"},
                           headers={"Authorization": "Bearer " + create_access_token("op", role="operator")})
    assert response.status_code == 403
    assert response.json()["detail"] == "malformed_permit"


def test_expired_admission_reply_cannot_start_movement(authority, sim, sim_module, monkeypatch):
    action, token = run(_issue(authority, sim, {"x": 6, "y": 3.5}))
    real = sim_module._post_redemption

    def expired(envelope):
        payload, _ = wire.open_envelope(authority.secret, real(envelope))
        return wire.sign(authority.secret, dict(payload, expires=time.time() - 1))

    monkeypatch.setattr(sim_module, "_post_redemption", expired)
    assert run(authority.dispatch("run-1", action, token, sim))["reason"] == "redemption_expired"
    assert action.action_id not in run(sim.get_telemetry())["accepted_actions"]


def test_restart_loads_persisted_estop_and_rejects_unused_preboot_permit(authority, sim, sim_module, monkeypatch):
    import importlib.util
    import sys
    from fastapi.testclient import TestClient
    action, token = run(_issue(authority, sim, {"x": 6, "y": 3.5}))
    prepare(authority, action, token)
    run(sim.estop(engaged=True, reason="survive reboot"))
    monkeypatch.setenv("SIM_STATE_DB", sim_module._journal.path)
    spec = importlib.util.spec_from_file_location("controller_reboot_test", sim_module.__file__)
    restarted = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "controller_reboot_test", restarted)
    spec.loader.exec_module(restarted)
    assert restarted._boot_id != sim_module._boot_id
    client = TestClient(restarted.app)
    assert client.get("/telemetry").json()["estop"]["engaged"]
    response = client.post("/estop", json={"engaged": False, "release_token": wire.release_token(authority.secret, "*")})
    assert response.status_code == 200
    result = client.post("/command", json=_raw_command(action, token))
    assert result.status_code == 403 and result.json()["detail"] == "controller_context_changed"
    # Release the original process's in-memory stop too.
    run(sim.estop(engaged=False, release_token=wire.release_token(authority.secret, "*")))


def test_real_http_callback_roundtrip(authority, sim, sim_module, monkeypatch):
    import socket
    import uvicorn
    from fastapi import FastAPI
    from app.api.routes_authority import router
    app = FastAPI()
    app.include_router(router)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="error"))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        monkeypatch.setattr(sim_module, "AUTHORITY_BASE_URL", f"http://127.0.0.1:{port}")
        monkeypatch.setattr(sim_module, "_post_redemption", sim_module._http_redemption)
        action, token = run(_issue(authority, sim, {"x": 6, "y": 3.5}))
        assert run(authority.dispatch("run-1", action, token, sim))["ok"]
        assert spent(authority, token) == 1
    finally:
        server.should_exit = True
        thread.join(5)
        listener.close()
    assert not thread.is_alive()
