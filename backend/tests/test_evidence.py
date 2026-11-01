"""Evidence endpoints: committed benchmark summaries and live learning / task-drift counts."""
from fastapi.testclient import TestClient

from app.main import app


def test_benchmarks_serve_committed_results():
    d = TestClient(app).get("/evidence/benchmarks").json()
    ids = {s["id"] for s in d["suites"]}
    assert {"rule_based", "reckless"} <= ids
    rb = next(s for s in d["suites"] if s["id"] == "rule_based")
    assert rb["totals"]["governed"]["unsafe_executed"] == 0


def test_learning_summary_has_all_counts():
    d = TestClient(app).get("/evidence/learning").json()
    for k in ("lessons", "lessons_by_policy", "plans_with_lessons", "lessons_used", "replans", "task_checks", "drift_caught"):
        assert k in d
    assert d["drift_caught"] <= d["task_checks"]
