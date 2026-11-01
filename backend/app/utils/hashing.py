from __future__ import annotations

import hashlib
import json
from typing import Any


def sha256_canonical(obj: Any) -> str:
    """Hash over canonical JSON (stable key ordering, no whitespace)."""
    data = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()
