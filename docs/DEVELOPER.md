# Developer Guide (internal)

The developer handbook for Sovereign Autonomy: where things live, how a run works, and the conventions to keep. For setup and deployment see [BUILD.md](BUILD.md); for endpoints see [api.md](api.md).

## Project Overview

**Sovereign Autonomy** is a real-time governance layer for autonomous robots. An NVIDIA Nemotron planner (on Nebius Token Factory) proposes each move; a deterministic gate of 11 policies approves, slows or blocks it before it runs; every decision is hash-chained and signed with Ed25519.

## Architecture Essentials

- Backend: `backend/app/` (FastAPI)
- Safety benchmark and simulation engine: `backend/bench/`
- Frontend: `frontend/src/` (Next.js 14, three.js for the 3D view)
- Warehouse simulator (default): `sim/warehouse_sim/`
- Original mock simulator (Compose `legacy` profile): `sim/mock_sim/`

The warehouse simulator imports the benchmark engine, so changes to `backend/bench/world.py`, `scenarios.py` or `layout.json` change the live demo too.

## Rules to Keep

- **The gate never trusts a model.** Planner output is only a proposal. Every proposal goes through `GovernanceEngine.evaluate_and_record()`.
- **Denied means stopped.** A denial sends STOP to the robot; hard denials never execute, even after the circuit breaker relabels them.
- **Outside text never sets a rule.** Tavily results and bulletins pass the firewall in `services/site_intel/`; fixed rules read accepted text; zones can only grow. The gate reads zone geometry and limits, never text.
- **Lessons come only from gate records** and are scoped to the policy version they were learned under.
- **Thresholds change only through proposals** (`policies/proposals.py`): replay, benchmark for relaxations, a second-person approval, activation between runs. Safety floors in code cannot be changed by a proposal.

## CI and Deployment

