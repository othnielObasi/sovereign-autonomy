"""POST /plans/check: the task-drift guard on a submitted plan, with no side effects."""
from fastapi.testclient import TestClient

from app.api import routes_sim
from app.main import app
from bench.world import load_layout

START = {"x": 3, "y": 3.5}
GOAL = {"x": 16, "y": 23}


class _Sim:
    async def get_world(self):
        return load_layout()


def test_wrong_destination_is_rejected_and_replaced(monkeypatch):
    monkeypatch.setattr(routes_sim, "sim", _Sim())
    r = TestClient(app).post("/plans/check", json={"start": START, "goal": GOAL,
                                                   "waypoints": [{"x": 12.5, "y": 3.5}, {"x": 28, "y": 23}]})
    d = r.json()
    assert r.status_code == 200 and d["check"]["verdict"] == "DRIFT" and d["replaced"]
    assert d["used"][-1]["x"] == GOAL["x"] and d["used"][-1]["y"] == GOAL["y"]


def test_on_task_plan_is_kept(monkeypatch):
    monkeypatch.setattr(routes_sim, "sim", _Sim())
    wps = [{"x": 12.5, "y": 3.5}, {"x": 12.5, "y": 13.5}, {"x": 16, "y": 13.5}, {"x": 16, "y": 23}]
    d = TestClient(app).post("/plans/check", json={"start": START, "goal": GOAL, "waypoints": wps}).json()
    assert d["check"]["verdict"] == "ON_TASK" and not d["replaced"]
