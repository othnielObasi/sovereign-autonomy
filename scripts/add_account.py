"""Create a sign-in account entry for AUTH_ACCOUNTS.

    python scripts/add_account.py alice admin
    (prompts for the password; prints the entry to append, separated by ";")

Roles: viewer, operator, admin. The password is hashed (PBKDF2-SHA256); only the
hash goes into the environment.
"""
from __future__ import annotations

import getpass
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.auth.roles import ROLE_RANK, hash_password  # noqa: E402

if len(sys.argv) != 3 or sys.argv[2] not in ROLE_RANK or ":" in sys.argv[1] or ";" in sys.argv[1]:
    sys.exit("usage: add_account.py <name> <viewer|operator|admin>")
pw = getpass.getpass("Password: ")
if len(pw) < 12 or pw != getpass.getpass("Again: "):
    sys.exit("Passwords must match and be at least 12 characters.")
print(f"{sys.argv[1]}:{sys.argv[2]}:{hash_password(pw)}")
