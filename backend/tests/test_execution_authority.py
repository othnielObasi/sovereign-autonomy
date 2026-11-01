"""Execution authority end to end: permits issued by the backend are checked again by
the real warehouse simulator; kill switches stop the robot at the controller and
survive restarts; uncertain moves are settled against what the controller did."""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.autonomy import permit as wire
from app.autonomy.core import Rejected
from app.services.execution_authority import ExecutionAuthority
from app.services.sim_adapter import SimAdapter

SECRET = os.environ["PERMIT_SECRET"]


@pytest.fixture(scope="module")
def sim_module():
    sim_dir = str(Path(__file__).resolve().parents[2] / "sim" / "warehouse_sim")
    sys.path.insert(0, sim_dir)
    sys.modules.pop("server", None)
    try:
        server = importlib.import_module("server")
        with TestClient(server.app):   # runs the simulator's startup
            yield server
    finally:
        sys.path.remove(sim_dir)
        sys.modules.pop("server", None)
        sys.modules.pop("camera", None)


@pytest.fixture
def sim(sim_module):
    """The backend's real SimAdapter, talking to the real simulator in-process."""
    adapter = SimAdapter(base_url="http://sim")
    adapter._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=sim_module.app), base_url="http://sim")
    sim_module._estop.update(engaged=False, reason="", since=None)
    sim_module._robot_estops.clear()
    yield adapter
    sim_module._estop.update(engaged=False, reason="", since=None)
    sim_module._robot_estops.clear()


@pytest.fixture
def authority(tmp_path):
    return ExecutionAuthority(secret=SECRET, db_path=str(tmp_path / "authority.db"))


def run(coro):
    return asyncio.run(coro)


async def _observe(authority, sim):
    """Real simulator telemetry, minus the walking workers: these tests are about permits,
    and the path check (tested on its own below) would otherwise depend on where people wander."""
    tel = await sim.get_telemetry()
    tel["walking_humans"], tel["obstacles"] = [], []
    authority.observe(tel)


async def _issue(authority, sim, params, run_id="run-1"):
    await _observe(authority, sim)
    return authority.authorize(run_id=run_id, mission_id="mis-1", intent="MOVE_TO", params=params,
                               decision="APPROVED", policy_version="v1", agent_id="planner:test")


def _raw_command(action, token, **override):
    body = {"intent": action.kind, "params": action.params,
            "action": {k: v for k, v in action.as_dict().items() if k not in ("kind", "params")},
            "permit": token}
    body.update(override)
    return body


# --- the simulator checks every move -----------------------------------------------------

def test_permitted_move_executes_and_cannot_be_replayed(authority, sim):
    async def go():
        action, token = await _issue(authority, sim, {"x": 6.0, "y": 3.5, "max_speed": 0.3})
        first = await authority.dispatch("run-1", action, token, sim)
        replay = await sim.send_command(_raw_command(action, token))
        tel = await sim.get_telemetry()
        return first, replay, tel, action

    first, replay, tel, action = run(go())
    assert first["ok"] is True
    assert tel["target"]["x"] == pytest.approx(6.0)
    assert replay == {"ok": False, "rejected": True, "reason": "permit_replayed", "status": 403}
    assert authority.checkpoints.status(action.action_id) == "COMPLETED"


def test_simulator_refuses_altered_forged_expired_and_wrong_robot(authority, sim, sim_module):
    async def go():
        out = {}
        action, token = await _issue(authority, sim, {"x": 6.0, "y": 3.5, "max_speed": 0.3})
        out["altered"] = await sim.send_command(_raw_command(action, token, params={"x": 20.0, "y": 3.5, "max_speed": 0.3}))
        forged = wire.sign(b"some-other-secret-0123456789abcdef", json.loads(token)["payload"])
        out["forged"] = await sim.send_command(_raw_command(action, forged))
        out["missing"] = await sim.send_command({"intent": "MOVE_TO", "params": action.params})
        wrong = dict(_raw_command(action, token))
        wrong["action"] = dict(wrong["action"], robot_id="robot-9")
        out["wrong_robot"] = await sim.send_command(wrong)
        payload = dict(json.loads(token)["payload"], expires=time.time() - 1)
        out["expired"] = await sim.send_command(_raw_command(action, wire.sign(SECRET.encode(), payload)))
        out["stop"] = await sim.send_command({"intent": "STOP", "params": {}})
        return out

    out = run(go())
    assert out["altered"]["reason"] == "action_mismatch"
    assert out["forged"]["reason"] == "invalid_signature"
    assert out["missing"]["reason"] == "permit_required"
    assert out["wrong_robot"]["reason"] == "wrong_robot"
    assert out["expired"]["reason"] == "permit_expired"
    assert all(out[k]["rejected"] for k in ("altered", "forged", "missing", "wrong_robot", "expired"))
    assert out["stop"]["ok"] is True   # stopping never needs a permit


