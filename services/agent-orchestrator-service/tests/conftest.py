"""
Make platform_shared importable in all tests.
platform_shared lives at: ../../.. relative to this service root.
This file is auto-loaded by pytest before any test is collected.
"""
import sys
import os

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# ── Per-test-suite env defaults ────────────────────────────────────────────────
# main.py captures DB_PATH and POLICY_DB_URL at MODULE-IMPORT TIME (lines 105 +
# 232 in main.py).  Once any test imports `from main import ...` (and a lot of
# them do, transitively), those module globals are frozen — even later test
# files that try to ``os.environ.setdefault("DB_PATH", ":memory:")`` at their
# own top level have no effect, because their setdefault runs AFTER the cached
# import.  Setting these here in conftest.py guarantees they're in place before
# pytest collects (and therefore imports) anything.
#
# Without this, test_startup_wiring.py errors with
#   sqlite3.OperationalError: unable to open database file
# at the policy-store init step, because main.py's _DEFAULT_DB_PATH points at
# DataVolumes/agent-orchestrator/agent_orchestrator.db — a directory that
# doesn't exist on a fresh CI runner / dev clone.
os.environ.setdefault("DB_PATH",        ":memory:")
os.environ.setdefault("POLICY_DB_URL",  "sqlite:///:memory:")
