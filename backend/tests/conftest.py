"""Test fixtures: in-memory SQLite database + FastAPI TestClient."""

from __future__ import annotations

import os
import tempfile

# Execution authority: a test-only permit secret (the simulator under test reads the
# same variable) and a throwaway database, set before the app is imported.
os.environ.setdefault("PERMIT_SECRET", "test-permit-secret-0123456789abcdef0123")
# Tests never use real credentials from backend/.env: no paid model calls, no traces sent.
# (Environment variables override the .env file, so blanking them here is enough.)
for _secret in ("MODEL_API_KEY", "BASETEN_API_KEY", "LANGSMITH_API_KEY", "GEMINI_API_KEY",
                "TAVILY_API_KEY", "OTEL_EXPORTER_OTLP_ENDPOINT"):
    os.environ[_secret] = ""
# Tests never talk to a real simulator running on this machine (another project may own
# the default port 8090): a closed port fails fast, and tests that need one start their own.
os.environ["SIM_BASE_URL"] = "http://127.0.0.1:9"
# Most tests check the benchmark warehouse's exact geometry; the factory has its own tests.
os.environ.setdefault("SITE_LAYOUT", "warehouse")
# Lifespan/real-server tests bypass get_db overrides. Keep those databases away
# from local mission state and isolate separate pytest processes from each other.
_test_state_dir = tempfile.mkdtemp(prefix="sovereign-tests-")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_test_state_dir, "app.db").replace("\\", "/")
os.environ["AUTHORITY_DB_PATH"] = os.path.join(_test_state_dir, "authority.db")
os.environ["SIM_STATE_DB"] = os.path.join(_test_state_dir, "controller.db")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.deps import get_db
from app.main import app


@pytest.fixture
def bind_redemption(monkeypatch):
    """Bind simulator callbacks to the real signed-request API without sockets."""
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from app.api.routes_authority import router
    import app.services.execution_authority as ea

    def bind(server, authority):
        monkeypatch.setattr(ea, "_authority", authority)
        api = FastAPI()
        api.include_router(router)
        client = TestClient(api)

        def post(envelope):
            response = client.post("/authority/redeem", json={"request": envelope})
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=response.json()["detail"])
            return response.json()["redemption"]

        monkeypatch.setattr(server, "_post_redemption", post)
        return post

    return bind


# In-memory SQLite engine shared across a test session
_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def _override_get_db():
    db = _TestSession()
    try:
        yield db
    finally:
        db.close()


# Apply dependency override once
app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture(scope="session", autouse=True)
def _create_tables():
    """Create all tables once before the test session."""
    Base.metadata.create_all(bind=_engine)
    yield
    Base.metadata.drop_all(bind=_engine)
