"""
seed_demo.py — thin re-export shim.

The canonical seeder is ``scripts/seed_all.py`` (copied to
``/app/seed_all.py`` in the orchestrator image).  Until May 2026 this
file was a 769-line duplicate that drifted from
``services/spm_api/seed_db.py``.  We consolidated both into a single
``seed_all.py`` and replaced the duplicates with shims like this one.

Kept as a shim (not deleted) so:
  - existing import ``from seed_demo import seed_demo_data`` (in
    services/agent-orchestrator-service/main.py) keeps working
  - tests under ``tests/test_seed_demo.py`` keep working

If you're adding a new seeder: add it to ``scripts/seed_all.py``.
NEVER add another standalone ``seed_*.py``.
"""
from __future__ import annotations

# `seed_demo_data` is a back-compat alias for `seed_orchestrator_db`
# already exported by seed_all.py (see seed_all.py module-tail).
from seed_all import seed_demo_data, seed_orchestrator_db  # noqa: F401
