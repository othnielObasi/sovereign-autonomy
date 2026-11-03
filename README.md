# Sovereign Autonomy

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![Next.js](https://img.shields.io/badge/next.js-14-black.svg)](https://nextjs.org)

**AI plans the robot's moves. Nothing moves without proof it was allowed.**

Sovereign Autonomy puts Meta's models in charge of planning and perception for a warehouse robot, and puts an independent execution authority between those models and the motors. A model can propose; only a signed, single-use permit for that exact action, issued against fresh world state, can make the robot move. Kill switches revoke authority instantly, and a crash mid-mission never causes a move to be repeated.

Entry to the **Meta Global AI Developer Hackathon** (Startup track, theme: *Push the Frontier*).

> **Status:** work in progress during the hackathon build period (27 Oct – 4 Nov 2026).

Fresh live validation and submission draft: [submission evidence](docs/HACKATHON_SUBMISSION.md).
On 3 November, a camera-informed Muse Spark mission completed with 88 verified
original audit events and 25 verified decision signatures. Tavily also completed
a live spill lookup and the gate denied a move into its tightened exclusion zone.
The [three-minute demo script](docs/demo-script.md) is ready; video publication
and the final submission remain pending. Team and participant fields are blank.

---

## Built during the hackathon

The redesigned workspace starts at **`/mission-control`**, with the facility,
fleet, mission desk and decision trail together. See
[UI / UX overhaul](docs/UI_UX_OVERHAUL.md) for the workflow, default cleanroom
layout and browser validation.

The git history starts with a baseline containing the pre-existing codebase.
Later commits record the additions below; [`CHANGELOG.md`](CHANGELOG.md) lists
changes. Git history alone does not establish original creation dates. The
[submission draft](docs/HACKATHON_SUBMISSION.md) separates new additions from
the supporting foundation, including the pre-existing Tavily integration.

| Capability | Status |
|---|---|
| **Muse Spark** plans each mission from the map and the robot camera; **Muse Spark Open** (Baseten) proposes steps | Ready: runs when `MODEL_API_KEY` / `BASETEN_API_KEY` are set |
| **SAM 3.1** perception: detections projected onto the floor, cross-checked with sensors | Ready: runs with `MODEL_API_KEY` |
| **Muse Voice Transcribe** stop: say "stop" and the robot stops; voice can never start it | Ready: runs with `MODEL_API_KEY` |
| **Precision parts factory** (new live site): raw-material stores, a transport corridor with a forklift, a production floor with CNC machines, a press, a fenced welding cell and an assembly line, QC and dispatch. Two robots deliver parts line-side. The benchmark keeps the original warehouse (`SITE_LAYOUT` picks the site) | Working |
| Execution authority: every approved move gets a signed, single-use permit after a full-path check; the simulator checks it again | Working |
| Kill switches (global, robot, mission, agent), controller e-stop, verified stop, dead-man stop | Working |
| Restart recovery: interrupted runs pause; resume settles uncertain moves and continues from the last confirmed waypoint | Working |
| Learned routing on NetworkX from signed experience; forged records quarantined | Working |
| Canary tripwire: a plan that obeys an instruction hidden in untrusted data is discarded | Working |
| Security drills: eight real attacks against the live simulator, pass/fail (`/authority`) | Working |
| Prometheus `/metrics` and Grafana dashboard for the safety path | Working |
| LangSmith: one trace per mission, from the model's plan to each gate decision and permit | Ready: runs with `LANGSMITH_API_KEY` |

This table is updated as each item lands. [`docs/TRACEABILITY.md`](docs/TRACEABILITY.md) maps every capability in the plan to its status and tests.

## Pre-existing foundation (before 26 October 2026)

Carried over from our earlier robotics governance codebase and **not** presented as hackathon work:

- Deterministic safety gate of 11 policies (geofence, zone speed limits, human proximity, obstacle and path clearance, hazard zones and others)
- SHA-256 hash-chained event log and Ed25519-signed decision receipts
- Operator approval, pause, stop and rule-change workflows
- Task-drift guard, learning from the gate's denials, injection firewall for site intelligence
- Live warehouse simulator with moving workers and hazards, 2D/3D dashboard
- Headless safety benchmark harness

---

## Quick start

### Docker Compose

```bash
git clone https://github.com/othnielObasi/sovereign-autonomy.git
cd sovereign-autonomy
echo "PERMIT_SECRET=$(python -c 'import secrets; print(secrets.token_hex(32))')" >> .env
docker compose up -d
```

| Service | URL |
|---------|-----|
| Operator dashboard | http://localhost:3000 |
| Backend API | http://localhost:8080 |
| API docs (Swagger) | http://localhost:8080/docs |
| Warehouse simulator | http://localhost:8090 |

### Local development (without Docker)

Run each from the repository root, in its own terminal.

```bash
# 0. Set the SAME value in the backend and simulator terminals before starting either.
export PERMIT_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")

# 1. Warehouse simulator (shares its engine with the benchmark in backend/bench)
pip install -r sim/warehouse_sim/requirements.txt
export AUTHORITY_BASE_URL="http://127.0.0.1:8080"
PYTHONPATH=backend uvicorn server:app --app-dir sim/warehouse_sim --host 0.0.0.0 --port 8090

# 2. Backend
cd backend && pip install -e ".[dev]"
export SIM_BASE_URL="http://localhost:8090"
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload

# 3. Frontend (proxies /api to http://localhost:8080; override with BACKEND_URL)
cd frontend && npm install && npm run dev
```

The simulator redeems every move with the backend before accepting it. If that callback is unavailable, no new move is accepted. Keep `SIM_STATE_DB` (default `data/controller.db`) across simulator restarts; Compose persists it in `controller_data`.

Without model keys the planner uses a clearly labelled deterministic fallback, and every safety control still applies.

To use Meta's models, add `MODEL_API_KEY` (and optionally `BASETEN_API_KEY`) to `.env` and `backend/.env`, then check them with `cd backend && python ../scripts/check_meta.py`.

## Testing

```bash
# Backend tests; run from backend/ so the bench package imports
cd backend && python -m pytest tests/ -q

# Frontend type-check
cd frontend && npx tsc --noEmit
```

## Documentation

- [docs/architecture.md](docs/architecture.md): how the system fits together
- [docs/BUILD.md](docs/BUILD.md): build, run and configuration
- [docs/api.md](docs/api.md): API reference
- [docs/DEVELOPER.md](docs/DEVELOPER.md): where things live and conventions
- [docs/EXPERIENCE_LEARNING_PLAN.md](docs/EXPERIENCE_LEARNING_PLAN.md): implementation and testing plan for context-aware experience reuse, freshness, permit revocation, and learning evaluation
- [docs/LEARNING_POISONING_DEFENSES.md](docs/LEARNING_POISONING_DEFENSES.md): source corroboration, bounded influence, quarantine, signed lessons, checkpoint recovery, and remaining trust assumptions

## Safety scope

This is simulation software. Software permits and kill switches are not a substitute for safety-rated hardware emergency stops on a real robot.

## License

MIT, see [LICENSE](LICENSE).
