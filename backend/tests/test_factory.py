"""The factory site: machines, welding cell and assembly line are solid, routes go round
them, the gate refuses moves through them, and the live simulator runs the site."""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.policies.rules_python import evaluate_policies
from app.policies import site_map
from app.policies.site_map import _racks_from_world, path_blocked
from app.schemas.governance import ActionProposal
from bench.world import Layout, load_layout

SITE = load_layout(site="factory")
SECRET = os.environ["PERMIT_SECRET"]


def test_factory_layout_is_complete():
    kinds = {r["kind"] for r in SITE["racks"]}
    assert kinds == {"rack", "machine", "cell", "conveyor"}
    ids = {b["id"] for b in SITE["bays"]}
    assert {"P-01", "L-01", "L-05", "Q-01", "D-04"} <= ids
    assert {p["bay"] for p in SITE["presets"]} <= ids
    assert [z["label"] for z in SITE["zones"]] == ["Raw-material stores", "Transport corridor",
                                                   "Production floor", "QC and dispatch"]


def test_every_destination_reachable_from_both_parking_spots():
    L = Layout(SITE)
    for start in SITE["parking"].values():
        for b in SITE["bays"]:
            assert L.route(tuple(start), (b["x"], b["y"])), (start, b["id"])


def test_routes_go_round_the_machines():
    from app.services.site_router import route_plan
    from app.world_model import ZONE_SPEED_LIMITS
    wps = route_plan(SITE, {"x": 6.0, "y": 3.5}, {"x": 24.0, "y": 18.6}, ZONE_SPEED_LIMITS)   # stores -> welding infeed
    assert wps
    prev = {"x": 6.0, "y": 3.5}
    for wp in wps:
        assert path_blocked(prev["x"], prev["y"], wp["x"], wp["y"], _racks_from_world(SITE)) is None
        prev = wp


def test_gate_checks_the_site_the_simulator_runs(monkeypatch):
    """Regression: the gate's racking rule used to be fixed to the warehouse map."""
    assert path_blocked(20.0, 15.0, 28.0, 15.0, _racks_from_world(SITE)) == "C-WELD"
    monkeypatch.setattr(site_map, "RACKS", site_map.RACKS)       # restored after the test
    monkeypatch.setattr(site_map, "SITE_NAME", site_map.SITE_NAME)
    site_map.use_world(dict(SITE, site={"name": "factory"}))
    assert site_map.SITE_NAME == "factory"
    tel = {"x": 20.0, "y": 18.6, "zone": "staging", "nearest_obstacle_m": 1.2, "human_detected": False,
           "human_distance_m": 999}
    through_cell = evaluate_policies(tel, ActionProposal(intent="MOVE_TO", params={"x": 27.5, "y": 14.0, "max_speed": 0.2}))
    assert through_cell.decision == "DENIED" and "PATH_CLEARANCE_07" in through_cell.policy_hits
    along_floor = evaluate_policies(tel, ActionProposal(intent="MOVE_TO", params={"x": 27.5, "y": 18.6, "max_speed": 0.2}))
    assert "PATH_CLEARANCE_07" not in along_floor.policy_hits


@pytest.fixture(scope="module")
def factory_sim():
    sim_dir = str(Path(__file__).resolve().parents[2] / "sim" / "warehouse_sim")
    old = os.environ.get("SITE_LAYOUT")
    os.environ["SITE_LAYOUT"] = "factory"
    sys.path.insert(0, sim_dir)
    sys.modules.pop("server", None)
    try:
        server = importlib.import_module("server")
        with TestClient(server.app) as c:
            yield server, c
    finally:
        sys.path.remove(sim_dir)
        sys.modules.pop("server", None)
        sys.modules.pop("camera", None)
        if old is None:
            os.environ.pop("SITE_LAYOUT", None)
        else:
            os.environ["SITE_LAYOUT"] = old


def test_live_simulator_runs_the_factory(factory_sim):
    server, c = factory_sim
    world = c.get("/world").json()
    assert world["site"] == {"name": "factory", "title": "Precision parts factory"}
    assert any(r["kind"] == "cell" for r in world["racks"]) and world["presets"]
    fleet = c.get("/fleet").json()["robots"]
    assert {(r["robot_id"], r["x"], r["y"]) for r in fleet} == {("robot-1", 3.0, 3.5), ("robot-2", 3.0, 21.5)}
    w = server._world()
    assert any(v.kind == "forklift" for v in w.walkers)
    assert sum(1 for v in w.walkers if v.kind == "person") >= 3
    png = c.get("/frame?size=256")
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"


def test_permitted_move_on_the_factory_floor(factory_sim, tmp_path):
    from app.services.execution_authority import ExecutionAuthority
    from app.services.sim_adapter import SimAdapter
    server, _ = factory_sim
    server._estop.update(engaged=False, reason="", since=None)
    adapter = SimAdapter(base_url="http://sim")
    adapter._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://sim")
    authority = ExecutionAuthority(secret=SECRET, db_path=str(tmp_path / "f.db"))

    async def go():
        tel = await adapter.get_telemetry()
        tel["walking_humans"] = []
        authority.observe(tel)
        action, token = authority.authorize(run_id="f", mission_id="mf", intent="MOVE_TO",
                                            params={"x": 9.0, "y": 3.5, "max_speed": 0.3},
                                            decision="APPROVED", policy_version="v")
        return await authority.dispatch("f", action, token, adapter), await adapter.get_telemetry()

    result, tel = asyncio.run(go())
    assert result["ok"] and tel["target"]["x"] == pytest.approx(9.0) and tel["zone"] == "aisle"


def test_backend_startup_syncs_the_gate_with_the_simulator(monkeypatch):
    """Regression: the startup sync silently failed (asyncio was a local name in lifespan)."""
    import app.api.routes_runs as rr
    from app.main import app
    seen = []

    class Sim:
        async def get_world(self):
            seen.append(1)
            site_map.use_world(dict(SITE, site={"name": "factory"}))
            return SITE

        async def close(self):
            return None

    monkeypatch.setattr(site_map, "RACKS", site_map.RACKS)
    monkeypatch.setattr(site_map, "SITE_NAME", None)
    monkeypatch.setattr(rr.get_run_svc(), "sim", Sim())
    with TestClient(app) as c:
        assert seen == [1]
        assert c.get("/health").json()["site"] == "factory"