def test_estop_blocks_even_valid_permits_until_signed_release(authority, sim):
    async def go():
        engaged = await sim.estop(engaged=True, reason="test")
        action, token = await _issue(authority, sim, {"x": 6.0, "y": 3.5, "max_speed": 0.3})
        blocked = await sim.send_command(_raw_command(action, token))
        with pytest.raises(httpx.HTTPStatusError):
            await sim.estop(engaged=False, release_token="not-a-token")
        wrong = None
        try:
            await sim.estop(engaged=False, release_token=wire.release_token(SECRET.encode(), "robot-1"))
        except httpx.HTTPStatusError as exc:
            wrong = exc.response.status_code      # a one-robot token cannot lift the global stop
        released = await sim.estop(engaged=False, release_token=wire.release_token(SECRET.encode(), "*"))
        action2, token2 = await _issue(authority, sim, {"x": 6.0, "y": 3.5, "max_speed": 0.3})
        after = await authority.dispatch("run-1", action2, token2, sim)
        return engaged, blocked, released, after, wrong

    engaged, blocked, released, after, wrong = run(go())
    assert wrong == 403
    assert engaged["engaged"] is True
    assert blocked["rejected"] and blocked["reason"] == "estop_engaged" and blocked["status"] == 423
    assert released["engaged"] is False
    assert after["ok"] is True


# --- kill switches ------------------------------------------------------------------------

def test_kill_switch_stops_robot_voids_permits_and_survives_restart(authority, sim, tmp_path):
    async def go():
        action, token = await _issue(authority, sim, {"x": 6.0, "y": 3.5, "max_speed": 0.3})
        report = await authority.kill("robot", "robot-1", reason="test", actor="op", sim=sim)
        with pytest.raises(Rejected, match="kill"):
            await authority.dispatch("run-1", action, token, sim)
        restarted = ExecutionAuthority(secret=SECRET, db_path=authority.db_path)
        await _observe(restarted, sim)
        with pytest.raises(Rejected, match="kill"):
            restarted.authorize(run_id="r", mission_id="m", intent="MOVE_TO", params={"x": 6, "y": 3.5},
                                decision="APPROVED", policy_version="v1")
        tel = await sim.get_telemetry()
        reset = await restarted.reset("robot", "robot-1", actor="op", sim=sim)
        return report, tel, reset, restarted

    report, tel, reset, restarted = run(go())
    assert report["stop_verified"] is True and report["controller"]["engaged"] is True
    assert tel["estop"]["robot"] is not None and tel["estop"]["engaged"] is False   # this robot only
    assert reset["controller_released"] is True and restarted.kill_locks() == []


def test_reset_requires_an_actor(authority, sim):
    async def go():
        await authority.kill("global", "*", reason="test", actor=None, sim=sim)
        with pytest.raises(Rejected, match="authorization"):
            await authority.reset("global", "*", actor="", sim=sim)
        return await authority.reset("global", "*", actor="op", sim=sim)

    assert run(go())["reset"] is True


def test_mission_kill_blocks_only_that_mission(authority, sim):
    async def go():
        await authority.kill("mission", "mis-1", reason="test", actor="op", sim=sim)
        await _observe(authority, sim)
        with pytest.raises(Rejected, match="kill"):
            authority.authorize(run_id="r", mission_id="mis-1", intent="MOVE_TO", params={"x": 6, "y": 3.5},
                                decision="APPROVED", policy_version="v1")
        authority.authorize(run_id="r", mission_id="mis-2", intent="MOVE_TO", params={"x": 6, "y": 3.5},
                            decision="APPROVED", policy_version="v1")

    run(go())


# --- authorization rules ---------------------------------------------------------------------

def test_no_secret_means_nothing_moves(tmp_path):
    a = ExecutionAuthority(secret="", db_path=str(tmp_path / "a.db"))
    a.observe({"x": 0})
    with pytest.raises(Rejected, match="not_configured"):
        a.authorize(run_id="r", mission_id="m", intent="MOVE_TO", params={}, decision="APPROVED", policy_version="v")


