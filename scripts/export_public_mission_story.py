"""Export a historical simulator run without modifying its source database.

Only the isolated validation database is supported by default. No credentials,
model requests, simulator commands or live operational links are exported.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "run_f8bdbc5984ab"


def digest(value):
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def reject_credentials(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in {"authorization", "access_token", "refresh_token", "api_key", "private_key", "secret", "password"}:
                raise ValueError(f"Refusing credential-like field: {key}")
            reject_credentials(child)
    elif isinstance(value, list):
        for child in value:
            reject_credentials(child)


def export(database: Path):
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        run = dict(db.execute("SELECT * FROM runs WHERE id=?", (RUN_ID,)).fetchone())
        rows = list(db.execute("SELECT * FROM events WHERE run_id=? ORDER BY ts, rowid", (RUN_ID,)))
    events = []
    mismatches = []
    previous = "0" * 64
    for row in rows:
        # SQLite stored naive UTC; the original event hash included +00:00.
        timestamp = dt.datetime.fromisoformat(row["ts"]).replace(tzinfo=dt.timezone.utc).isoformat()
        event = dict(id=row["id"], ts=timestamp, type=row["type"], payload=json.loads(row["payload_json"]), hash=row["hash"], prev_hash=row["prev_hash"] or "0" * 64)
        body = {"run_id": RUN_ID, **{key: event[key] for key in ("ts", "type", "payload", "prev_hash")}}
        assert digest(body) == event["hash"], event["id"]
        if previous != event["prev_hash"]:
            mismatches.append(event["id"])
        previous = event["hash"]
        events.append(event)
    reject_credentials(events)
    used = [e for e in events if e["type"] == "AUTHORITY" and e["payload"].get("event") == "permit_used"]
    denied = [e for e in events if e["type"] == "DECISION" and e["payload"].get("governance", {}).get("hard_fail")]
    plans = [e for e in events if e["type"] == "PLAN"]
    human = next(e for e in events if e["id"] == "evt_0b5a92dc17f7")
    stop = next(e for e in events if e["ts"] > human["ts"] and e["type"] == "EXECUTION" and e["payload"].get("command", {}).get("intent") == "STOP")
    resume = next(e for e in used if e["ts"] > plans[1]["ts"])
    decisions = [e for e in events if e["type"] == "DECISION" and "context" in e["payload"]]
    move = next(e for e in decisions if e["ts"] > used[0]["ts"])
    resumed = next(e for e in decisions if e["ts"] > resume["ts"])
    last_stop = next(e for e in reversed(events) if e["type"] == "EXECUTION" and e["payload"].get("command", {}).get("intent") == "STOP")

    def pose(event):
        telemetry = event["payload"]["context"]["telemetry"]
        return {key: telemetry.get(key) for key in ("x", "y", "speed", "human_distance_m")}

    def route(plan, start):
        return [start] + [[w["x"], w["y"]] for w in plan["payload"]["plan"]["waypoints"]]

    notes = [
        "Recorded local simulator validation on 3 November 2026; no physical robots or paid model calls.",
        "Selected moments omit intermediate events and operator pauses. This is not real-time playback.",
        "Fallback planning was used. This recording does not demonstrate live AI model execution or shared learning.",
        "The record contains unsafe proposals, review decisions and integrity alerts. Completion does not mean every proposal was safe.",
        "After arrival the simulator resets to parking; this is not a driven return journey.",
        f"All {len(events)} individual event hashes verify. The historical chronological audit has {len(mismatches)} linkage discontinuities; it is not a fully continuous audit chain.",
    ]
    steps = [
        dict(label="Plan", title="A route to the Quality lab", text="Robot-2 receives a route from Formulation to the Quality lab through the shared corridor. The site router proposes 16 waypoints. Each move still needs its own safety check and permit.", status="Route proposed", time=plans[0]["ts"], event_ids=[plans[0]["id"]], pose=pose(decisions[0]), route=route(plans[0], [30, 2.5]), fact_label="Planned route", fact="16 waypoints"),
        dict(label="Move", title="A permit allows the next move", text="The controller records a used movement permit. Subsequent robot updates show the carrier leaving its start position. A route alone did not authorise this move.", status="Permit used", time=used[0]["ts"], event_ids=[used[0]["id"], move["id"]], pose=pose(move), fact_label="Recorded robot speed", fact=f"{pose(move)['speed']} m/s"),
        dict(label="Stop", title="A person comes too close", text="The recorded human distance falls to 0.378 metres. The proximity rule refuses the proposed move and a verified STOP follows. The robot is stationary while the next route is assessed.", status="Move refused / STOP verified", time=human["ts"], event_ids=[human["id"], stop["id"]], pose=pose(human), people=human["payload"]["context"]["telemetry"]["walking_humans"], fact_label="Recorded human distance", fact="0.378 m"),
        dict(label="Replan", title="New plan. Fresh permission.", text="After repeated proximity denials, the fallback planner proposes a replacement toward the same destination. A task check keeps it on goal. The controller later records a fresh permit use before continuation.", status="New plan / fresh permit used", time=resume["ts"], event_ids=[plans[1]["id"], resume["id"]], pose=pose(resumed), route=route(plans[1], [pose(human)["x"], pose(human)["y"]]), fact_label="Replacement plan", fact="Same destination"),
        dict(label="Arrive", title="Arrival is recorded", text="The final decision records robot-2 at the Quality lab with zero speed, followed by a verified STOP. The run completes. Its later parking reset is not a driven return journey.", status="Completed / STOP verified", time=last_stop["ts"], event_ids=[decisions[-1]["id"], last_stop["id"]], pose=pose(decisions[-1]), fact_label="Recorded arrival", fact="18.004, 2.533 m"),
    ]
    # Include the telemetry observation that supplies each map marker, and draw
    # only positions observed by that moment (never a predicted executed path).
    observations = [decisions[0], move, human, resumed, decisions[-1]]
    by_id = {event['id']: event for event in events}
    for step, observation in zip(steps, observations):
        if observation['id'] not in step['event_ids']:
            step['event_ids'].append(observation['id'])
        times = sorted(by_id[event_id]['ts'] for event_id in step['event_ids'])
        clock = lambda timestamp: timestamp[11:19]
        step['time_range'] = clock(times[0]) + (' - ' + clock(times[-1]) if clock(times[0]) != clock(times[-1]) else '') + ' UTC'
        step['trail'] = [[pose(event)['x'], pose(event)['y']] for event in decisions if event['ts'] <= observation['ts']]
    report = next((json.loads(v) for v in run.values() if isinstance(v, str) and v.startswith("{") and "metrics_summary" in v), None)
    summary = dict(schema="sovereign-mission-highlights-v1", run_id=RUN_ID, recorded_date="3 November 2026", robot_id="robot-2", event_count=len(events), permit_uses=len(used), hard_fail_decisions=len(denied), notes=notes, steps=steps)
    audit = dict(schema="sovereign-public-mission-record-v1", run_id=RUN_ID, status=run["status"], started_at=run["started_at"], ended_at=run["ended_at"], robot_id="robot-2", goal=dict(x=18, y=2.5, label="Quality lab"), event_count=len(events), individual_hashes_verified=True, chronological_chain_valid=not mismatches, chronological_link_mismatches=mismatches, notes=notes, recorded_safety_report=report, events=events)
    output = ROOT / "frontend/public/landing/mission-story"
    output.mkdir(exist_ok=True)
    (output / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"events": len(events), "permit_uses": len(used), "hard_denials": len(denied), "chronological_link_discontinuities": len(mismatches)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    export(parser.parse_args().database)
