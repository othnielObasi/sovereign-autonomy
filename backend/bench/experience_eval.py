"""Paired signed-memory experiment on a deterministic two-corridor graph.

This measures routing and modeled queue/travel time, not physical robot safety,
contacts, motor control, or language-model quality. No network/model calls.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import tempfile
from pathlib import Path

from app.autonomy.intelligence import RouteGraph
from app.services.route_learning import RouteMemory

START, QUEUE, GOAL = (0, 0), (1, 0), (2, 0)
UPPER = (1, 1)
CONTEXT = {"site_id": "paired-corridors", "map_version": "layout-v1", "policy_version": "benchmark-v1",
           "capability_profile_version": "graph-amr-v1"}


def graph(delays, *, changed=False):
    g = RouteGraph()
    # The queue's delay is counted once across its two half-edges.
    g.add_edge(START, QUEUE, distance=4, predicted_delay=delays.get(QUEUE, 0) / 2)
    g.add_edge(QUEUE, GOAL, distance=4, predicted_delay=delays.get(QUEUE, 0) / 2, allowed=not changed)
    g.add_edge(START, UPPER, distance=6)
    g.add_edge(UPPER, GOAL, distance=6)
    g.add_edge(START, GOAL, distance=1, allowed=False)  # enticing forbidden shortcut
    return g


def evaluate(g, path, queue_s):
    edges = [g.graph[a][b] for a, b in zip(path, path[1:])]
    return {"completed": path[0] == START and path[-1] == GOAL,
            "modeled_time_s": sum(e["distance"] for e in edges) / 0.5 + (queue_s if QUEUE in path else 0),
            "distance_m": sum(e["distance"] for e in edges),
            "restricted_edges": sum(not e["allowed"] for e in edges), "route": path}


def experiment(seeds=20, first_seed=0, *, root=None):
    if seeds < 2:
        raise ValueError("at least two paired seeds are required")
    rows = []
    # Each seed gets independent acquisition memory. Evaluation never writes it.
    with tempfile.TemporaryDirectory(prefix="experience-eval-", dir=root) as directory:
        for seed in range(first_seed, first_seed + seeds):
            rng = random.Random(seed)
            queue_s = round(rng.uniform(12, 28), 1) if seed % 4 else 0.0
            mem = RouteMemory(str(Path(directory) / f"{seed}.db"), b"benchmark-only-secret-0123456789abcdef",
                              clock=lambda: 1000.0)
            acquisition = graph({}).plan(START, GOAL)["path"]
            observed_queue_s = queue_s if QUEUE in acquisition else 0
            if observed_queue_s:
                # Robot A's verified outcome in this queue model: actual elapsed
                # waiting time, not a planner's predicted performance.
                mem.record(f"robot-A:{seed}", [(QUEUE, observed_queue_s, "STOP")],
                           context=CONTEXT, source_robot_id="robot-A", observed_at=1000.0)
            for condition in ("disabled", "shared", "stale"):
                current = dict(CONTEXT, map_version="layout-v2") if condition == "stale" else CONTEXT
                delays, quarantine = mem.load(context=current)
                decisions = list(mem.last_retrieval)
                used = {} if condition == "disabled" else delays
                g = graph(used, changed=condition == "stale")
                path = g.plan(START, GOAL, delay_weight=0.5)["path"]
                row = dict(evaluate(g, path, queue_s), seed=seed, condition=condition, queue_s=queue_s,
                           acquisition_queue_s=observed_queue_s, acquisition_source="robot-A",
                           accepted_experiences=sum(d["status"] == "accepted" for d in decisions) if condition != "disabled" else 0,
                           excluded_experiences=sum(d["status"] == "excluded" for d in decisions),
                           quarantine=len(quarantine), retrieval=decisions, model_calls=0)
                rows.append(row)
    paired = []
    for seed in range(first_seed, first_seed + seeds):
        trial = {r["condition"]: r for r in rows if r["seed"] == seed}
        paired.append(trial["disabled"]["modeled_time_s"] - trial["shared"]["modeled_time_s"])
    rng = random.Random(0)
    samples = sorted(statistics.mean(rng.choices(paired, k=len(paired))) for _ in range(2000))
    summary = {condition: {
        "completed": sum(r["completed"] for r in rows if r["condition"] == condition),
        "mean_modeled_time_s": statistics.mean(r["modeled_time_s"] for r in rows if r["condition"] == condition),
        "restricted_edges": sum(r["restricted_edges"] for r in rows if r["condition"] == condition),
    } for condition in ("disabled", "shared", "stale")}
    stale = [r for r in rows if r["condition"] == "stale"]
    tested = sum(len(r["retrieval"]) for r in stale)
    baseline = summary["disabled"]["mean_modeled_time_s"]
    reduction = statistics.mean(paired) / baseline
    return {"config": {"seeds": seeds, "first_seed": first_seed, "primary_measure": "modeled_time_s",
                       "minimum_reduction": 0.05, "speed_m_s": 0.5, "model_calls": 0,
                       "scope": "graph routing and signed memory; physical contacts and motor behavior not measured",
                       "stale_condition": "layout changes and closes one queue edge; compare recovery, not speed"},
            "summary": summary, "paired_mean_saved_s": statistics.mean(paired),
            "paired_saved_s_bootstrap_95": [samples[49], samples[1949]],
            "modeled_time_reduction": reduction,
            "stale_records_tested": tested,
            "stale_rejection_rate": sum(r["excluded_experiences"] for r in stale) / tested if tested else None,
            "acceptance": reduction >= 0.05 and tested > 0 and all(r["restricted_edges"] == 0 for r in rows)
                          and all(r["accepted_experiences"] == 0 and r["completed"] for r in stale),
            "rows": rows}


def write(result, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    lines = ["# Paired experience learning experiment", "", result["config"]["scope"], "",
             "| Condition | Completed | Mean modeled time (s) | Restricted edges |", "|---|---:|---:|---:|"]
    for condition, row in result["summary"].items():
        lines.append(f"| {condition} | {row['completed']} | {row['mean_modeled_time_s']:.2f} | {row['restricted_edges']} |")
    lines += ["", f"Paired mean saving: {result['paired_mean_saved_s']:.2f} s; 95% bootstrap interval: {result['paired_saved_s_bootstrap_95']}.",
              f"Modeled time reduction: {result['modeled_time_reduction']:.1%}. Stale rejection: {result['stale_rejection_rate']:.1%} across {result['stale_records_tested']} records.",
              "", "Robot A acquires queue outcomes before evaluation; Robot B never updates memory during paired trials.",
              "Every fourth seed has no queue, testing a case where sharing should offer no advantage.",
              "The stale arm has changed topology and is a rejection/recovery check, not an efficiency comparison with the other arms.",
              "These results do not establish physical mission success, contact rates, neural-network learning, or general performance gains."]
    (output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--first-seed", type=int, default=0)
    parser.add_argument("--out", default="bench/results/experience")
    args = parser.parse_args()
    result = experiment(args.seeds, args.first_seed)
    write(result, args.out)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
