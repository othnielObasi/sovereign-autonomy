# Simulator Configuration Guide

## Overview

The backend drives a robot simulator over HTTP. The default is the **warehouse simulator** ([`sim/warehouse_sim`](../sim/warehouse_sim/server.py)), which runs the safety benchmark's deterministic engine ([`backend/bench/world.py`](../backend/bench/world.py)) in real time, so the live demo and the benchmark share one world.

```
┌─────────────────┐                    ┌─────────────────┐
│    BACKEND      │  ──HTTP + TOKEN──▶ │   SIMULATOR     │
│   (FastAPI)     │                    │ warehouse_sim   │
│   Port 8080     │  ◀──Telemetry───   │   Port 8090     │
└─────────────────┘                    └─────────────────┘
```

The original mock simulator (`sim/mock_sim`) is kept for comparison under the Docker Compose `legacy` profile: `docker compose --profile legacy up mock-sim` (port 8091).

## Running It

| How | Command |
|---|---|
| Docker Compose | `docker compose up -d` (service `warehouse-sim`) |
| Docker only | `docker build -f sim/warehouse_sim/Dockerfile -t sovereign-autonomy-warehouse-sim .` then `docker run -p 8090:8090 sovereign-autonomy-warehouse-sim` (build from the repo root: the image copies the engine from `backend/bench`) |
| Local | `pip install -r sim/warehouse_sim/requirements.txt` then, from the repo root, `PYTHONPATH=backend uvicorn server:app --app-dir sim/warehouse_sim --port 8090` |

## Configuration

### Simulator environment

| Variable | Default | Description |
|---|---|---|
| `SIM_TICK_HZ` | `10` | Physics rate |
| `SIM_SPEED` | `1.0` | Time multiplier (`2.0` = twice real time) |
| `SIM_SEED` | `42` | Seed for site activity; the same seed replays the same session |
| `SIM_TOKEN` | empty | Shared secret; when set, every call except `/health` needs `X-Sim-Token` |

### Backend environment

| Variable | Description |
|---|---|
| `SIM_BASE_URL` | Where the simulator runs (see below) |
| `SIM_TOKEN` | Must match the simulator's token |

| Environment | `SIM_BASE_URL` |
|-------------|-------|
| Local (same machine) | `http://localhost:8090` |
| Docker Compose (dev) | `http://warehouse-sim:8090` |
| Nebius VM (production compose) | `http://sim:8090` |

### Generate a token

```bash
openssl rand -hex 16
# or
python -c "import secrets; print(secrets.token_hex(16))"
```

Set the same value as `SIM_TOKEN` for both the backend and the simulator. A mismatch returns `401 Unauthorized simulator call`.

## The World

Defined in [`backend/bench/layout.json`](../backend/bench/layout.json):

| Zone | Speed limit | Description |
|------|-------------|-------------|
| `aisle` | 0.5 m/s | Racking aisles with pedestrian traffic |
| `corridor` | 0.7 m/s | Main transit corridor; the forklift runs here |
| `staging` | 0.3 m/s | Buffer area |
| `loading_bay` | 0.4 m/s | Dock area |

- Geofence: 40 m × 25 m (x: 0–40, y: 0–25)
- 9 solid rack sections; 20 bays (`B-01`–`B-06` dock, `A-01`–`A-12` pick face, `S-01`–`S-02` staging)
- Charging stations, packing stations and fire exits
- 13 hotspots where people cross (cross-aisles, corridor, packing stations, dock doors)

**Site activity** runs on its own: workers move between work destinations and pause to work, people cross at hotspots, and a forklift drives the corridor. Pedestrians yield before entering vehicle traffic and detour round blocked walking space. The forklift's driver stops for the robot.

## Hazards

Inject from the run page buttons, through the backend (`POST /sim/scenario`), or directly:

```bash
curl -X POST http://localhost:8090/scenario \
  -H "Content-Type: application/json" \
  -d '{"scenario": "spill", "params": {"substance": "hydraulic oil"}}'
```

| Scenario | Effect | Expected gate response |
|----------|--------|------------------------|
| `human_approach` | A worker walks toward the robot and stops about 2.5 m ahead | SLOW (`WORKER_PROXIMITY_06`, `HUMAN_PROXIMITY_02`) |
| `human_too_close` | A worker steps out 0.8 m in front of the robot | STOP |
| `path_blocked` | A pallet is dropped 2 m ahead | REPLAN (`OBSTACLE_CLEARANCE_03`) |
| `spill` | A spill appears 3 m ahead; the warehouse system reports what was spilled | Hazard zone (`HAZARD_EXCLUSION_08`, `HAZARD_SLOW_09`) |
| `forklift_crossing` | The forklift drives across the robot's path on the corridor | REPLAN or hold (moving obstacle) |
| `clear` | Remove injected hazards | SAFE |

## Seeded Replay

```bash
# Replay benchmark scenario 17 exactly (start, goal, people and timing)
curl -X POST http://localhost:8090/seed -H "Content-Type: application/json" \
  -d '{"seed": 17, "mode": "benchmark"}'

# Load a different live site
curl -X POST http://localhost:8090/seed -H "Content-Type: application/json" \
  -d '{"seed": 7, "mode": "live"}'
```

The benchmark response includes the scenario summary and its goal bay. The same call is available through the backend as `POST /sim/seed`.

## Robot Camera

`GET /frame?size=512&view_m=12` returns a heading-up, top-down PNG around the robot, with no text, for a vision model. Through the backend: `GET /sim/frame`.

## Simulator Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Engine, mode and seed |
| `/telemetry` | GET | Robot state, people, vehicles, obstacles and perception |
| `/world` | GET | Geofence, zones, racks, features, bays, obstacles, hotspots |
| `/command` | POST | `MOVE_TO` / `STOP` / `WAIT` |
| `/reset` | POST | Robot back to its start position |
| `/scenarios` | GET | Available hazards |
| `/scenario` | POST | Inject a hazard |
| `/seed` | POST | Benchmark replay or live site by seed |
| `/frame` | GET | Robot camera frame (PNG) |
| `/path/smooth` | POST | Route between waypoints along the aisles |

## Without a Simulator

The governance API still evaluates any input (`POST /governance/evaluate`, the Policies page sandbox), but missions, live telemetry and the warehouse views need a simulator.

## Troubleshooting

### "Connection refused"
- Simulator not running, or wrong `SIM_BASE_URL` (in Docker, use the service name, not `localhost`)

### "401 Unauthorized simulator call"
- `SIM_TOKEN` differs between backend and simulator

### "sim error (needs the warehouse simulator)"
- `/sim/frame` and `/sim/seed` exist only on the warehouse simulator, not the legacy mock simulator

### `ModuleNotFoundError: No module named 'bench'`
- Running locally without `PYTHONPATH=backend`, or building the image from `sim/warehouse_sim` instead of the repo root
