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
