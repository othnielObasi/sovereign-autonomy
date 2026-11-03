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
FRONTEND_PORT = int(os.environ.get("BROWSER_FRONTEND_PORT", "19300"))
BACKEND_PORT = int(os.environ.get("BROWSER_BACKEND_PORT", "18080"))
SIM_PORT = int(os.environ.get("BROWSER_SIM_PORT", "18090"))
STATE = ROOT / "backend/data/browser-validation"
if FRONTEND_PORT != 19300:
    STATE = STATE / f"ports-{FRONTEND_PORT}"


def main():
    for port in (FRONTEND_PORT, BACKEND_PORT, SIM_PORT):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', port))
    STATE.mkdir(parents=True, exist_ok=True)
    stop = STATE / "stop"
    stop.unlink(missing_ok=True)
    session = os.environ.get('BROWSER_VALIDATION_SESSION') or str(time.time_ns())
    if not session.isdigit() or len(session) > 24:
        raise ValueError('BROWSER_VALIDATION_SESSION must be the numeric ID of an isolated validation session')
    env = dict(os.environ)
    for name in ("MODEL_API_KEY", "BASETEN_API_KEY", "NEBIUS_API_KEY", "GEMINI_API_KEY", "LANGSMITH_API_KEY",
                 "TAVILY_API_KEY", "OTEL_EXPORTER_OTLP_ENDPOINT"):
        env[name] = ""
    live_integrations = os.environ.get("BROWSER_LIVE_INTEGRATIONS") == "1"
    if live_integrations:
        from dotenv import dotenv_values
        configured = dotenv_values(ROOT / 'backend/.env')
        # Explicit opt-in, bounded validation only. Do not enable external tracing.
        for name in ("MODEL_API_KEY", "BASETEN_API_KEY", "TAVILY_API_KEY"):
            env[name] = configured.get(name) or ""
        env.update(LLM_ENABLED="true", VISION_ENABLED="false", REQUIRE_LLM_PLAN_AT_START="true")
    env.update(ENVIRONMENT="development", AUTH_REQUIRED="false", ALLOW_DEV_TOKENS="true", AUTH_ACCOUNTS="",
               PUBLIC_DEMO="false", PYTHONIOENCODING="utf-8", RUN_MIGRATIONS_ON_START="false", SITE_LAYOUT=os.environ.get("BROWSER_SITE_LAYOUT", "factory"),
               DATABASE_URL="sqlite:///" + str(STATE / f"app-{session}.db").replace("\\", "/"),
               AUTHORITY_DB_PATH=str(STATE / f"authority-{session}.db"), SIM_STATE_DB=str(STATE / f"controller-{session}.db"),
               EXPERIENCE_ANCHOR_PATH=str(STATE / f'anchor-{session}.sqlite'), RECEIPT_SIGNING_KEY='',
               RECEIPT_SIGNING_KEY_FILE=str(STATE / f'receipt-{session}.key'),
               SIM_BASE_URL=f"http://127.0.0.1:{SIM_PORT}", AUTHORITY_BASE_URL=f"http://127.0.0.1:{BACKEND_PORT}",
               BACKEND_URL=f"http://127.0.0.1:{BACKEND_PORT}", NEXT_DIST_DIR=os.environ.get("BROWSER_NEXT_DIST_DIR", ".next-validation"),
               PERMIT_SECRET="browser-validation-only-secret-0123456789abcdef", SIM_TOKEN="",
               JWT_SECRET="browser-validation-only-jwt-0123456789abcdef", PYTHONPATH=str(ROOT / "backend"))
    env['MEMGRAPH_ENABLED'] = 'true' if os.environ.get('BROWSER_MEMGRAPH_URI') else 'false'
    if os.environ.get('BROWSER_MEMGRAPH_URI'):
        env['MEMGRAPH_URI'] = os.environ['BROWSER_MEMGRAPH_URI']
        env['MEMGRAPH_NAMESPACE'] = 'browser-validation-' + session
    commands = [
        ("sim", ROOT, [sys.executable, "-m", "uvicorn", "server:app", "--app-dir", "sim/warehouse_sim", "--host", "127.0.0.1", "--port", str(SIM_PORT)]),
        ("backend", ROOT / "backend", [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(BACKEND_PORT)]),
        ("frontend", ROOT / "frontend", ["node", "node_modules/next/dist/bin/next", "start", "--hostname", "127.0.0.1", "--port", str(FRONTEND_PORT)]),
    ]
    processes, logs = [], []
    try:
        for name, cwd, command in commands:
            log = (STATE / f"{name}.log").open("w", encoding="utf-8")
            logs.append(log)
            processes.append(subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0))
        deadline = time.monotonic() + 180
        for url in (f"http://127.0.0.1:{SIM_PORT}/health", f"http://127.0.0.1:{BACKEND_PORT}/health", f"http://127.0.0.1:{FRONTEND_PORT}/authority"):
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
        print(f"Validation stack ready at http://127.0.0.1:{FRONTEND_PORT}", flush=True)
        if live_integrations:
            print('Live validation: no synthetic experience seeded', flush=True)
        else:
            # Signed fixture for exercising eligibility/rejection in the isolated UI;
            # it is labelled explicitly and is not presented as a real mission outcome.
            os.environ.update(env)
            sys.path.insert(0, str(ROOT / "backend"))
            from app.autonomy.experience import context_from_state
            from app.services.route_learning import RouteMemory
            telemetry = httpx.get(f"http://127.0.0.1:{SIM_PORT}/telemetry", trust_env=False).json()
            policy = httpx.get(f"http://127.0.0.1:{BACKEND_PORT}/agent/lessons", trust_env=False).json()["policy_version"]
            context = context_from_state(telemetry, policy)
            fixture = RouteMemory(env["AUTHORITY_DB_PATH"], env["PERMIT_SECRET"].encode(), anchor_path=env['EXPERIENCE_ANCHOR_PATH'])
            for source in ['robot-A (fixture)', 'robot-C (fixture)']:
                fixture.record(f"browser-fixture-{source}-{time.time_ns()}", [((6, 7), 4.0, "STOP")],
                               context=context, source_robot_id=source)
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
