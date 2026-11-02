from bench.experience_eval import experiment, write


def test_paired_experiment_is_deterministic_and_rejects_stale_records(tmp_path):
    result = experiment(8, root=tmp_path)
    assert result == experiment(8, root=tmp_path)
    assert result["acceptance"]
    assert result["stale_rejection_rate"] == 1
    assert result["paired_mean_saved_s"] > 0
    assert all(r["restricted_edges"] == 0 and r["model_calls"] == 0 for r in result["rows"])
    for seed in (0, 4):
        rows = {r["condition"]: r for r in result["rows"] if r["seed"] == seed}
        assert rows["disabled"]["modeled_time_s"] == rows["shared"]["modeled_time_s"]
    write(result, tmp_path / "report")
    assert (tmp_path / "report/results.json").exists()
    assert "physical" in (tmp_path / "report/README.md").read_text()
