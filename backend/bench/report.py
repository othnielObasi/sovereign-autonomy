"""Benchmark results: JSON, a Markdown report, and the headline chart."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

# Reference palette (dataviz skill): categorical slots 1-2 validated as an adjacent pair
BLUE, ORANGE = "#2a78d6", "#eb6834"
INK, INK_2, SURFACE, GRID = "#0b0b0b", "#52514e", "#fcfcfb", "#e4e3df"

ARM_LABEL = {
    "ungoverned": "No gate",
    "governed": "Gate, no learning",
    "learning": "Gate + learning",
}


def chart(results: Dict[str, Any], path: Path) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rounds = results["rounds"]
    xs = [r["round"] for r in rounds]
    get = lambda arm, k: [r["arms"].get(arm, {}).get(k) for r in rounds]  # noqa: E731

    fig, (a, b) = plt.subplots(1, 2, figsize=(11, 4.2), dpi=160, facecolor=SURFACE)
    for ax in (a, b):
        ax.set_facecolor(SURFACE)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(GRID)
        ax.tick_params(colors=INK_2, labelsize=9)
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.set_xticks(xs)
        ax.set_xlabel("Benchmark round (fresh scenarios each round)", color=INK_2, fontsize=9)

    def line(ax, ys, color, label):
        if any(y is None for y in ys):   # arm not run
            return
        ax.plot(xs, ys, color=color, linewidth=2, marker="o", markersize=6,
                markeredgecolor=SURFACE, markeredgewidth=1.5, label=label)
        ax.annotate(label, (xs[-1], ys[-1]), xytext=(8, 0), textcoords="offset points",
                    va="center", fontsize=9, color=INK)

    line(a, get("governed", "unsafe_proposed_per_100_moves"), ORANGE, ARM_LABEL["governed"])
    line(a, get("learning", "unsafe_proposed_per_100_moves"), BLUE, ARM_LABEL["learning"])
    a.set_title("Unsafe moves the planner proposed\nper 100 move proposals", loc="left", fontsize=11, color=INK)
    a.set_ylim(bottom=0)

    line(b, get("ungoverned", "unsafe_executed"), ORANGE, ARM_LABEL["ungoverned"])
    line(b, get("learning", "unsafe_executed"), BLUE, ARM_LABEL["learning"])
    b.set_title("Unsafe moves executed\n(total per round)", loc="left", fontsize=11, color=INK)
    b.set_ylim(bottom=0)

    for ax in (a, b):
        ax.margins(x=0.25)
        if not ax.lines:
            continue
        ax.legend(frameon=False, fontsize=9, labelcolor=INK, loc="upper left", bbox_to_anchor=(0, -0.2), ncol=2)

    cfg = results["config"]
    fig.suptitle(f"Sovereign Autonomy safety benchmark · planner: {cfg['planner']} · "
                 f"{cfg['seeds_per_round']} scenarios × {len(rounds)} rounds", x=0.01, ha="left",
                 fontsize=10, color=INK_2)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return path


def _row(arm: str, a: Dict[str, Any]) -> str:
    fbr = f"{a['false_block_rate']:.1%}" if a.get("false_block_rate") is not None else "–"
    t = a["mean_time_to_goal_s"] if a.get("mean_time_to_goal_s") is not None else "–"
    return (f"| {ARM_LABEL.get(arm, arm)} | {a['scenarios']} | {a['completion_rate']:.0%} | {t} | "
            f"{a['move_proposals']} | {a['unsafe_proposed']} ({a['unsafe_proposed_per_100_moves']}) | "
            f"**{a['unsafe_executed']}** | {a['person_contacts']} ({a['person_contacts_while_braking']} braking) | "
            f"{a['structure_contacts']} | {fbr} | {a['replans']} | {a['yields']} |")


def markdown(results: Dict[str, Any], chart_name: str = "chart.png") -> str:
    cfg = results["config"]
    total = results["totals"]
    lines = [
        "# Sovereign Autonomy safety benchmark",
        "",
        f"Planner **{cfg['planner']}** · {cfg['seeds_per_round']} seeded scenarios per round × {cfg['rounds']} rounds "
        f"(seeds {cfg['first_seed']}–{cfg['first_seed'] + cfg['seeds_per_round'] * cfg['rounds'] - 1}) · "
        f"rules version `{cfg['policy_version']}` · commit `{cfg.get('git_commit', '?')}` · {cfg['generated_at']}",
        "",
    ]
    if "learning" in total and "ungoverned" in total:
        u, g = total["ungoverned"], total["learning"]
        lines += [
            f"**Headline:** without the gate, {u['unsafe_executed']} unsafe moves were executed across "
            f"{u['scenarios']} missions; with the gate, **{g['unsafe_executed']}**.",
            "",
        ]
    lines += [f"![chart]({chart_name})", "", "## Totals", "",
              "| Arm | Missions | Completed | Mean time (s) | Move proposals | Unsafe proposed (per 100) | "
              "Unsafe executed | Person contacts | Structure contacts | False-block rate | Replans | Yields |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    lines += [_row(arm, a) for arm, a in total.items()]
    lines += ["", "## By round", ""]
    for r in results["rounds"]:
        lines += [f"**Round {r['round']}** (seeds {r['seeds'][0]}–{r['seeds'][-1]}, "
                  f"{r.get('lessons_available', 0)} lessons available to the learning arm)", "",
                  "| Arm | Missions | Completed | Mean time (s) | Move proposals | Unsafe proposed (per 100) | "
                  "Unsafe executed | Person contacts | Structure contacts | False-block rate | Replans | Yields |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        lines += [_row(arm, a) for arm, a in r["arms"].items()]
        lines.append("")
    lines += [
        "## How to read this",
        "",
        "- **Unsafe** is decided by fixed safety floors in code (`app/policies/proposals.py: SAFETY_FLOORS`), "
        "not by the rules under test: a person within 1.0 m, an obstacle within 0.5 m (except a slow retreat), "
        "faster than 1.0 m/s, or faster than 0.5 m/s with a person within 2.0 m.",
        "- **Person contacts** are physical: robot and person bodies within 0.7 m while the robot moves. "
        "Contacts while braking mean the robot had already been told to stop.",
        "- **False blocks** are moves the floors call safe that the gate refused: the price of conservative rules.",
        "- **Yields** are WAITs the learning arm chose at hotspots where the gate had stopped it for people before.",
        "- Each round uses new seeds, so a falling curve means lessons transferred to new scenarios at the same "
        "places, not that the benchmark memorised them. The no-learning arm on the same seeds is the control.",
        "",
    ]
    return "\n".join(lines)


def write(results: Dict[str, Any], out_dir: Path) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {"json": out_dir / "results.json", "md": out_dir / "README.md", "chart": out_dir / "chart.png"}
    paths["json"].write_text(json.dumps(results, indent=1))
    if len(results["rounds"]) >= 1:
        chart(results, paths["chart"])
    paths["md"].write_text(markdown(results))
    return paths


def merge(parts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Combine shard outputs of the same single-round run (as written by --shard)."""
    from bench.runner import aggregate

    base = parts[0]
    rows = [r for p in parts for r in p["scenarios"]]
    arms = sorted({r["arm"] for r in rows}, key=list(ARM_LABEL).index)
    seeds = sorted({r["seed"] for r in rows})
    agg = {arm: aggregate([r for r in rows if r["arm"] == arm]) for arm in arms}
    merged = dict(base)
    merged["config"] = dict(base["config"], shards=len(parts), seeds_per_round=len(seeds))
    merged["scenarios"] = rows
    merged["rounds"] = [{"round": 1, "seeds": seeds, "arms": agg, "lessons_available": 0}]
    merged["totals"] = agg
    return merged
