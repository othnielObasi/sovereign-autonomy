# Simulation

Two simulators speak the same HTTP API (`/telemetry`, `/world`, `/command`, `/scenario`, `/reset`), so the backend works with either:

- **`warehouse_sim/` (default)** — runs the safety benchmark's deterministic engine (`backend/bench/world.py`) in real time: solid racks, workers moving between tasks and crossing at hotspots, a forklift on the corridor, hazards on demand (spill, dropped pallet, worker stepping out, forklift crossing), exact replay of any benchmark scenario by seed (`POST /seed`), and a robot camera frame (`GET /frame`).
- **`mock_sim/` (legacy)** — the original lightweight simulator, with 10 scripted scenarios and demo sequences. Start it with `docker compose --profile legacy up mock-sim` (port 8091).

Run the warehouse simulator locally from the repository root:

```bash
pip install -r sim/warehouse_sim/requirements.txt
PYTHONPATH=backend uvicorn server:app --app-dir sim/warehouse_sim --port 8090
```

Build its image from the repository root, since it copies the engine from `backend/bench`:

```bash
docker build -f sim/warehouse_sim/Dockerfile -t sovereign-autonomy-warehouse-sim .
```

Configuration, hazards and endpoints: [docs/SIMULATOR_CONFIG.md](../docs/SIMULATOR_CONFIG.md).

Either simulator can be replaced by Webots, Isaac Sim, Gazebo or a physical robot through a ROS 2 or HTTP bridge that serves the same API.
