"""Smoke tests for spm-llm-proxy's FastAPI app — Task 6 surface (GET /health).

The OpenAI-compatible chat-completions surface is covered separately in
``tests/test_spm_llm_proxy_chat.py`` once Task 7 lands.
"""
from __future__ import annotations

import sys
from pathlib import Path

# The service has no top-level package import; add it to sys.path so the
# `app` module can be imported directly. Mirrors the pattern in
# tests/conftest.py for sibling services.
_PROXY_DIR = Path(__file__).parent.parent / "services" / "spm_llm_proxy"
if str(_PROXY_DIR) not in sys.path:
    sys.path.insert(0, str(_PROXY_DIR.parent.parent))  # repo root

from fastapi.testclient import TestClient  # noqa: E402

from services.spm_llm_proxy.main import app  # noqa: E402


def test_health_returns_ok():
    c = TestClient(app)
    r = c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_app_has_openapi_metadata():
    """Docs surface — should not regress to defaults."""
    assert app.title == "spm-llm-proxy"
    assert app.version == "0.1.0"


def test_unknown_route_returns_404():
    c = TestClient(app)
    assert c.get("/v1/no-such-endpoint").status_code == 404
