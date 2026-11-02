"""Two robots: each has its own permits, e-stop and telemetry, they see each other as
obstacles, path reservations never overlap, and a robot runs one mission at a time."""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.autonomy import permit as wire
from app.autonomy.core import Rejected
from app.services.execution_authority import ExecutionAuthority
from app.services.run_service import RobotView
from app.services.sim_adapter import SimAdapter

SECRET = os.environ["PERMIT_SECRET"]


@pytest.fixture(scope="module")
def sim_module(tmp_path_factory):
    sim_dir = str(Path(__file__).resolve().parents[2] / "sim" / "warehouse_sim")
    sys.path.insert(0, sim_dir)
    sys.modules.pop("server", None)
    try:
        server = importlib.import_module("server")
        from app.autonomy.controller import ControllerJournal
        server._journal = ControllerJournal(str(tmp_path_factory.mktemp("fleet-controller") / "controller.db"))
        server._estop.update(engaged=False, reason="", since=None)
        server._robot_estops.clear()
        with TestClient(server.app):
            yield server
    finally:
        sys.path.remove(sim_dir)
        sys.modules.pop("server", None)
        sys.modules.pop("camera", None)


@pytest.fixture
def sim(sim_module):
    adapter = SimAdapter(base_url="http://sim")
    adapter._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=sim_module.app), base_url="http://sim")
    sim_module._estop.update(engaged=False, reason="", since=None)
    sim_module._robot_estops.clear()
    yield adapter
    sim_module._estop.update(engaged=False, reason="", since=None)
    sim_module._robot_estops.clear()


@pytest.fixture
def authority(tmp_path, sim_module, bind_redemption):
    authority = ExecutionAuthority(secret=SECRET, db_path=str(tmp_path / "fleet.db"))
    bind_redemption(sim_module, authority)
    return authority


def run(coro):
    return asyncio.run(coro)


async def _issue(authority, view, robot, params, mission="mis-f"):
    from app.policies.versioning import policy_version_hash
    tel = await view.get_telemetry()
    tel["walking_humans"] = []                 # permits, not pedestrians, are under test here
    tel["obstacles"] = [o for o in tel["obstacles"] if o.get("type") == "robot"]
    authority.observe(tel, robot_id=robot)
    return authority.authorize(run_id=f"run-{robot}", mission_id=mission, intent="MOVE_TO", params=params,
                               decision="APPROVED", policy_version=policy_version_hash(), robot_id=robot)


# --- the simulator -------------------------------------------------------------------------------

def test_fleet_has_two_robots_that_see_each_other(sim):
    async def go():
        fleet = await sim.get_fleet()
        t1 = await sim.get_telemetry()
        t2 = await RobotView(sim, "robot-2").get_telemetry()
        return fleet, t1, t2

    fleet, t1, t2 = run(go())
    assert [r["robot_id"] for r in fleet["robots"]] == ["robot-1", "robot-2"]
    assert t1["robot_id"] == "robot-1" and t2["robot_id"] == "robot-2"
    assert (t2["x"], t2["y"]) != (t1["x"], t1["y"])
    assert any(o["type"] == "robot" for o in t1["obstacles"]) and any(o["type"] == "robot" for o in t2["obstacles"])


def test_a_permit_moves_only_its_own_robot(authority, sim):
    r2 = RobotView(sim, "robot-2")

    async def go():
        before1 = await sim.get_telemetry()
        action, token = await _issue(authority, r2, "robot-2", {"x": 6.0, "y": 21.5, "max_speed": 0.3})
        result = await authority.dispatch("run-robot-2", action, token, r2)
        t1, t2 = await sim.get_telemetry(), await r2.get_telemetry()
        # the same permit cannot be pointed at robot-1
        body = {"intent": "MOVE_TO", "params": action.params, "permit": token,
                "action": dict({k: v for k, v in action.as_dict().items() if k not in ("kind", "params")}, robot_id="robot-1")}
        swapped = await sim.send_command(body)
        await r2.send_command({"intent": "STOP", "params": {}})
        return before1, result, t1, t2, swapped

    before1, result, t1, t2, swapped = run(go())
    assert result["ok"] and result["robot_id"] == "robot-2"
    assert t2["target"]["x"] == pytest.approx(6.0)
    assert t1["target"] == before1["target"]          # robot-1 untouched
    assert swapped["rejected"] and swapped["reason"] == "action_mismatch"


