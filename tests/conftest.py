"""
conftest.py — lives in tests/, applies to all tests under tests/.

Ensures unit tests can import service modules that use sibling-style imports
(e.g. ``services/api/app.py`` does ``from security import ...`` because at
runtime uvicorn is launched from inside ``services/api/``).

Without this, pytest from project root fails with ``ModuleNotFoundError: No
module named 'security'`` when it tries to import ``services.api.app``.

Path ordering matters: the project root must come FIRST so that
``services.api.app`` (a namespace package under the repo) wins over any
``services/`` subdirectory that lives inside a vendored service. For
example, ``services/agent-orchestrator-service/services/`` would shadow the
real top-level ``services/`` package if placed ahead of the project root.
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # project root

# 1) Project root FIRST so ``import services.api.app`` resolves to the
#    top-level services/ package, not to one vendored inside a service.
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# 2) Sibling roots AFTER the project root, so ``from security import ...``
#    inside services/api/app.py finds services/api/security/ — but
#    ``import services.api.app`` still resolves to the correct module.
_SIBLING_ROOTS = [
    os.path.join(_HERE, "services", "api"),
    os.path.join(_HERE, "services", "policy_decider"),
    os.path.join(_HERE, "services", "guard_model"),
    # spm_api's Dockerfile flattens ``integrations_routes.py`` and
    # ``integrations_seed_data.py`` onto /app/ next to app.py, so at runtime
    # they are importable by bare name (e.g. ``from integrations_routes import
    # router``).  Mirror that here so tests can import the same modules the
    # way the running container does.
    os.path.join(_HERE, "services", "spm_api"),
]

for _root in _SIBLING_ROOTS:
    if os.path.isdir(_root) and _root not in sys.path:
        # append — NOT insert — so the repo root's view of ``services``
        # cannot be shadowed by a vendored ``services/`` inside one of
        # these roots.
        sys.path.append(_root)
