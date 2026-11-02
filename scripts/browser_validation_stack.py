"""Isolated, key-free local stack for browser regression checks.

Build first: NEXT_DIST_DIR=.next-validation BACKEND_URL=http://127.0.0.1:18080 npm run build
Run from repo root with its .venv Python. Create backend/data/browser-validation/stop
to shut down only these child processes. Logs and databases stay in that directory.
"""
import os
from pathlib import Path
import subprocess
import socket
import sys
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "backend/data/browser-validation"


def main():
    for port in (19300, 18080, 18090):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', port))
    STATE.mkdir(parents=True, exist_ok=True)
    stop = STATE / "stop"
    stop.unlink(missing_ok=True)
    session = str(time.time_ns())
    env = dict(os.environ)
    for name in ("MODEL_API_KEY", "BASETEN_API_KEY", "NEBIUS_API_KEY", "GEMINI_API_KEY", "LANGSMITH_API_KEY",
                 "TAVILY_API_KEY", "OTEL_EXPORTER_OTLP_ENDPOINT"):
        env[name] = ""
    env.update(ENVIRONMENT="development", AUTH_REQUIRED="false", ALLOW_DEV_TOKENS="true", AUTH_ACCOUNTS="",
               PUBLIC_DEMO="false", PYTHONIOENCODING="utf-8", RUN_MIGRATIONS_ON_START="false", SITE_LAYOUT="factory",
               DATABASE_URL="sqlite:///" + str(STATE / f"app-{session}.db").replace("\\", "/"),
               AUTHORITY_DB_PATH=str(STATE / f"authority-{session}.db"), SIM_STATE_DB=str(STATE / f"controller-{session}.db"),
               SIM_BASE_URL="http://127.0.0.1:18090", AUTHORITY_BASE_URL="http://127.0.0.1:18080",
               BACKEND_URL="http://127.0.0.1:18080", NEXT_DIST_DIR=".next-validation",
               PERMIT_SECRET="browser-validation-only-secret-0123456789abcdef", SIM_TOKEN="",
               JWT_SECRET="browser-validation-only-jwt-0123456789abcdef", PYTHONPATH=str(ROOT / "backend"))
    commands = [
        ("sim", ROOT, [sys.executable, "-m", "uvicorn", "server:app", "--app-dir", "sim/warehouse_sim", "--host", "127.0.0.1", "--port", "18090"]),
        ("backend", ROOT / "backend", [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "18080"]),
        ("frontend", ROOT / "frontend", ["node", "node_modules/next/dist/bin/next", "start", "--hostname", "127.0.0.1", "--port", "19300"]),
    ]
    processes, logs = [], []
    try:
        for name, cwd, command in commands:
            log = (STATE / f"{name}.log").open("w", encoding="utf-8")
            logs.append(log)
            processes.append(subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0))
        deadline = time.monotonic() + 180
        for url in ("http://127.0.0.1:18090/health", "http://127.0.0.1:18080/health", "http://127.0.0.1:19300/authority"):
            while True:
                if any(p.poll() is not None for p in processes):
                    raise RuntimeError("validation service exited; inspect local logs")
                try:
                    if httpx.get(url, timeout=2, trust_env=False).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.monotonic() > deadline:
                    raise TimeoutError("validation stack not ready")
                time.sleep(0.25)
        print("Validation stack ready at http://127.0.0.1:19300", flush=True)
        # Signed fixture for exercising eligibility/rejection in the isolated UI;
        # it is labelled explicitly and is not presented as a real mission outcome.
        os.environ.update(env)
        sys.path.insert(0, str(ROOT / "backend"))
        from app.autonomy.experience import context_from_state
        from app.services.route_learning import RouteMemory
        telemetry = httpx.get("http://127.0.0.1:18090/telemetry", trust_env=False).json()
        policy = httpx.get("http://127.0.0.1:18080/agent/lessons", trust_env=False).json()["policy_version"]
        context = context_from_state(telemetry, policy)
        RouteMemory(env["AUTHORITY_DB_PATH"], env["PERMIT_SECRET"].encode()).record(
            f"browser-fixture-{time.time_ns()}", [((6, 7), 4.0, "STOP")], context=context, source_robot_id="robot-A (fixture)")
        print("Signed browser fixture ready", flush=True)
        while not stop.exists():
            if any(p.poll() is not None for p in processes):
                raise RuntimeError("validation service exited")
            time.sleep(0.5)
    finally:
        for process in reversed(processes):
            if os.name == 'nt' and process.poll() is None:
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            elif process.poll() is None:
                process.terminate()
        for process in reversed(processes):
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for log in logs:
            log.close()


if __name__ == "__main__":
    main()
