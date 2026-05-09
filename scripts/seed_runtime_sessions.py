#!/usr/bin/env python3
"""
seed_runtime_sessions.py — thin re-export shim.

The canonical seeder is ``scripts/seed_all.py``.  Until May 2026 this
file was a 164-line duplicate; we consolidated everything into
``seed_all.py`` and replaced the duplicates with shims.

To run from CLI use:
    python3 scripts/seed_all.py runtime [base_url]

If you're adding a new seeder: add it to ``scripts/seed_all.py``.
NEVER add another standalone ``seed_*.py``.
"""
from __future__ import annotations

import sys

from seed_all import seed_runtime_sessions_via_http  # noqa: F401


if __name__ == "__main__":
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8094"
    seed_runtime_sessions_via_http(base_url=base_url)