`.github/workflows/ci.yml` runs on every push and pull request to `main`: backend tests, the frontend build, and Docker builds (backend, mock sim, warehouse sim). Deployment is manual; see [BUILD.md](BUILD.md#production).

### Secrets and Runtime

- Runtime secrets live in `.env` beside the compose file on the VM, readable only by the deploy user. `.env.example` lists the names; never put real values in it.
- Never commit secrets, and rotate keys after the event.
- Without `RECEIPT_SIGNING_KEY`, a development signing key is created in `data/`; receipts signed with it cannot be verified after the key is lost.

## Run Lifecycle

1. `start_run()` — creates the run, snapshots the policy version, requests a mission plan (Nemotron Ultra, with lessons near the route), spawns the loop
2. `_run_loop()` — about once a second: poll telemetry (plus hazard zones) → next waypoint or planner proposal → `evaluate_and_record` → execute or STOP → append events → broadcast
3. `pause_run()` / `resume_run()` — sets the pause flag, logs an INTERVENTION event
4. `stop_run()` — sets the stop flag, marks the run `stopped`
5. On completion — post-run safety validation (fails a run only for an unsafe *execution*), then lessons are distilled from the gate's records

States: `running` → `paused` → `running` → `completed` | `stopped` | `failed`

## Governance Engine

[`governance_engine.py`](../backend/app/services/governance_engine.py):

- `evaluate()` — stateless policy evaluation
- `evaluate_and_record()` — evaluates, signs, persists to `governance_decisions`, runs the circuit breaker
- Circuit breaker: 3 consecutive denials per run → DENIED relabelled NEEDS_REVIEW (state persisted in `circuit_breaker_state`)
- Decision history, stats and receipts

## Policy Catalog

11 policies in [`policy_catalog.yaml`](../backend/app/policies/policy_catalog.yaml), each with `parameters`, `trigger` and `action`; logic in [`rules_python.py`](../backend/app/policies/rules_python.py):

`GEOFENCE_01`, `SAFE_SPEED_01`, `HUMAN_PROXIMITY_02`, `HUMAN_CLEARANCE_02`, `OBSTACLE_CLEARANCE_03`, `UNCERTAINTY_04`, `HITL_05`, `WORKER_PROXIMITY_06`, `PATH_CLEARANCE_07`, `HAZARD_EXCLUSION_08`, `HAZARD_SLOW_09`.

Zone speed limits come from `ZONE_SPEED_LIMITS` in [`world_model.py`](../backend/app/world_model.py), which reads `sim/mock_sim/world.json` (aisle 0.5, corridor 0.7, loading bay 0.4, staging 0.3 m/s). Keep it in step with `backend/bench/layout.json`.

## Database Schema

Key tables ([`models.py`](../backend/app/db/models.py)):

- `missions`, `mission_audit` — missions and their change history
- `runs` — runs, with policy version, planning mode and safety verdict
- `events` — SHA-256 hash-chained audit trail (PLAN, DECISION, EXECUTION, INTERVENTION, site-intel events)
- `governance_decisions` — every evaluation (decision, risk score, policy hits, signature)
- `telemetry_samples`, `operator_approvals`, `agent_memory`
- `policy_versions`, `policy_proposals`, `policy_activations` — governed rule changes
- `circuit_breaker_state`

Migrations: `backend/alembic/versions/`. SQLite uses one connection per thread with WAL.

## Simulator Hazards

The warehouse simulator supports these hazards (`POST /sim/scenario` on the backend):

| Scenario | Effect |
|----------|--------|
| `human_approach` | Worker stops about 2.5 m ahead → SLOW |
| `human_too_close` | Worker steps out 0.8 m ahead → STOP |
| `path_blocked` | Pallet dropped 2 m ahead → REPLAN |
| `spill` | Spill 3 m ahead → hazard zone |
| `forklift_crossing` | Forklift crosses the robot's path |
| `clear` | Remove injected hazards |

`POST /sim/seed` replays a benchmark scenario exactly. The legacy mock simulator still has its 10 scripted scenarios and `governance_demo` / `policy_sweep` / `stress_test` sequences.

## Useful Commands

```bash
# Run locally
docker compose up -d
# Frontend: http://localhost:3000   Backend: http://localhost:8080/docs

# Backend tests (from backend/, so the bench package imports)
cd backend && python -m pytest tests/ -q

# Live traffic tests (from the repo root)
python -m pytest tests/test_live_traffic.py -q

# Browser smoke tests (frontend running; from the repo root)
APP_URL=http://127.0.0.1:3000 node tests/warehouse-parity.smoke.cjs

# Safety benchmark
cd backend && python -m bench run --planner rule_based --rounds 5 --seeds-per-round 30 --out bench/results/rule_based

# Check the Token Factory catalogue and both Nemotron tiers
NEBIUS_API_KEY=... python scripts/check_token_factory.py

# Inject a hazard
curl -X POST http://localhost:8080/sim/scenario \
  -H "Content-Type: application/json" -d '{"scenario": "spill"}'

# Governance stats for a run
curl http://localhost:8080/governance/decisions/{run_id}/stats
```

## Where to Look

| Area | File(s) |
|---|---|
| Run loop | `backend/app/services/run_service.py` |
| Governance engine | `backend/app/services/governance_engine.py` |
| Policies | `backend/app/policies/rules_python.py`, `policy_catalog.yaml` |
| Governed rule changes | `backend/app/policies/proposals.py`, `params.py`, `api/routes_policy_proposals.py` |
| Nemotron planner | `backend/app/services/nemotron_planner.py`, `llm_factory.py` |
| Planner lessons | `backend/app/services/planner_lessons.py` |
| Site intelligence | `backend/app/services/site_intel/`, `api/routes_site_intel.py` |
| Receipt signing | `backend/app/utils/signing.py` |
| Simulator adapter | `backend/app/services/sim_adapter.py`, `api/routes_sim.py` |
| Benchmark | `backend/bench/` ([README](../backend/bench/README.md)) |
| Warehouse simulator | `sim/warehouse_sim/server.py`, `traffic.py`, `camera.py` |
| Run page | `frontend/src/app/runs/[runId]/page.tsx` |
| 2D/3D views | `frontend/src/components/WarehouseView.tsx`, `Map2D.tsx`, `twin/` |
| WebSocket hub | `backend/app/api/routes_ws.py` |
| DB models | `backend/app/db/models.py` |

---

**Last Updated:** 2026-10-25
