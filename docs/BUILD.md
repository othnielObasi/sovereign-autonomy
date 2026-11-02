# Build & Deployment Guide

> Sovereign Autonomy — an autonomous robotics governance platform.

This document covers every way to build, run, and deploy the project: local
development and Docker Compose. Production deployment (Scaleway) will be added later.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Prerequisites](#prerequisites)
3. [Environment Variables](#environment-variables)
4. [Local Development (Docker Compose)](#local-development-docker-compose)
5. [Local Development (No Docker)](#local-development-no-docker)
6. [Production](#production)
7. [Database & Migrations](#database--migrations)
8. [Running Tests](#running-tests)
9. [CI](#ci)
10. [Monitoring](#monitoring)
11. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

```
┌────────────┐      ┌────────────┐      ┌────────────┐
│  Frontend   │ ───▶ │  Backend   │ ───▶ │ Simulator  │
│  Next.js    │      │  FastAPI   │      │  FastAPI    │
│  :3000      │      │  :8080     │      │  :8090      │
└────────────┘      └─────┬──────┘      └────────────┘
                          │
                    ┌─────▼──────┐
                    │ PostgreSQL │
                    │  :5432     │
                    └────────────┘
```

| Service       | Technology               | Port | Source Directory   |
|---------------|--------------------------|------|--------------------|
| **Frontend**  | Next.js 14, React 18, TypeScript, Tailwind CSS | 3000 | `frontend/` |
| **Backend**   | FastAPI, Python 3.11, SQLAlchemy, Alembic       | 8080 | `backend/`  |
| **Simulator** | FastAPI, Python 3.11 (live warehouse on the benchmark engine) | 8090 | `sim/warehouse_sim/` (+ `backend/bench/`) |
| **Database**  | PostgreSQL 16 (production) / SQLite (dev fallback)| 5432 | — |

The original mock simulator (`sim/mock_sim/`) is kept for comparison under the Compose `legacy` profile.

In production, a **Caddy** reverse proxy sits in front of
everything, gets the TLS certificate automatically, and routes traffic:

- `https://<site>/` → frontend (`:3000`)
- `https://<site>/api/*` → backend (`:8080`, path prefix stripped)
- `https://<site>/ws/*`, `/docs`, `/openapi.json`, `/health` → backend (direct)

---

## Prerequisites

| Tool           | Version  | Purpose                |
|----------------|----------|------------------------|
| Docker         | ≥ 24     | Container builds       |
| Docker Compose | ≥ 2.20   | Service orchestration  |
| Python         | ≥ 3.10   | Backend (if running bare-metal) |
| Node.js        | ≥ 20     | Frontend (if running bare-metal) |
| Git            | ≥ 2.x    | Source control         |

Docker is the recommended path — it handles all dependencies automatically.

---

## Environment Variables

Copy the example file and fill in your values:

```bash
cp .env.example .env
```

### Required in Production

| Variable             | Description                                    | Example                          |
|----------------------|------------------------------------------------|----------------------------------|
| `DATABASE_URL`       | PostgreSQL connection string                   | `postgresql://sovereign:secret@db:5432/sovereign` |
| `JWT_SECRET`         | Secret key for JWT token signing               | *(auto-generated in dev)*        |
| `SIM_TOKEN`          | Shared auth token for simulator API            | *(empty in dev = no auth)*       |
| `POSTGRES_PASSWORD`  | PostgreSQL password (production compose)       | `openssl rand -hex 32`           |
| `RECEIPT_SIGNING_KEY`| Base64 Ed25519 private key for signed receipts | *(dev key created in `data/`)*   |

### AI and Site Intelligence

| Variable               | Default                         | Description                          |
|------------------------|---------------------------------|--------------------------------------|
| `MODEL_API_KEY`        | —                               | Meta Model API key: Muse Spark, SAM 3.1, Muse Voice Transcribe |
| `BASETEN_API_KEY`      | —                               | Baseten key: Muse Spark Open (per-step proposals) |
| `LLM_ENABLED`          | `false`                         | `true` lets the models propose each step too |
| `LLM_PROVIDER`         | `muse`                          | `muse`, `gemini`, `agentic` or `mock` |
| `MUSE_REASONING_MODEL` | `muse-spark-1.3`                | Mission planning and replanning |
| `MUSE_OPEN_MODEL`      | `meta-models/muse-spark-open-1026` | Per-step proposals |

Check every Meta model with `cd backend && python ../scripts/check_meta.py`.

### Other Optional Variables

| Variable               | Default                         | Description                          |
|------------------------|---------------------------------|--------------------------------------|
| `ENVIRONMENT`          | `development`                   | Set to `production` for prod guards  |
| `AUTH_REQUIRED`        | `true` in production, else `false` | Enforce authentication            |
| `CORS_ORIGINS`         | `http://localhost:3000`         | Allowed CORS origins (comma-separated) |
| `SIM_BASE_URL`         | `http://localhost:8090`         | Simulator endpoint                   |
| `NEXT_PUBLIC_API_BASE` | `/api`                          | Frontend → backend API prefix        |
| `BACKEND_URL`          | `http://localhost:8080`         | Where the Next.js dev server proxies `/api` |
| `SIM_TICK_HZ`          | `10`                            | Simulator physics rate               |
| `SIM_SEED`             | `42`                            | Simulator seed (same seed, same session) |

> **Note:** In production mode (`ENVIRONMENT=production`), the backend will
> refuse to start if `JWT_SECRET` or `SIM_TOKEN` are missing.
>

---

## Local Development (Docker Compose)

The fastest way to get everything running:

```bash
# 1. Clone the repository
git clone https://github.com/othnielObasi/sovereign-autonomy.git
cd sovereign-autonomy

# 2. Optional: create a .env file for API keys (Meta, Baseten, Tavily)
cp .env.example .env
# Set MODEL_API_KEY, BASETEN_API_KEY, LLM_ENABLED=true, PERMIT_SECRET, TAVILY_API_KEY

# 3. Build and start all services
docker compose up --build
```

This uses `docker-compose.yml` and starts four containers. The backend and frontend read `.env` if it exists; the local Postgres password is fixed (`sovereign`) in the compose file.

| Container       | Image                                | Exposed Port |
|-----------------|--------------------------------------|-------------|
| `frontend`      | `frontend/Dockerfile`                | `3000`      |
| `backend`       | `backend/Dockerfile`                 | `8080`      |
| `warehouse-sim` | `sim/warehouse_sim/Dockerfile` (built from the repo root) | `8090` |
| `postgres`      | `postgres:16`                        | `5432`      |

The legacy mock simulator starts only with `docker compose --profile legacy up mock-sim` (port `8091`).

The backend runs Alembic migrations on startup via `app.preflight`.

**Access points:**

- Dashboard: http://localhost:3000
- API docs: http://localhost:8080/docs
- Health check: http://localhost:8080/health
- Simulator: http://localhost:8090/health

### Hot Reload

- **Backend**: The local compose file mounts `./backend:/app`, so code changes
  are picked up by Uvicorn's auto-reload.
- **Frontend**: Runs via `npm run dev` with Next.js fast refresh.

### Stopping

```bash
docker compose down          # stop containers
docker compose down -v       # stop + remove volumes (wipes DB)
```

---

## Local Development (No Docker)

If you prefer running services directly:

### Backend

```bash
cd backend

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev,postgres]"

# Run database migrations (uses SQLite by default at data/app.db)
python -m app.preflight

# Start the server
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

### Simulator

From the repository root (the simulator imports the benchmark engine from `backend/bench`):

```bash
pip install -r sim/warehouse_sim/requirements.txt
PYTHONPATH=backend uvicorn server:app --app-dir sim/warehouse_sim --host 0.0.0.0 --port 8090
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000. The Next.js dev server rewrites `/api/*` requests
to `http://localhost:8080` automatically (see `next.config.js`).

---

## Production

A production deployment (Scaleway) will be added later. Until then, use the
Docker Compose stack above.

---

## Database & Migrations

### Engine Selection

| Environment   | Engine       | Connection String                        |
|---------------|-------------|------------------------------------------|
| Development   | SQLite       | `sqlite:///./data/app.db` (default)      |
| Production    | PostgreSQL 16| `postgresql://sovereign:<pw>@db:5432/sovereign`      |

Set `DATABASE_URL` to switch engines. The ORM layer (SQLAlchemy) abstracts
the difference.

### Running Migrations

Migrations run automatically on startup via `app.preflight` (with retry logic).
To run manually:

```bash
cd backend
alembic upgrade head
```

### Creating a New Migration

```bash
cd backend
alembic revision --autogenerate -m "describe_your_change"
```

Review the generated file in `alembic/versions/`, then apply:

```bash
alembic upgrade head
```

### Backing Up PostgreSQL (Production)

To keep daily backups on the server, add a cron job such as:

```
0 3 * * * docker compose exec -T postgres pg_dump -U sovereign sovereign | gzip > /opt/sovereign/backups/sovereign-$(date +\%Y\%m\%d).sql.gz
```

Prune old files to keep about a week of backups.

---

## Running Tests

### Backend Tests

```bash
cd backend
pip install -e ".[dev]"
pytest -q                # 221 tests
```

Run from `backend/`: the benchmark tests import the `bench` package from there.

Key test files:

| File                    | Coverage                                 |
|-------------------------|------------------------------------------|
| `tests/test_api_smoke.py`       | API endpoint smoke tests          |
| `tests/test_governance.py`      | Governance engine logic           |
| `tests/test_live_safety.py`     | Live run loop: denied moves stop the robot; nothing unapproved executes |
| `tests/test_bench.py`           | Benchmark engine, arms and report |
| `tests/test_model_runtime.py`   | Muse planner tiers, fallback and usage log |
| `tests/test_planner_lessons.py` | Lessons from gate decisions       |
| `tests/test_governed_rules_and_signing.py` | Rule-change workflow and Ed25519 receipts |
| `tests/test_site_intel.py`      | Tavily firewall, corroboration, hazard zones |
| `tests/test_safety_validator.py`| Post-run safety validation        |
| `tests/test_plan_execution.py`  | Plan execution pipeline           |
| `tests/test_reward_hacking.py`  | Adversarial / reward hacking      |
| `tests/test_phase_abc.py`, `test_phase_d.py`, `test_new_services.py` | Earlier feature phases |
| `tests/test_startup_cleanup.py` | Startup and cleanup behaviour     |

### Simulator and Browser Tests

From the repository root:

```bash
python -m pytest tests/test_live_traffic.py -q   # live site traffic

npm install                                      # Playwright
APP_URL=http://127.0.0.1:3000 node tests/warehouse-ui.smoke.cjs
APP_URL=http://127.0.0.1:3000 node tests/warehouse-parity.smoke.cjs
```

The browser tests need the frontend running. They serve every API and WebSocket
call from fixtures and fail on any mutation, so they never move a robot. Set
`PLAYWRIGHT_CHROMIUM_EXECUTABLE` if Playwright's own Chromium is not installed.

### Frontend Build Verification

```bash
cd frontend
npm install
npm run build    # Type checks + production build
```

### Docker Build Verification

```bash
docker compose build                          # dev images
```

---

## CI

`.github/workflows/ci.yml` runs on every push and pull request to `main`:
backend tests, the frontend build, and Docker builds of the backend, mock
simulator and warehouse simulator. Deployment is manual (see above).

---

## Monitoring

### Health Endpoint

```bash
curl https://your-domain.com/health
# {"status":"ok","checks":{"database":"ok","simulator":"ok"}}
```

The health endpoint always returns HTTP 200. Dependency status is informational
in the JSON payload — not a fatal error code — so Docker healthchecks remain
stable during transient simulator hiccups.

### Grafana Dashboard

An optional Prometheus-based Grafana dashboard is included at
`infra/grafana/dashboard.json`. It tracks:

- Governance decision counts and approval rate
- Average risk score
- Policy violations by type
- Decision throughput over time
- Policy evaluation latency (p50 / p99)

### API Documentation

- **Swagger UI**: `https://your-domain.com/docs`
- **ReDoc**: `https://your-domain.com/redoc`
- **OpenAPI spec**: `https://your-domain.com/openapi.json`

---

## Troubleshooting

### "Cannot reach simulator"

The backend can't connect to the simulator on port 8090.

- **Local**: Make sure the simulator is running — `docker compose up warehouse-sim`
- **Docker**: Verify `SIM_BASE_URL` uses the container hostname, not `localhost`
  (`http://warehouse-sim:8090` in `docker-compose.yml`)

### Simulator exits with `No module named 'bench'`

Build the warehouse simulator image from the repository root
(`docker build -f sim/warehouse_sim/Dockerfile .`), or run it locally with
`PYTHONPATH=backend`.

### Planning always uses the deterministic fallback

`LLM_ENABLED` must be `true` and `MODEL_API_KEY` set in the backend's own
environment. Check with `GET /llm/models`.

### Frontend shows "loading" indefinitely

The frontend API calls are failing silently.

- Check that `NEXT_PUBLIC_API_BASE` is correct and was set **at build time**
  (it's baked into the Next.js bundle)
- In dev, verify the `next.config.js` rewrite points to port `8080`
- Check browser DevTools → Network tab for failing `/api/*` requests

### Backend container keeps restarting

Check logs: `docker compose logs backend`

Common causes:
- Database not ready yet — the backend retries migrations 5 times (3s apart)
- Missing required env vars in production (`JWT_SECRET`, `SIM_TOKEN`)
- Port conflict on 8080

### Database migration errors

```bash
cd backend
alembic heads          # check for multiple heads
alembic history        # view migration chain
alembic upgrade head   # apply pending migrations
```

### Out of memory

The full stack (frontend, backend, simulator, PostgreSQL, Caddy) needs about
4 GB. Check usage with `docker stats --no-stream`.