def test_only_approved_decisions_get_permits(authority):
    authority.observe({"x": 0})
    for decision in ("DENIED", "NEEDS_REVIEW"):
        with pytest.raises(Rejected, match="denied"):
            authority.authorize(run_id="r", mission_id="m", intent="MOVE_TO", params={}, decision=decision,
                                policy_version="v")


def test_stale_world_state_gets_no_permit(tmp_path):
    a = ExecutionAuthority(secret=SECRET, db_path=str(tmp_path / "a.db"), max_age_s=0.05)
    a.observe({"x": 0})
    time.sleep(0.1)
    with pytest.raises(Rejected, match="stale"):
        a.authorize(run_id="r", mission_id="m", intent="MOVE_TO", params={}, decision="APPROVED", policy_version="v")


def test_lost_acknowledgement_is_settled_from_controller_state(authority, sim):
    class LosesAck:
        """Delivers the command, then loses the answer."""
        def __init__(self, inner):
            self.inner = inner

        async def send_command(self, cmd):
            await self.inner.send_command(cmd)
            raise httpx.ReadTimeout("lost")

    async def go():
        action, token = await _issue(authority, sim, {"x": 7.0, "y": 3.5, "max_speed": 0.3})
        with pytest.raises(Rejected, match="unknown"):
            await authority.dispatch("run-1", action, token, LosesAck(sim))
        in_doubt = authority.checkpoints.in_doubt("mis-1")
        settled = authority.reconcile_in_doubt("mis-1", await sim.get_telemetry())
        # a second lost answer, but this time the command never arrived
        action2, token2 = await _issue(authority, sim, {"x": 9.0, "y": 3.5, "max_speed": 0.3})

        class NeverArrives:
            async def send_command(self, cmd):
                raise httpx.ConnectError("down")

        with pytest.raises(Rejected, match="unknown"):
            await authority.dispatch("run-1", action2, token2, NeverArrives())
        settled2 = authority.reconcile_in_doubt("mis-1", await sim.get_telemetry())
        return action, in_doubt, settled, settled2

    action, in_doubt, settled, settled2 = run(go())
    assert in_doubt == [action.action_id]
    assert settled == [{"action_id": action.action_id, "executed": True}]
    assert settled2[0]["executed"] is False
    assert authority.checkpoints.in_doubt("mis-1") == [] and authority.checkpoints.verify_chain()


# --- the API -----------------------------------------------------------------------------------

class _StopSim:
    def __init__(self):
        self.calls = []

    async def estop(self, **kw):
        self.calls.append(("estop", kw.get("engaged")))
        return {"ok": True, "engaged": kw.get("engaged")}

    async def send_command(self, cmd):
        self.calls.append(("command", cmd["intent"]))
        return {"ok": True}

    async def get_telemetry(self):
        return {"speed": 0.0, "target": None}


def test_kill_api_open_but_reset_needs_login(monkeypatch, tmp_path):
    import app.services.execution_authority as ea
    import app.api.routes_runs as rr
    from app.auth.jwt import create_access_token
    from app.main import app

    monkeypatch.setattr(ea, "_authority", ExecutionAuthority(secret=SECRET, db_path=str(tmp_path / "api.db")))
    fake = _StopSim()
    monkeypatch.setattr(rr.get_run_svc(), "sim", fake)
    client = TestClient(app)

    r = client.post("/authority/kill", json={"scope": "global", "reason": "drill"})
    assert r.status_code == 200 and r.json()["stop_verified"] is True
    assert client.get("/authority/status").json()["kill_locks"][0]["scope"] == "global"
    assert client.post("/authority/reset", json={"scope": "global"}).status_code == 401
    assert client.post("/authority/kill", json={"scope": "robot"}).status_code == 422
    viewer = {"Authorization": f"Bearer {create_access_token('watcher', role='viewer')}"}
    assert client.post("/authority/reset", json={"scope": "global"}, headers=viewer).status_code == 403
    headers = {"Authorization": f"Bearer {create_access_token('operator-1', role='operator')}"}
    r = client.post("/authority/reset", json={"scope": "global"}, headers=headers)
    assert r.status_code == 200 and r.json()["controller_released"] is True
    assert client.post("/authority/reset", json={"scope": "global"}, headers=headers).status_code == 404
    assert ("estop", True) in fake.calls and ("estop", False) in fake.calls


