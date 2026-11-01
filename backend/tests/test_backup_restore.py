"""Disaster recovery: back up, lose everything, restore. Kill switches still hold,
used permits stay used, the journal is intact, and bad backups are refused."""
from __future__ import annotations

import json
import os
import sqlite3
import time

import pytest

from app.autonomy.core import Action, Rejected
from app.ops import backup as B
from app.services.execution_authority import ExecutionAuthority

SECRET = os.environ["PERMIT_SECRET"]


@pytest.fixture
def live(tmp_path):
    """A live system's state: an app database with a run, and an authority database with
    a used permit, a dispatched action and an active kill switch."""
    app_db = tmp_path / "live" / "app.db"
    app_db.parent.mkdir()
    conn = sqlite3.connect(app_db)
    conn.execute("CREATE TABLE runs (id TEXT PRIMARY KEY, status TEXT)")
    conn.execute("INSERT INTO runs VALUES ('run-1', 'running')")
    conn.commit()
    conn.close()

    auth_db = tmp_path / "live" / "authority.db"
    a = ExecutionAuthority(secret=SECRET, db_path=str(auth_db))
    a.observe({"x": 3.0, "y": 3.5})
    action, token = a.authorize(run_id="run-1", mission_id="mis-1", intent="MOVE_TO",
                                params={"x": 4.0, "y": 3.5}, decision="APPROVED", policy_version="v")
    a.permits.consume(token, action)
    a.checkpoints.begin_action(action)
    a.checkpoints.reconcile(action.action_id, controller_verified=True, executed=True)
    a.kills.activate("mission", "mis-2")
    conn = a._db()
    try:
        with conn:
            conn.execute("INSERT INTO kill_locks VALUES ('mission', 'mis-2', 'drill', 'op', 0)")
    finally:
        conn.close()
    return {"app_db": app_db, "auth_db": auth_db, "url": f"sqlite:///{app_db}", "token": token, "action": action,
            "out": tmp_path / "backups"}


def _create(live):
    return B.create(live["out"], database_url=live["url"], authority_db=live["auth_db"], secret=SECRET)


def test_backup_verifies(live):
    bk = _create(live)
    res = B.verify(bk, secret=SECRET)
    assert res["ok"], res["problems"]
    assert set(res["files"]) == {"app.db", "authority.db"} and res["journal_intact"] is True


def test_full_loss_then_restore(live):
    bk = _create(live)
    os.remove(live["app_db"])
    os.remove(live["auth_db"])                          # the disaster

    with pytest.raises(SystemExit, match="Stop the backend"):
        B.restore(bk, database_url=live["url"], authority_db=live["auth_db"], secret=SECRET, backend_stopped=False)
    t0 = time.monotonic()
    out = B.restore(bk, database_url=live["url"], authority_db=live["auth_db"], secret=SECRET, backend_stopped=True)
    rto = time.monotonic() - t0
    assert len(out["restored"]) == 2 and rto < 5

    conn = sqlite3.connect(live["app_db"])
    assert conn.execute("SELECT status FROM runs WHERE id='run-1'").fetchone() == ("running",)
    conn.close()

    a = ExecutionAuthority(secret=SECRET, db_path=str(live["auth_db"]))
    assert ("mission", "mis-2") in a.kills.active()                 # kill switch survived
    a.observe({"x": 3.0, "y": 3.5})
    with pytest.raises(Rejected, match="kill"):
        a.authorize(run_id="r", mission_id="mis-2", intent="MOVE_TO", params={"x": 4, "y": 3.5},
                    decision="APPROVED", policy_version="v")
    with pytest.raises(Rejected):                                    # used permit stays used
        a.permits.consume(live["token"], live["action"])
    assert a.checkpoints.status(live["action"].action_id) == "COMPLETED"
    assert a.checkpoints.verify_chain()


def test_tampered_or_foreign_backups_are_refused(live):
    bk = _create(live)
    with open(bk / "authority.db", "r+b") as f:     # flip bytes in the copy
        f.seek(200)
        f.write(b"\x00\xff\x00\xff")
    assert any("changed" in p for p in B.verify(bk, secret=SECRET)["problems"])
    with pytest.raises(SystemExit, match="invalid backup"):
        B.restore(bk, database_url=live["url"], authority_db=live["auth_db"], secret=SECRET, backend_stopped=True)

    bk2 = B.create(live["out"] / "b2", database_url=live["url"], authority_db=live["auth_db"], secret=SECRET)
    m = json.loads((bk2 / "manifest.json").read_text())
    m["files"]["app.db"]["bytes"] += 1
    (bk2 / "manifest.json").write_text(json.dumps(m))
    assert any("signature" in p for p in B.verify(bk2, secret=SECRET)["problems"])

    bk3 = B.create(live["out"] / "b3", database_url=live["url"], authority_db=live["auth_db"], secret=SECRET)
    assert any("signature" in p for p in B.verify(bk3, secret="another-secret-0123456789abcdef0123")["problems"])
    (bk3 / "planted.sql").write_text("DROP TABLE runs;")
    assert any("unexpected" in p for p in B.verify(bk3, secret=SECRET)["problems"])


def test_backup_is_consistent_while_the_backend_writes(live):
    """SQLite online backup: a copy taken mid-write still passes integrity checks."""
    import threading
    stop = threading.Event()

    def writer():
        conn = sqlite3.connect(live["app_db"])
        i = 0
        while not stop.is_set():
            conn.execute("INSERT OR REPLACE INTO runs VALUES (?, 'running')", (f"w-{i}",))
            conn.commit()
            i += 1
        conn.close()

    t = threading.Thread(target=writer)
    t.start()
    try:
        bk = _create(live)
    finally:
        stop.set()
        t.join()
    assert B.verify(bk, secret=SECRET)["ok"]


def test_cli_needs_a_permit_secret(live):
    with pytest.raises(SystemExit, match="PERMIT_SECRET"):
        B.create(live["out"], database_url=live["url"], authority_db=live["auth_db"], secret="short")