def test_robot_estop_stops_one_robot_global_stops_all(authority, sim):
    r2 = RobotView(sim, "robot-2")

    async def go():
        await sim.estop(engaged=True, reason="r2", robot_id="robot-2")
        a2, k2 = await _issue(authority, r2, "robot-2", {"x": 5.0, "y": 21.5, "max_speed": 0.3})
        blocked2 = await sim.send_command({"intent": "MOVE_TO", "params": a2.params, "permit": k2,
                                           "action": {k: v for k, v in a2.as_dict().items() if k not in ("kind", "params")}})
        a1, k1 = await _issue(authority, sim, "robot-1", {"x": 4.0, "y": 3.5, "max_speed": 0.3}, mission="mis-1")
        ok1 = await authority.dispatch("run-robot-1", a1, k1, sim)
        with pytest.raises(httpx.HTTPStatusError):    # a robot-1 token cannot release robot-2
            await sim.estop(engaged=False, robot_id="robot-2", release_token=wire.release_token(SECRET.encode(), "robot-1"))
        await sim.estop(engaged=False, robot_id="robot-2", release_token=wire.release_token(SECRET.encode(), "robot-2"))
        await sim.estop(engaged=True, reason="all")
        fleet = await sim.get_fleet()
        await sim.estop(engaged=False, release_token=wire.release_token(SECRET.encode(), "*"))
        return blocked2, ok1, fleet

    blocked2, ok1, fleet = run(go())
    assert blocked2["reason"] == "estop_engaged" and ok1["ok"]
    assert all(r["estopped"] and r["target"] is None for r in fleet["robots"])


def test_kill_switch_scopes_across_the_fleet(authority, sim):
    r2 = RobotView(sim, "robot-2")

    async def go():
        await _issue(authority, r2, "robot-2", {"x": 5.0, "y": 21.5, "max_speed": 0.3}, mission="mis-2")
        report = await authority.kill("mission", "mis-2", reason="mission stop", actor="op", sim=sim)
        await authority.reset("mission", "mis-2", actor="op", sim=sim)
        robot_report = await authority.kill("robot", "robot-2", reason="robot stop", actor="op", sim=sim)
        fleet = await sim.get_fleet()
        await authority.reset("robot", "robot-2", actor="op", sim=sim)
        after = await sim.get_fleet()
        return report, robot_report, fleet, after

    report, robot_report, fleet, after = run(go())
    assert report["robots"] == ["robot-2"] and report["stop_verified"]
    assert robot_report["stop_verified"]
    state = {r["robot_id"]: r["estopped"] for r in fleet["robots"]}
    assert state == {"robot-1": False, "robot-2": True}
    assert not any(r["estopped"] for r in after["robots"])


def test_simulator_dead_man_covers_every_robot(authority, sim, sim_module, monkeypatch):
    monkeypatch.setattr(sim_module, "SIM_DEADMAN_S", 0.4)
    r2 = RobotView(sim, "robot-2")

    async def go():
        before = (await r2.get_telemetry())["deadman_trips"]
        a, k = await _issue(authority, r2, "robot-2", {"x": 8.0, "y": 21.5, "max_speed": 0.3})
        await authority.dispatch("run-robot-2", a, k, r2)
        await asyncio.sleep(1.0)
        return before, await r2.get_telemetry()

    before, after = run(go())
    assert after["target"] is None and after["deadman_trips"] == before + 1


# --- path reservations ------------------------------------------------------------------------------

def _observe(a, robot, x, y):
    a.observe({"x": x, "y": y, "robot_id": robot}, robot_id=robot)


