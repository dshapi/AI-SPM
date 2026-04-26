# tests/e2e/conftest.py
import os
import pytest


def pytest_configure(config):
    if not os.environ.get("AISPM_BASE_URL"):
        pytest.skip("AISPM_BASE_URL not set — skipping E2E tests", allow_module_level=True)
