#!/usr/bin/env python3
"""
seed_db.py — thin re-export shim.

The canonical seeder is ``scripts/seed_all.py`` (copied to
``/app/seed_all.py`` in the spm-api image).  Until May 2026 this file
was a 646-line duplicate that drifted from the orchestrator's
``seed_demo.py``.  We consolidated both into a single ``seed_all.py``
and replaced the duplicates with shims like this one.

Kept as a shim (not deleted) so:
  - existing imports ``from seed_db import seed_models, ...`` still work
  - tests under ``services/spm_api/tests/test_seed_db.py`` keep working

If you're adding a new seeder: add it to ``scripts/seed_all.py``.
NEVER add another standalone ``seed_*.py``.
"""
from __future__ import annotations

import asyncio
import sys

from seed_all import (  # noqa: F401  (re-exported for back-compat)
    DEMO_MODELS,
    ensure_schema,
    seed_models,
    seed_posture_snapshots,
    seed_spm_db,
    seed_system_agents,
)


def main() -> int:
    """Compat entry — ``python3 /app/seed_db.py`` keeps working."""
    asyncio.run(seed_spm_db())
    return 0


if __name__ == "__main__":
    sys.exit(main())
