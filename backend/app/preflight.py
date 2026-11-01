from __future__ import annotations

"""Preflight checks for container startup.

- ensures data directory exists for SQLite
- optionally applies Alembic migrations with retry
- prints config summary
"""

import os
import subprocess
import time

from app.config import settings


def run_migrations(max_retries: int = 5, retry_delay: int = 3) -> None:
    if not settings.migrate_on_start:
        print("Skipping Alembic migrations")
        return

    for attempt in range(1, max_retries + 1):
        print(f"Running Alembic migrations (attempt {attempt}/{max_retries})")
        result = subprocess.run(["alembic", "upgrade", "head"])
        if result.returncode == 0:
            print("Alembic migrations applied successfully")
            return
        if attempt < max_retries:
            print(f"Migration attempt {attempt} failed, retrying in {retry_delay}s...")
            time.sleep(retry_delay)
        else:
            raise RuntimeError(f"Alembic migrations failed after {max_retries} attempts")


def main():
    os.makedirs("data", exist_ok=True)
    run_migrations()
    # Mask credentials in DATABASE_URL
    db_url = settings.database_url
    if "@" in db_url:
        # Hide password: show scheme + host only
        parts = db_url.split("@")
        db_url = parts[0].split("://")[0] + "://***@" + parts[-1]
    print("Preflight OK")
    print(f"DATABASE_URL={db_url}")
    print(f"SIM_BASE_URL={settings.sim_base_url}")
    print(f"CORS_ORIGINS={settings.cors_origins}")


if __name__ == "__main__":
    main()
