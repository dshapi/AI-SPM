"""Conftest for the aispm SDK test suite.

Adds ``agent_runtime/`` to sys.path so ``import aispm`` resolves to
the package living under it. The repo root's ``tests/conftest.py``
takes care of the broader path setup; this just adds the one extra
directory.
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))  # repo root
_AGENT_RUNTIME = os.path.join(_HERE, "agent_runtime")

if _AGENT_RUNTIME not in sys.path:
    sys.path.insert(0, _AGENT_RUNTIME)
