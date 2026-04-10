# tests/conftest.py
import sys, os
# Add services/api/ and the project root to sys.path
_HERE = os.path.dirname(__file__)
_API  = os.path.dirname(_HERE)                          # services/api/
_ROOT = os.path.dirname(os.path.dirname(_API))          # repo root (for platform_shared/)
for p in (_API, _ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)
