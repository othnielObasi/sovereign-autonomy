from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.http_middleware import InMemoryRateLimiter, RateLimitMiddleware, SecurityHeadersMiddleware
from app.observability.logging import configure_logging
from app.db.session import engine, Base
from sqlalchemy import text
from app.api.routes_health import router as health_router
from app.api.routes_missions import router as missions_router
from app.api.routes_runs import router as runs_router
from app.api.routes_governance import router as governance_router
from app.api.routes_sim import router as sim_router
from app.api.routes_ws import router as ws_router, hub
from app.api.routes_compliance import router as compliance_router
from app.auth.routes import router as auth_router
from app.api.routes_llm import router as llm_router
from app.api.routes_operator import router as operator_router
from app.api.routes_policy_proposals import router as policy_proposals_router
from app.api.routes_site_intel import router as site_intel_router
from app.api.routes_evidence import router as evidence_router
from app.services.run_service import RunService

configure_logging()
logger = logging.getLogger("app")


def _add_missing_nullable_columns() -> None:
    """Development only: create_all() never alters existing tables, so a local
    database made by an older version lacks newer columns. Add any missing
    *nullable* columns in place. Production uses Alembic migrations instead."""
    from sqlalchemy import inspect

    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have or not col.nullable:
                    continue
                ddl = col.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {ddl}'))
                logger.info("Added missing column %s.%s", table.name, col.name)


def init_database(max_retries: int = 5, retry_delay: int = 2):
    """
    Initialize database with retry logic.
    Railway/Fly databases may take a moment to be ready.
    """
    for attempt in range(max_retries):
        try:
            # Test connection
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            
            if settings.migrate_on_start:
                logger.info("✅ Database connection verified; schema managed via Alembic migrations")
            else:
                Base.metadata.create_all(bind=engine)
                _add_missing_nullable_columns()
                logger.info("✅ Database initialized successfully")

            return True
            
        except Exception as e:
            logger.warning(f"⚠️ Database connection attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                logger.error("❌ Failed to connect to database after all retries")
                # Don't crash - allow app to start, health check will fail
                return False
    return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup
    logger.info(f"🚀 Starting Sovereign Autonomy API")
    logger.info(f"   Environment: {settings.environment}")
    logger.info(f"   Planner: {settings.planner_provider} (Nemotron: {'on' if settings.nemotron_configured else 'off'}, Gemini: {'on' if settings.gemini_configured else 'off'})")
    
    init_database()

    # Enforce the most recently activated rules (defaults if none were ever activated)
    try:
        from app.db.session import SessionLocal as _PSL
        from app.policies.params import load_active_from_db
        _pdb = _PSL()
        try:
            logger.info(f"   Policy version: {load_active_from_db(_pdb) or 'defaults'}")
        finally:
            _pdb.close()
    except Exception as _perr:
        logger.error(f"Could not load active policy version, enforcing defaults: {_perr}")

    # Mark stale "running" runs as interrupted on startup.
    # In-memory state (asyncio tasks, plans) is lost across restarts, so
    # blindly resuming dozens of loops overwhelms the simulator and event loop.
    from app.db.session import SessionLocal as _SL
    from app.db.models import Run as _Run, Mission as _Mission
    from app.utils.time import utc_now as _utc_now
    _db = _SL()
    try:
        stale = _db.query(_Run).filter(_Run.status.in_(("running", "planning"))).all()
        if stale:
            logger.info("Startup: marking %d stale runs as interrupted", len(stale))
            mission_ids = set()
            for r in stale:
                r.status = "failed"
                r.ended_at = _utc_now()
                mission_ids.add(r.mission_id)
            # Keep mission status aligned with the failed run state.
            for mid in mission_ids:
                m = _db.query(_Mission).filter(_Mission.id == mid).first()
                if m and m.status == "executing":
                    m.status = "failed"
            _db.commit()
            logger.info("Startup: cleaned up %d stale runs, %d missions reset",
                        len(stale), len(mission_ids))
    except Exception as exc:
        logger.warning("Startup stale-run cleanup failed: %s", exc)
        try:
            _db.rollback()
        except Exception:
            pass
    finally:
        _db.close()
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    # Stop all active runs gracefully
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        for run_id in list(run_service._stop_flags.keys()):
            run_service._stop_flags[run_id].set()
        # Wait briefly for tasks to finish
        import asyncio
        tasks = list(run_service._tasks.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        db.close()
    await run_service.sim.close()


app = FastAPI(
    title="Sovereign Autonomy API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)

app.state.rate_limiter = InMemoryRateLimiter()


@app.get("/")
def root():
    return {
        "name": "Sovereign Autonomy API",
        "status": "ok",
        "docs": "/docs" if settings.docs_enabled else None,
        "health": "/health"
    }


from app.demo_guard import DemoGuardMiddleware  # noqa: E402

app.add_middleware(DemoGuardMiddleware)  # no-op unless PUBLIC_DEMO=true
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware, limiter=app.state.rate_limiter)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With"],
)

# Routers
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(missions_router)
app.include_router(runs_router)
app.include_router(governance_router)
app.include_router(sim_router)
app.include_router(ws_router)
app.include_router(compliance_router)
app.include_router(llm_router)
app.include_router(operator_router)
app.include_router(policy_proposals_router)
app.include_router(site_intel_router)
app.include_router(evidence_router)

# Initialize RunService and bind broadcaster
run_service = RunService()
run_service.bind_broadcaster(hub.broadcast)

# Inject into routes_runs module (simple shared singleton)
import app.api.routes_runs as routes_runs_module
routes_runs_module.run_svc = run_service
