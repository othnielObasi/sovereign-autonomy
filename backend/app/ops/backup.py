"""Backup, verify and restore: the disaster-recovery path.

    python -m app.ops.backup create  [--out backups/]
    python -m app.ops.backup verify  backups/<stamp>
    python -m app.ops.backup restore backups/<stamp> --backend-stopped

What a backup holds:
  app.db         missions, runs, hash-chained events, signed receipts (SQLite), or
  app.sql        a pg_dump when DATABASE_URL is PostgreSQL
  authority.db   permit journal, action reconciliation, kill switches, learning memory
  manifest.json  size and SHA-256 of every file, signed with a key derived from
                 PERMIT_SECRET, so a tampered or partial backup is refused

The receipt signing key is NOT included: it is a private key and belongs in the
secret store (RECEIPT_SIGNING_KEY). See docs/RUNBOOK.md.

SQLite files are copied with SQLite's online backup API, so a backup taken while the
backend runs is still consistent. Restore requires the backend to be stopped; after a
restore, interrupted runs come back paused, kill switches still hold, and every move
needs a new permit (old permits expire within seconds).
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

FORMAT = "sovereign-autonomy-backup/1"


def _sqlite_path(database_url: str) -> Optional[Path]:
    if database_url.startswith("sqlite:///"):
        return Path(database_url[len("sqlite:///"):])
    return None


def _manifest_key(secret: str) -> bytes:
    return hmac.new(secret.encode() or b"unset", b"backup-manifest-v1", hashlib.sha256).digest()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sqlite_copy(src: Path, dst: Path) -> None:
    """Consistent copy of a live SQLite database."""
    s = sqlite3.connect(str(src))
    d = sqlite3.connect(str(dst))
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()


def _sign(manifest: Dict[str, Any], secret: str) -> str:
    body = json.dumps({k: v for k, v in manifest.items() if k != "signature"}, sort_keys=True).encode()
    return hmac.new(_manifest_key(secret), body, hashlib.sha256).hexdigest()


def create(out_dir: Path, *, database_url: str, authority_db: Path, secret: str) -> Path:
    if len(secret) < 32:
        raise SystemExit("PERMIT_SECRET (32+ characters) is needed to sign the backup manifest")
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    target = out_dir / stamp
    target.mkdir(parents=True, exist_ok=False)
    files: Dict[str, Dict[str, Any]] = {}

    app_db = _sqlite_path(database_url)
    if app_db is not None:
        if app_db.exists():
            _sqlite_copy(app_db, target / "app.db")
    else:
        dump = target / "app.sql"
        with open(dump, "wb") as f:
            subprocess.run(["pg_dump", "--no-owner", "--format=plain", database_url], stdout=f, check=True)
    if authority_db.exists():
        _sqlite_copy(authority_db, target / "authority.db")

    for p in sorted(target.iterdir()):
        files[p.name] = {"bytes": p.stat().st_size, "sha256": _sha256(p)}
    manifest = {"format": FORMAT, "created_at": time.time(), "created_utc": stamp,
                "database": "sqlite" if app_db is not None else "postgresql", "files": files}
    manifest["signature"] = _sign(manifest, secret)
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return target


def verify(backup: Path, *, secret: str) -> Dict[str, Any]:
    """Check signature, sizes, hashes, SQLite integrity and the authority journal chain."""
    problems = []
    manifest = json.loads((backup / "manifest.json").read_text())
    if manifest.get("format") != FORMAT:
        problems.append("unknown backup format")
    if not hmac.compare_digest(manifest.get("signature", ""), _sign(manifest, secret)):
        problems.append("manifest signature does not match (tampered, or a different PERMIT_SECRET)")
    for name, meta in manifest.get("files", {}).items():
        p = backup / name
        if not p.exists():
            problems.append(f"{name}: missing")
            continue
        if p.stat().st_size != meta["bytes"] or _sha256(p) != meta["sha256"]:
            problems.append(f"{name}: contents changed since the backup was made")
            continue
        if name.endswith(".db"):
            conn = sqlite3.connect(str(p))
            try:
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    problems.append(f"{name}: SQLite integrity check failed")
            finally:
                conn.close()
    extra = {p.name for p in backup.iterdir()} - set(manifest.get("files", {})) - {"manifest.json"}
    if extra:
        problems.append(f"unexpected files: {sorted(extra)}")
    journal_ok = None
    if not problems and (backup / "authority.db").exists():
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from app.autonomy.core import CheckpointStore
        journal_ok = CheckpointStore(str(backup / "authority.db")).verify_chain()
        if not journal_ok:
            problems.append("authority.db: action journal hash chain is broken")
    return {"ok": not problems, "problems": problems, "files": list(manifest.get("files", {})),
            "journal_intact": journal_ok, "created_utc": manifest.get("created_utc")}


def restore(backup: Path, *, database_url: str, authority_db: Path, secret: str, backend_stopped: bool) -> Dict[str, Any]:
    if not backend_stopped:
        raise SystemExit("Stop the backend first, then pass --backend-stopped")
    check = verify(backup, secret=secret)
    if not check["ok"]:
        raise SystemExit("Refusing to restore an invalid backup: " + "; ".join(check["problems"]))
    t0 = time.monotonic()
    restored = []
    app_db = _sqlite_path(database_url)
    if app_db is not None and (backup / "app.db").exists():
        app_db.parent.mkdir(parents=True, exist_ok=True)
        if app_db.exists():
            shutil.copy2(app_db, app_db.with_suffix(".db.before-restore"))
        _sqlite_copy(backup / "app.db", app_db)
        restored.append(str(app_db))
    elif app_db is None and (backup / "app.sql").exists():
        subprocess.run(["psql", "--single-transaction", "-v", "ON_ERROR_STOP=1", database_url,
                        "-f", str(backup / "app.sql")], check=True)
        restored.append("postgresql")
    if (backup / "authority.db").exists():
        authority_db.parent.mkdir(parents=True, exist_ok=True)
        if authority_db.exists():
            shutil.copy2(authority_db, authority_db.with_suffix(".db.before-restore"))
        _sqlite_copy(backup / "authority.db", authority_db)
        restored.append(str(authority_db))
    return {"restored": restored, "seconds": round(time.monotonic() - t0, 3), "verified": check}


def main(argv=None) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from app.config import settings
    ap = argparse.ArgumentParser(prog="python -m app.ops.backup")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create"); c.add_argument("--out", default="backups")
    v = sub.add_parser("verify"); v.add_argument("path")
    r = sub.add_parser("restore"); r.add_argument("path"); r.add_argument("--backend-stopped", action="store_true")
    a = ap.parse_args(argv)
    common = dict(database_url=settings.database_url, authority_db=Path(settings.authority_db_path))
    if a.cmd == "create":
        print(create(Path(a.out), secret=settings.permit_secret, **common))
    elif a.cmd == "verify":
        res = verify(Path(a.path), secret=settings.permit_secret)
        print(json.dumps(res, indent=2))
        return 0 if res["ok"] else 1
    else:
        print(json.dumps(restore(Path(a.path), secret=settings.permit_secret, backend_stopped=a.backend_stopped,
                                 **common), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