# --- the live run loop ------------------------------------------------------------------------

class PermitCheckingSim:
    """A clear aisle. Accepts a move only with a valid, unused permit for exactly that move."""

    def __init__(self):
        self.moves, self.refused, self.seen = [], [], set()
        self.x = 3.0

    async def get_telemetry(self):
        return {"x": self.x, "y": 3.5, "theta": 0.0, "speed": 0.3, "zone": "aisle", "nearest_obstacle_m": 2.5,
                "nearest_obstacle_xy": [3.0, 1.0], "human_detected": False, "human_conf": 0.0,
                "human_distance_m": 999.0, "walking_humans": [], "events": [], "target": None}

    async def get_world(self):
        from bench.world import load_layout
        return dict(load_layout(), walking_humans=[], idle_robots=[])

    async def send_command(self, cmd):
        if cmd["intent"] != "MOVE_TO":
            return {"ok": True, "stopped": True}
        try:
            payload = wire.verify_for_action(SECRET.encode(), cmd.get("permit") or "",
                                             dict(cmd.get("action") or {}, kind=cmd["intent"], params=cmd["params"]))
            assert payload["id"] not in self.seen, "permit reused"
            self.seen.add(payload["id"])
        except (wire.PermitError, AssertionError) as exc:
            self.refused.append(str(exc))
            return {"ok": False, "rejected": True, "reason": str(exc)}
        self.moves.append(cmd)
        self.x = min(self.x + 0.3, 12.0)
        return {"ok": True, "set_target": cmd["params"]}

    async def reset_robot(self):
        return {"ok": True}

    async def close(self):
        return None


def test_run_loop_sends_only_permitted_moves(monkeypatch):
    """The real app under uvicorn (the run loop needs a live event loop) with a permit-checking simulator."""
    import socket
    import threading

    import uvicorn

    import app.api.routes_runs as rr
    from app.main import app

    monkeypatch.setattr(app, "dependency_overrides", {})
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    fake = PermitCheckingSim()
    try:
        deadline = time.time() + 30
        while not server.started and time.time() < deadline:
            time.sleep(0.1)
        monkeypatch.setattr(rr.get_run_svc(), "sim", fake)
        client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30)
        mid = client.post("/missions", json={"title": "Permitted moves", "bay_id": "B-03"}).json()["id"]
        rid = client.post(f"/missions/{mid}/start").json()["run_id"]
        deadline = time.time() + 25
        while time.time() < deadline and len(fake.moves) < 3:
            time.sleep(0.2)
        client.post(f"/runs/{rid}/stop")
        events = client.get(f"/runs/{rid}/events").json()
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert len(fake.moves) >= 3, [(e["type"], str(e["payload"])[:160]) for e in events][-15:]
    assert fake.refused == []
    used = [e for e in events if e["type"] == "AUTHORITY"
            and (e["payload"] if isinstance(e["payload"], dict) else json.loads(e["payload"])).get("event") == "permit_used"]
    assert len(used) >= 3


# --- controller dead-man stop and approval expiry -------------------------------------------------

def test_simulator_brakes_when_permitted_moves_stop_arriving(authority, sim, sim_module, monkeypatch):
    monkeypatch.setattr(sim_module, "SIM_DEADMAN_S", 0.4)

    async def go():
        before = (await sim.get_telemetry())["deadman_trips"]
        action, token = await _issue(authority, sim, {"x": 10.0, "y": 3.5, "max_speed": 0.3})
        assert (await authority.dispatch("run-1", action, token, sim))["ok"]
        moving = await sim.get_telemetry()
        await asyncio.sleep(1.0)   # the backend "dies": no further moves
        return before, moving, await sim.get_telemetry()

    before, moving, after = run(go())
    assert moving["target"] is not None
    assert after["target"] is None and after["deadman_trips"] == before + 1


def test_operator_approval_expires(monkeypatch):
    from datetime import datetime, timedelta, timezone

    import app.services.operator_approval as oa
    from app.db.models import OperatorApproval
    from conftest import _TestSession

    monkeypatch.setattr(oa, "SessionLocal", _TestSession)
    oa.approve("run-exp", "hash-1", approved_by="op")
    assert oa.is_approved("run-exp", "hash-1")
    db = _TestSession()
    try:
        row = db.query(OperatorApproval).filter(OperatorApproval.run_id == "run-exp").one()
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
        assert not oa.is_approved("run-exp", "hash-1")
        db.query(OperatorApproval).filter(OperatorApproval.run_id == "run-exp").delete()
        db.commit()
    finally:
        db.close()


