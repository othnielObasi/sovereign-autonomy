"""Send one test trace to LangSmith and confirm it arrived. Never prints the key.

    cd backend && python ../scripts/check_langsmith.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.config import settings  # noqa: E402
from app.observability import tracing  # noqa: E402


def main() -> int:
    if not settings.langsmith_api_key:
        print("LANGSMITH_API_KEY is not set (add it to backend/.env and .env)")
        return 1
    print(f"Project: {settings.langsmith_project}   Endpoint: {settings.langsmith_endpoint}")
    run_id = f"check-{int(time.time())}"
    tracing.mission_start(run_id, "check", "LangSmith connectivity check", {"x": 0, "y": 0})
    with tracing.within_mission(run_id):
        tracing.llm_call(model="check-model", provider="check", tier="check", prompt="ping", output="pong")
    tracing.mission_event(run_id, "gate", inputs={"proposal": "check"}, outputs={"decision": "APPROVED"})
    tracing.mission_end(run_id, "completed")
    tracing.flush()
    time.sleep(3)
    try:
        client = tracing._get_client()
        runs = list(client.list_runs(project_name=settings.langsmith_project, filter='eq(name, "mission")', limit=5))
        found = any((r.extra or {}).get("metadata", {}).get("run_id") == run_id for r in runs)
    except Exception as exc:
        text = str(exc)
        if any(code in text for code in ("401", "403", "Forbidden", "Unauthorized", "permission")):
            # A "Tracing Only" key is write-only: it can send traces but not read them back.
            print("Trace sent. This key is write-only (Tracing Only), so it cannot read traces back;")
            print(f"open the '{settings.langsmith_project}' project in LangSmith and look for a 'mission' trace "
                  f"named with run_id {run_id}.")
            return 0
        print(f"Could not read back from LangSmith: {type(exc).__name__}: {exc}")
        return 1
    print("Trace received by LangSmith." if found else "Trace sent but not visible yet; check the project in the LangSmith UI.")
    return 0 if found else 2


if __name__ == "__main__":
    sys.exit(main())
