from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import StaticPool

from app.config import settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    # SQLite needs special args for threading and relative paths
    if settings.database_url.startswith("sqlite"):
        if ":memory:" in settings.database_url or settings.database_url.rstrip("/") == "sqlite:":
            # in-memory databases exist per connection, so share exactly one
            return create_engine(settings.database_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
        # File database: one connection per thread (a single shared connection
        # corrupts concurrent requests), WAL so readers don't block the writer.
        eng = create_engine(
            settings.database_url,
            connect_args={"check_same_thread": False, "timeout": 30},
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
        )

        @event.listens_for(eng, "connect")
        def _sqlite_pragmas(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

        return eng
    return create_engine(settings.database_url, pool_pre_ping=True)


engine = _make_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
