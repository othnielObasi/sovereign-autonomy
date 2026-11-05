FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /app/pyproject.toml
ARG BACKEND_EXTRAS=postgres
RUN pip install --no-cache-dir ".[${BACKEND_EXTRAS}]"

FROM python:3.11-slim

WORKDIR /app
ENV MUJOCO_GL=disable

RUN groupadd -r sovereign && useradd -r -g sovereign -d /app -s /sbin/nologin sovereign

# pg_dump/psql for app.ops.backup (signed backups of the Postgres database)
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY pyproject.toml /app/pyproject.toml
COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic
COPY app /app/app
COPY bench /app/bench
RUN mkdir -p /app/data /anchors && chown -R sovereign:sovereign /app/data /anchors

USER sovereign

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

CMD ["sh", "-c", "python -m app.preflight && uvicorn app.main:app --host 0.0.0.0 --port 8080"]