# --- full-path check before a permit ---------------------------------------------------------------

def test_permit_refused_when_the_path_runs_through_a_person_or_obstacle(authority):
    base = {"x": 3.0, "y": 3.5, "bounds": {"min_x": 0, "min_y": 0, "max_x": 40, "max_y": 25}}
    cases = [
        ({"walking_humans": [{"x": 6.0, "y": 3.6}]}, "person"),        # walking straight through someone
        ({"obstacles": [{"x": 6.0, "y": 3.5, "r": 0.4, "type": "dropped_pallet"}]}, "obstacle"),
        ({"site_constraints": [{"x": 6.0, "y": 3.5, "radius": 1.0, "slow_radius": 2.0, "max_speed": 0.2}]}, "hazard"),
    ]
    for extra, kind in cases:
        authority.observe({**base, **extra})
        with pytest.raises(Rejected, match=f"trajectory_{kind}_clearance"):
            authority.authorize(run_id="r", mission_id="m", intent="MOVE_TO", params={"x": 9.0, "y": 3.5},
                                decision="APPROVED", policy_version="v")
    authority.observe(base)
    with pytest.raises(Rejected, match="out_of_bounds"):
        authority.authorize(run_id="r", mission_id="m", intent="MOVE_TO", params={"x": 45.0, "y": 3.5},
                            decision="APPROVED", policy_version="v")


def test_robot_already_close_can_still_back_away(authority):
    # A person 0.8 m away (inside the 1 m stop radius): moving away is allowed, moving closer is not
    authority.observe({"x": 3.0, "y": 3.5, "walking_humans": [{"x": 3.8, "y": 3.5}]})
    authority.authorize(run_id="r", mission_id="m", intent="MOVE_TO", params={"x": 1.5, "y": 3.5},
                        decision="APPROVED", policy_version="v")
    authority.observe({"x": 3.0, "y": 3.5, "walking_humans": [{"x": 3.8, "y": 3.5}]})
    with pytest.raises(Rejected, match="person"):
        authority.authorize(run_id="r", mission_id="m", intent="MOVE_TO", params={"x": 3.5, "y": 3.5},
                            decision="APPROVED", policy_version="v")


# --- security drills against the real simulator ----------------------------------------------------

def test_security_drills_all_pass_against_the_real_simulator(authority, sim, monkeypatch, tmp_path):
    import app.services.route_learning as rl
    from app.services.drills import run_drills
    monkeypatch.setattr(rl, "_memory", rl.RouteMemory(db_path=str(tmp_path / "exp.db"), secret=SECRET.encode()))
    names = ["bypass", "tamper", "replay", "forged", "poison", "injection", "kill"]   # canary needs a live model
    result = run(run_drills(authority, sim, names))
    assert result["all_passed"], result["results"]
    assert [r["drill"] for r in result["results"]] == names
    assert authority.kill_locks() == []          # the kill drill reset its own lock
    assert rl._memory.status()["quarantined"] == 0   # the planted record was removed


# --- metrics ----------------------------------------------------------------------------------------

def test_metrics_endpoint_counts_the_safety_path(authority, sim, monkeypatch):
    import app.services.execution_authority as ea
    from app.main import app
    monkeypatch.setattr(ea, "_authority", authority)

    async def go():
        action, token = await _issue(authority, sim, {"x": 6.0, "y": 3.5, "max_speed": 0.3})
        await authority.dispatch("run-1", action, token, sim)
        await authority.kill("robot", "robot-1", reason="metrics", actor="op", sim=sim)
        await _observe(authority, sim)
        with pytest.raises(Rejected):
            authority.authorize_or_count(run_id="r", mission_id="m", intent="MOVE_TO", params={"x": 6, "y": 3.5},
                                         decision="APPROVED", policy_version="v")
        await authority.reset("robot", "robot-1", actor="op", sim=sim)

    run(go())
    text = TestClient(app).get("/metrics").text
    for needle in ("permits_issued_total", 'dispatch_total{outcome="accepted"}', 'kill_switch_total{scope="robot"}',
                   'permits_refused_total{reason="kill_switch_active"}', "kill_revoke_ms_count", "permits_enforced 1"):
        assert needle in text, needle
