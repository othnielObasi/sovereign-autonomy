# Simulation

Two simulators expose the base HTTP API (`/telemetry`, `/world`, `/command`, `/scenario`, `/reset`). The execution-authority admission contract is implemented by the warehouse simulator:

- **`warehouse_sim/` (default)** — runs the safety benchmark's deterministic engine (`backend/bench/world.py`) in real time: solid racks, workers moving between tasks and crossing at hotspots, a forklift on the corridor, hazards on demand (spill, dropped pallet, worker stepping out, forklift crossing), exact replay of any benchmark scenario by seed (`POST /seed`), and a robot camera frame (`GET /frame`).
- **`mock_sim/` (legacy)** — the original lightweight simulator, with 10 scripted scenarios and demo sequences. Start it with `docker compose --profile legacy up mock-sim` (port 8091).

Run the warehouse simulator locally from the repository root:

```bash
pip install -r sim/warehouse_sim/requirements.txt
# Set the same PERMIT_SECRET in this process and the backend before starting.
export AUTHORITY_BASE_URL=http://127.0.0.1:8080
PYTHONPATH=backend uvicorn server:app --app-dir sim/warehouse_sim --port 8090
```

Build its image from the repository root, since it copies the engine from `backend/bench`:

```bash
docker build -f sim/warehouse_sim/Dockerfile -t sovereign-autonomy-warehouse-sim .
```

Configuration, hazards and endpoints: [docs/SIMULATOR_CONFIG.md](../docs/SIMULATOR_CONFIG.md).

Persist `SIM_STATE_DB` (default `data/controller.db`). Each move requires a signed, single-use redemption from the backend; a callback failure refuses new movement. Compose sets the callback URL and mounts the `controller_data` volume.

A bridge for Webots, Isaac Sim, Gazebo or a physical robot must implement controller redemption, local stop fencing, and appropriate local safety controls in addition to the base HTTP API. This repository does not establish a physical robot integration.
