"""Live run loop + live simulator: aisle routing, path rule, denials stop the robot,
nothing executes on NEEDS_REVIEW without a fresh approval."""
from __future__ import annotations

import importlib
import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.policies.rules_python import evaluate_policies
from app.policies.site_map import path_blocked
from app.schemas.governance import ActionProposal
from bench.world import load_layout

SITE = load_layout()


# -- path rule ---------------------------------------------------------------------------

def test_path_through_racking_is_detected():
    assert path_blocked(3, 3.5, 16, 23) == "RB-1"
    assert path_blocked(3, 3.5, 10, 3.5) is None           # along aisle A
    assert path_blocked(12.5, 3.5, 12.5, 13.5) is None     # down the cross-aisle


def test_gate_refuses_a_move_through_racking():
    tel = {"x": 3.0, "y": 3.5, "zone": "aisle", "nearest_obstacle_m": 1.1, "human_detected": False,
           "human_distance_m": 999}
    d = evaluate_policies(tel, ActionProposal(intent="MOVE_TO", params={"x": 16, "y": 23, "max_speed": 0.3}))
    assert d.decision == "DENIED" and d.hard_fail and "PATH_CLEARANCE_07" in d.policy_hits
    ok = evaluate_policies(tel, ActionProposal(intent="MOVE_TO", params={"x": 10, "y": 3.5, "max_speed": 0.3}))
    assert ok.decision == "APPROVED"


# -- routing ---------------------------------------------------------------------------------

def test_route_plan_follows_the_aisles():
    from app.services.site_router import route_plan
    from app.world_model import ZONE_SPEED_LIMITS
    wps = route_plan(SITE, {"x": 3, "y": 3.5}, {"x": 16, "y": 23}, ZONE_SPEED_LIMITS)
    assert wps and wps[-1]["x"] == pytest.approx(16) and wps[-1]["y"] == pytest.approx(23)
    prev = {"x": 3, "y": 3.5}
    for wp in wps:
        assert path_blocked(prev["x"], prev["y"], wp["x"], wp["y"]) is None
        prev = wp


def test_repair_plan_keeps_model_waypoints_and_reroutes_bad_legs():
    from app.services.site_router import repair_plan
    from app.world_model import ZONE_SPEED_LIMITS
    model_plan = [{"x": 16.0, "y": 23.0, "max_speed": 0.4}]
    fixed, n = repair_plan(SITE, {"x": 3, "y": 3.5}, model_plan, ZONE_SPEED_LIMITS)
    assert n == 1 and fixed[-1] == model_plan[0] and len(fixed) > 1


# -- the live simulator --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sim_client():
    sim_dir = str(Path(__file__).resolve().parents[2] / "sim" / "warehouse_sim")
    sys.path.insert(0, sim_dir)
    try:
        server = importlib.import_module("server")
        with TestClient(server.app) as c:
            yield c
    finally:
        sys.path.remove(sim_dir)
        sys.modules.pop("server", None)
        sys.modules.pop("camera", None)


def test_live_sim_api(sim_client):
    assert sim_client.get("/health").json()["engine"] == "bench.world"
    world = sim_client.get("/world").json()
    assert len(world["racks"]) == 9 and len(world["bays"]) == 20
    tel = sim_client.get("/telemetry").json()
    for key in ("x", "y", "zone", "nearest_obstacle_m", "nearest_obstacle_xy", "human_distance_m", "walking_humans"):
        assert key in tel
    assert tel["nearest_obstacle_m"] >= 0
    assert sim_client.post("/command", json={"intent": "MOVE_TO", "params": {"x": 99, "y": 1}}).json()["ok"] is False
    assert sim_client.post("/scenario", json={"scenario": "spill"}).json()["ok"] is True
    assert any(o["type"] == "spill" for o in sim_client.get("/world").json()["obstacles"])
    seed = sim_client.post("/seed", json={"seed": 2043}).json()
    assert seed["mode"] == "benchmark" and seed["goal"]["bay"]
    png = sim_client.get("/frame?size=256")
    assert png.headers["content-type"] == "image/png" and png.content[:4] == b"\x89PNG"
    sim_client.post("/seed", json={"seed": 42, "mode": "live"})


# -- the live run loop ----------------------------------------------------------------------------

class FakeSim:
    """A robot pinned in aisle A with a person 0.5 m away: every move must be refused."""

    def __init__(self):
        self.commands = []

    async def get_telemetry(self):
        return {"x": 3.0, "y": 3.5, "theta": 0.0, "speed": 0.0, "zone": "aisle", "nearest_obstacle_m": 1.1,
                "nearest_obstacle_xy": [3.0, 2.0], "human_detected": True, "human_conf": 0.9,
                "human_distance_m": 0.5, "walking_humans": [{"x": 3.5, "y": 3.5, "conf": 0.9}], "events": []}

    async def get_world(self):
        return dict(SITE, walking_humans=[], idle_robots=[])

    async def send_command(self, cmd):
        self.commands.append(cmd)
        return {"ok": True, "stopped": cmd["intent"] == "STOP"}

    async def reset_robot(self):
        return {"ok": True}

    async def close(self):
        return None


def test_denied_moves_stop_the_robot_and_never_execute(monkeypatch):
    """Runs the real app under uvicorn (the run loop needs a live event loop) with a fake simulator."""
    import socket
    import threading

    import httpx
    import uvicorn

    import app.api.routes_runs as rr
    from app.main import app

    # The run loop's background tasks use the app's own database session, so the requests
    # must too (the shared test fixture points requests at an in-memory database).
    monkeypatch.setattr(app, "dependency_overrides", {})
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    fake = FakeSim()
    try:
        deadline = time.time() + 30
        while not server.started and time.time() < deadline:
            time.sleep(0.1)
        monkeypatch.setattr(rr.get_run_svc(), "sim", fake)
        client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30)
        mid = client.post("/missions", json={"title": "Live safety", "bay_id": "B-03"}).json()["id"]
        rid = client.post(f"/missions/{mid}/start").json()["run_id"]
        deadline = time.time() + 20
        while time.time() < deadline and sum(c["intent"] == "STOP" for c in fake.commands) < 2:
            time.sleep(0.2)
        client.post(f"/runs/{rid}/stop")
        events = client.get(f"/runs/{rid}/events").json()
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    plan = next(e for e in events if e["type"] == "PLAN")
    plan = plan["payload"] if isinstance(plan["payload"], dict) else json.loads(plan["payload"])
    assert len(plan["plan"]["waypoints"]) > 1                          # routed along the aisles
    assert not [c for c in fake.commands if c["intent"] == "MOVE_TO"]  # nothing unapproved ran
    assert sum(c["intent"] == "STOP" for c in fake.commands) >= 2, (fake.commands, _debug_events(events))
    decisions = [e for e in events if e["type"] == "DECISION"]
    assert decisions and all(
        (e["payload"] if isinstance(e["payload"], dict) else json.loads(e["payload"]))["governance"]["decision"] != "APPROVED"
        for e in decisions)


def _debug_events(events):
    return [(e["type"], str(e["payload"])[:150]) for e in events]
