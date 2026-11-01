"""Sovereign Autonomy safety benchmark.

    # learning curve: 5 rounds of 40 fresh scenarios, rule-based planner
    python -m bench run --planner rule_based --rounds 5 --seeds-per-round 40

    # Nemotron on Token Factory (needs NEBIUS_API_KEY)
    python -m bench run --planner nemotron --rounds 3 --seeds-per-round 20

    # one large round split across Nebius Serverless Jobs, then merged
    python -m bench run --rounds 1 --seeds-per-round 500 --shard 0/4 --out results/shard0
    python -m bench merge results/shard*/results.json --out results/full

    # judge a candidate rule set (used by the rule-change workflow)
    python -m bench run --params candidate.json ...

Writes results.json, README.md and chart.png to --out.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

logging.basicConfig(level=logging.WARNING, format="%(message)s")
for noisy in ("app", "app.governance", "app.planner_lessons", "app.nemotron_planner", "httpx"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
logging.getLogger("app.governance").setLevel(logging.ERROR)


def _bench_db():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from app.db.session import Base
    from app.utils import signing
    signing._reset_for_tests(Ed25519PrivateKey.generate())   # throwaway key: benchmark receipts are not evidence
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _lessons(db) -> List[Dict[str, Any]]:
    from app.services.planner_lessons import all_lessons
    return [{"id": l["id"], "text": l["text"], "policy": l["policy"], "cell": [l["cell_x"], l["cell_y"]],
             "max_approved_speed": l.get("max_approved_speed"), "denials": l["denials"]}
            for l in all_lessons(db)]


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


def run(args) -> Dict[str, Any]:
    from app.policies import params as P
    from app.services.nemotron_planner import usage_log
    from app.services.planner_lessons import distill_run
    from bench.planners import PLANNERS
    from bench.runner import aggregate, run_arm
    from bench.scenarios import generate
    from bench.world import Layout

    params: Optional[Dict[str, Any]] = json.loads(Path(args.params).read_text()) if args.params else None
    if params is not None:
        problems = P.validate(params)
        if problems:
            sys.exit("candidate rules invalid: " + "; ".join(problems))
    rules = params if params is not None else P.active_params()
    if params is not None:
        P._set_active(params)   # lessons are scoped to the rules version in force

    layout = Layout()
    planner = PLANNERS[args.planner](layout)
    arms = [a for a in args.arms.split(",") if a]
    shard_i, shard_n = (int(x) for x in args.shard.split("/"))
    db = _bench_db()
    rows: List[Dict[str, Any]] = []
    rounds: List[Dict[str, Any]] = []
    t0 = time.time()

    for rnd in range(1, args.rounds + 1):
        first = args.first_seed + (rnd - 1) * args.seeds_per_round
        seeds = [s for s in range(first, first + args.seeds_per_round) if s % shard_n == shard_i]
        lessons = _lessons(db)
        round_rows: List[Dict[str, Any]] = []
        learning_runs = []
        for k, seed in enumerate(seeds):
            sc = generate(seed, layout)
            for arm in arms:
                run_id = f"bench_r{rnd}_s{seed}_{arm}"
                use_db = db if arm == "learning" else None
                r = run_arm(sc, layout, planner, arm, db=use_db, run_id=run_id,
                            lessons=lessons if arm == "learning" else None, params=params).as_dict()
                r["round"] = rnd
                round_rows.append(r)
                if arm == "learning":
                    learning_runs.append(run_id)
            if args.progress:
                print(f"round {rnd} · {k + 1}/{len(seeds)} scenarios · {time.time() - t0:.0f}s", file=sys.stderr)
        for run_id in learning_runs:   # lessons from this round feed the next
            distill_run(db, run_id)
        rows += round_rows
        rounds.append({
            "round": rnd, "seeds": seeds, "lessons_available": len(lessons),
            "arms": {arm: aggregate([r for r in round_rows if r["arm"] == arm]) for arm in arms},
        })

    usage = usage_log.summary()
    return {
        "config": {
            "planner": args.planner, "rounds": args.rounds, "seeds_per_round": args.seeds_per_round,
            "first_seed": args.first_seed, "arms": arms, "shard": args.shard,
            "policy_version": P.params_hash(rules), "candidate_rules": params is not None,
            "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "git_commit": _git_commit(), "wall_time_s": round(time.time() - t0, 1),
            "lessons_learned": len(_lessons(db)),
        },
        "rules": rules,
        "rounds": rounds,
        "totals": {arm: aggregate([r for r in rows if r["arm"] == arm]) for arm in arms},
        "model_usage": usage,
        "scenarios": rows,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bench", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--planner", default="rule_based", choices=["rule_based", "reckless", "nemotron"])
    r.add_argument("--rounds", type=int, default=3)
    r.add_argument("--seeds-per-round", type=int, default=30)
    r.add_argument("--first-seed", type=int, default=1000)
    r.add_argument("--arms", default="ungoverned,governed,learning")
    r.add_argument("--shard", default="0/1", help="i/n: run only seeds with seed %% n == i")
    r.add_argument("--params", help="JSON file with a candidate rule set to judge instead of the active rules")
    r.add_argument("--out", default="bench/results/latest")
    r.add_argument("--progress", action="store_true")
    m = sub.add_parser("merge")
    m.add_argument("parts", nargs="+")
    m.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    from bench import report
    if args.cmd == "run":
        if args.shard != "0/1" and args.rounds > 1:
            sys.exit("sharding is for single-round runs: learning rounds share lessons and run in one job")
        results = run(args)
    else:
        results = report.merge([json.loads(Path(p).read_text()) for p in args.parts])
    paths = report.write(results, Path(args.out))
    tot = results["totals"]
    print(json.dumps({arm: {k: tot[arm][k] for k in ("scenarios", "completion_rate", "unsafe_proposed",
                                                      "unsafe_executed", "person_contacts", "false_block_rate")}
                      for arm in tot}, indent=1))
    print(f"wrote {paths['md']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
