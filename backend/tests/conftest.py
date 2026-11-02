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
os.environ.setdefault("AUTHORITY_DB_PATH", os.path.join(tempfile.mkdtemp(prefix="authority-"), "authority.db"))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.deps import get_db
from app.main import app


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