def test_two_robots_cannot_hold_overlapping_paths(authority):
    _observe(authority, "robot-1", 3.0, 3.5)
    authority.authorize(run_id="r1", mission_id="m1", intent="MOVE_TO", params={"x": 12.0, "y": 3.5},
                        decision="APPROVED", policy_version="v", robot_id="robot-1")
    _observe(authority, "robot-2", 8.0, 0.8)
    with pytest.raises(Rejected, match="corridor_conflict"):      # crosses robot-1's path
        authority.authorize(run_id="r2", mission_id="m2", intent="MOVE_TO", params={"x": 8.0, "y": 7.0},
                            decision="APPROVED", policy_version="v", robot_id="robot-2")
    _observe(authority, "robot-2", 3.0, 21.5)
    authority.authorize(run_id="r2", mission_id="m2", intent="MOVE_TO", params={"x": 9.0, "y": 21.5},
                        decision="APPROVED", policy_version="v", robot_id="robot-2")   # far away: fine
    assert set(authority.reservations.held()) == {"robot-1", "robot-2"}


def test_a_new_permit_replaces_the_robots_old_hold(authority):
    _observe(authority, "robot-1", 3.0, 3.5)
    authority.authorize(run_id="r1", mission_id="m1", intent="MOVE_TO", params={"x": 12.0, "y": 3.5},
                        decision="APPROVED", policy_version="v", robot_id="robot-1")
    _observe(authority, "robot-1", 3.0, 3.5)
    authority.authorize(run_id="r1", mission_id="m1", intent="MOVE_TO", params={"x": 3.0, "y": 5.0},
                        decision="APPROVED", policy_version="v", robot_id="robot-1")   # robot-1 turns away
    _observe(authority, "robot-2", 8.0, 0.8)
    authority.authorize(run_id="r2", mission_id="m2", intent="MOVE_TO", params={"x": 8.0, "y": 7.0},
                        decision="APPROVED", policy_version="v", robot_id="robot-2")


