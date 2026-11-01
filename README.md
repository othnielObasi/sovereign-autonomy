# Sovereign Autonomy

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![Next.js](https://img.shields.io/badge/next.js-14-black.svg)](https://nextjs.org)

**AI plans the robot's moves. Nothing moves without proof it was allowed.**

Sovereign Autonomy puts Meta's models in charge of planning and perception for a warehouse robot, and puts an independent execution authority between those models and the motors. A model can propose; only a signed, single-use permit for that exact action, issued against fresh world state, can make the robot move. Kill switches revoke authority instantly, and a crash mid-mission never causes a move to be repeated.

Entry to the **Meta Global AI Developer Hackathon** (Startup track, theme: *Push the Frontier*).

> **Status:** work in progress during the hackathon build period (27 Oct – 4 Nov 2026).

---

## Built during the hackathon

Everything in this section was built from 26 October 2026 onward. The git history starts with a single commit containing the pre-existing codebase, so every later commit is hackathon work; [`CHANGELOG.md`](CHANGELOG.md) lists each change with its date.

| Capability | Status |
|---|---|
| Execution-authority package (`backend/app/autonomy/`): signed single-use permits, scoped kill switches, world-state versions, checkpoints with crash reconciliation, full-path checks, graph routing | In progress |
| Muse Spark mission planning | Planned |
| SAM 3.1 perception (camera frames to floor positions) | Planned |
| Muse Voice Transcribe operator stop (voice can stop, never start) | Planned |
| Muse Spark Open (open weights) cross-check planner | Planned |
| Permit-checking simulator `/command` (no command without a permit) | Planned |
| Learned routing (NetworkX) with signed, quarantinable experience records | Planned |
| Canaries and scripted poisoning/injection attacks | Planned |

This table is updated as each item lands, with its tests.

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
# 1. Warehouse simulator (shares its engine with the benchmark in backend/bench)
pip install -r sim/warehouse_sim/requirements.txt
PYTHONPATH=backend uvicorn server:app --app-dir sim/warehouse_sim --host 0.0.0.0 --port 8090

# 2. Backend
cd backend && pip install -e ".[dev]"
export SIM_BASE_URL="http://localhost:8090"
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload

# 3. Frontend (proxies /api to http://localhost:8080; override with BACKEND_URL)
cd frontend && npm install && npm run dev
```

Without model keys the planner uses a clearly labelled deterministic fallback, and every safety control still applies.

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

## Safety scope

This is simulation software. Software permits and kill switches are not a substitute for safety-rated hardware emergency stops on a real robot.

## License

MIT, see [LICENSE](LICENSE).
