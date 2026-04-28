"""
Add services/spm_api and the repo root (for the `spm` package) to sys.path
before any test is collected.
"""
import sys
import os

_SERVICE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_REPO_ROOT = os.path.abspath(os.path.join(_SERVICE, "../.."))

for _p in [_SERVICE, _REPO_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)