def test_reservation_contention_has_one_winner(authority):
    """Robots racing for the same aisle at the same moment: exactly one gets it."""
    wins, losses = [], []
    for k in range(6):
        _observe(authority, f"robot-{k}", 3.0, 3.5 + 0.01 * k)

    def go(k):
        try:
            authority.authorize(run_id=f"r{k}", mission_id=f"m{k}", intent="MOVE_TO", params={"x": 12.0, "y": 3.5},
                                decision="APPROVED", policy_version="v", robot_id=f"robot-{k}")
            wins.append(k)
        except Rejected:
            losses.append(k)

    threads = [threading.Thread(target=go, args=(k,)) for k in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(wins) == 1 and len(losses) == 5


# --- missions ---------------------------------------------------------------------------------------

def test_a_robot_runs_one_mission_at_a_time(monkeypatch):
    import app.api.routes_runs as rr
    from app.db.models import Mission, Run
    from app.main import app
    from conftest import _TestSession

    class Sim:
        async def reset_robot(self, robot_id=None):
            return {"ok": True}

        async def get_telemetry(self, robot_id=None):
            return {"x": 3.0, "y": 3.5}

        async def get_world(self):
            return {}

        async def send_command(self, cmd):
            return {"ok": True}

    svc = rr.get_run_svc()
    monkeypatch.setattr(svc, "sim", Sim())
    client = TestClient(app)
    m1 = client.post("/missions", json={"title": "r2 a", "bay_id": "B-03", "robot_id": "robot-2"}).json()
    m2 = client.post("/missions", json={"title": "r2 b", "bay_id": "B-04", "robot_id": "robot-2"}).json()
    assert m1["goal"]["robot_id"] == "robot-2"
    db = _TestSession()
    try:
        from app.utils.time import utc_now
        db.add(Run(id="run_busy_r2", mission_id=m1["id"], status="running", started_at=utc_now(), planning_mode="fallback"))
        db.commit()
        r = client.post(f"/missions/{m2['id']}/start")
        assert r.status_code == 409 and "robot-2" in r.json()["detail"]
    finally:
        db.query(Run).filter(Run.mission_id.in_([m1["id"], m2["id"]])).delete(synchronize_session=False)
        db.query(Mission).filter(Mission.id.in_([m1["id"], m2["id"]])).delete(synchronize_session=False)
        db.commit()
        db.close()
        svc._run_robot.pop("run_busy_r2", None)


class FleetFakeSim:
    """Two robots on a clear aisle; accepts a move only with a valid, unused permit for that robot."""

    def __init__(self):
        self.pos = {"robot-1": [3.0, 3.5], "robot-2": [3.0, 21.5]}
        self.moves, self.refused, self.seen = [], [], set()
        self.robot1_commands = []

    async def get_telemetry(self, robot_id=None):
        rid = robot_id or "robot-1"
        x, y = self.pos[rid]
        return {"robot_id": rid, "x": x, "y": y, "theta": 0.0, "speed": 0.3, "zone": "aisle",
                "nearest_obstacle_m": 2.5, "nearest_obstacle_xy": [x, y - 2], "human_detected": False,
                "human_conf": 0.0, "human_distance_m": 999.0, "walking_humans": [], "events": [], "target": None}

    async def get_world(self):
        from bench.world import load_layout
        return dict(load_layout(), walking_humans=[], idle_robots=[])

    async def send_command(self, cmd):
        rid = cmd.get("robot_id") or (cmd.get("action") or {}).get("robot_id") or "robot-1"
        if rid == "robot-1":
            self.robot1_commands.append(cmd)
        if cmd["intent"] != "MOVE_TO":
            return {"ok": True, "stopped": True}
        try:
            action = dict(cmd.get("action") or {}, kind=cmd["intent"], params=cmd["params"])
            payload = wire.verify_for_action(SECRET.encode(), cmd.get("permit") or "", action)
            assert payload["id"] not in self.seen
            self.seen.add(payload["id"])
        except (wire.PermitError, AssertionError) as exc:
            self.refused.append(str(exc))
            return {"ok": False, "rejected": True, "reason": str(exc)}
        self.moves.append((action["robot_id"], cmd["params"]))
        self.pos[action["robot_id"]][0] = min(self.pos[action["robot_id"]][0] + 0.3, 12.0)
        return {"ok": True, "set_target": cmd["params"]}

    async def reset_robot(self, robot_id=None):
        return {"ok": True}

    async def get_frame(self, size=512, robot_id=None):
        raise RuntimeError("no camera in this test")

    async def close(self):
        return None


def test_a_mission_on_robot_2_drives_only_robot_2(monkeypatch):
    import socket
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
    fake = FleetFakeSim()
    try:
        deadline = time.time() + 30
        while not server.started and time.time() < deadline:
            time.sleep(0.1)
        monkeypatch.setattr(rr.get_run_svc(), "sim", fake)
        client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30)
        mid = client.post("/missions", json={"title": "Robot two", "bay_id": "B-03", "robot_id": "robot-2"}).json()["id"]
        rid = client.post(f"/missions/{mid}/start").json()["run_id"]
        deadline = time.time() + 25
        while time.time() < deadline and len(fake.moves) < 3:
            time.sleep(0.2)
        client.post(f"/runs/{rid}/stop")
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert len(fake.moves) >= 3 and fake.refused == []
    assert {robot for robot, _ in fake.moves} == {"robot-2"}
    assert fake.robot1_commands == []          # robot-1 never received a command


def test_a_robot_never_sees_itself_as_an_obstacle(sim):
    """Regression: robot-2's view must list robot-1 as the other robot, not robot-2 itself."""
    async def go():
        return await sim.get_telemetry(), await RobotView(sim, "robot-2").get_telemetry()

    t1, t2 = run(go())
    others2 = [o for o in t2["obstacles"] if o["type"] == "robot"]
    others1 = [o for o in t1["obstacles"] if o["type"] == "robot"]
    assert len(others2) == 1 and (others2[0]["x"], others2[0]["y"]) == (round(t1["x"], 2), round(t1["y"], 2))
    assert len(others1) == 1 and (others1[0]["x"], others1[0]["y"]) == (round(t2["x"], 2), round(t2["y"], 2))
    assert t2["nearest_obstacle_m"] > 0.5


def test_unknown_bay_is_refused_not_sent_to_the_corner():
    from app.main import app
    client = TestClient(app)
    r = client.post("/missions", json={"title": "Nowhere", "bay_id": "B-99"})
    assert r.status_code == 422 and "B-99" in r.json()["detail"]
    ok = client.post("/missions", json={"title": "Real bay", "bay_id": "B-03"}).json()
    assert (ok["goal"]["x"], ok["goal"]["y"]) != (0.0, 0.0)
    client.delete(f"/missions/{ok['id']}")
