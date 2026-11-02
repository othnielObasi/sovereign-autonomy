"""Prometheus metrics, without extra dependencies.

Counters and timings for the safety-critical path: gate decisions, permits issued
and refused (by reason), dispatch outcomes, kill switches with measured revoke
and stop times, quarantined learning records, and model calls. Served as
Prometheus text at GET /metrics; infra/grafana/dashboard.json reads these names.
"""
from __future__ import annotations

import threading
from collections import defaultdict
from typing import Dict, Tuple

_lock = threading.Lock()
_counters: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = defaultdict(float)
_timings: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], list] = {}   # name/labels -> [count, sum, last]

HELP = {
    "governance_decisions_total": "Gate decisions by verdict",
    "permits_issued_total": "Single-use permits issued",
    "permits_refused_total": "Moves refused before a permit, by reason",
    "permit_redemptions_total": "Controller permit redemptions by outcome",
    "dispatch_total": "Commands through the dispatch path, by outcome",
    "kill_switch_total": "Kill switches activated, by scope",
    "kill_revoke_ms": "Time to revoke authority after a kill switch",
    "kill_stop_verified_ms": "Time until the controller reported the robot stopped",
    "canary_tripped_total": "Plans discarded because the planner obeyed a canary",
}


def _key(name: str, labels: Dict[str, str]):
    return name, tuple(sorted((k, str(v)) for k, v in labels.items()))


def inc(name: str, value: float = 1.0, **labels: str) -> None:
    with _lock:
        _counters[_key(name, labels)] += value


def observe(name: str, value: float, **labels: str) -> None:
    with _lock:
        t = _timings.setdefault(_key(name, labels), [0, 0.0, 0.0])
        t[0] += 1
        t[1] += float(value)
        t[2] = float(value)


def _fmt_labels(labels) -> str:
    if not labels:
        return ""
    esc = lambda v: v.replace("\\", "\\\\").replace('"', '\\"')   # noqa: E731
    return "{" + ",".join(f'{k}="{esc(v)}"' for k, v in labels) + "}"


def render() -> str:
    lines = []
    with _lock:
        counters = dict(_counters)
        timings = {k: list(v) for k, v in _timings.items()}
    seen = set()
    for (name, labels), value in sorted(counters.items()):
        if name not in seen:
            seen.add(name)
            lines += [f"# HELP {name} {HELP.get(name, name)}", f"# TYPE {name} counter"]
        lines.append(f"{name}{_fmt_labels(labels)} {value:g}")
    for (name, labels), (count, total, last) in sorted(timings.items()):
        if name not in seen:
            seen.add(name)
            lines += [f"# HELP {name} {HELP.get(name, name)}", f"# TYPE {name} summary"]
        lines.append(f"{name}_count{_fmt_labels(labels)} {count:g}")
        lines.append(f"{name}_sum{_fmt_labels(labels)} {total:g}")
        lines.append(f"{name}_last{_fmt_labels(labels)} {last:g}")

    # Gauges read at scrape time
    try:
        from app.services.route_learning import get_memory
        from app.services.site_router import last_route_info
        delays, quarantined = get_memory().load(context=last_route_info.get("experience_context"))
        lines += ["# TYPE learning_cells gauge", f"learning_cells {len(delays)}",
                  "# TYPE learning_quarantined_records gauge", f"learning_quarantined_records {len(quarantined)}"]
    except Exception:
        pass
    try:
        from app.services.execution_authority import get_authority
        a = get_authority()
        lines += ["# TYPE kill_switches_active gauge", f"kill_switches_active {len(a.kills.active())}",
                  "# TYPE permits_enforced gauge", f"permits_enforced {1 if a.enabled else 0}"]
    except Exception:
        pass
    try:
        from app.services.model_runtime import usage_log
        for row in usage_log.summary().get("by_model", []):
            lab = _fmt_labels((("model", str(row["model"])), ("tier", str(row["tier"]))))
            lines.append(f"model_calls_total{lab} {row['calls']}")
            lines.append(f"model_calls_ok_total{lab} {row['ok']}")
            if row.get("p50_latency_ms") is not None:
                lines.append(f"model_latency_p50_ms{lab} {row['p50_latency_ms']}")
    except Exception:
        pass
    return "\n".join(lines) + "\n"
