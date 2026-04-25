"""Tests for spm-mcp's bearer-auth surface (Task 8)."""
from __future__ import annotations

from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from services.spm_mcp.auth import verify_mcp_token
from services.spm_mcp.main import app


# ─── verify_mcp_token unit tests ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_verify_known_token_returns_agent(monkeypatch):
    async def _ok(token: str):
        return {"id": "ag-001", "tenant_id": "t1", "name": "cs-bot"}
    monkeypatch.setattr(
        "services.spm_mcp.auth.resolve_agent_by_mcp_token", _ok)

    out = await verify_mcp_token("Bearer good-token")
    assert out["id"]        == "ag-001"
    assert out["tenant_id"] == "t1"


@pytest.mark.asyncio
async def test_verify_strips_bearer_prefix(monkeypatch):
    captured = {}
    async def _ok(token: str):
        captured["token"] = token
        return {"id": "ag-1", "tenant_id": "t1", "name": "x"}
    monkeypatch.setattr(
        "services.spm_mcp.auth.resolve_agent_by_mcp_token", _ok)

    await verify_mcp_token("Bearer abc-123")
    assert captured["token"] == "abc-123"


@pytest.mark.asyncio
async def test_verify_accepts_bare_token(monkeypatch):
    """Without the 'Bearer ' prefix the token must still validate so SDKs
    that strip the prefix don't accidentally fall through to a 401."""
    async def _ok(token: str):
        return {"id": "ag-1", "tenant_id": "t1", "name": "x"}
    monkeypatch.setattr(
        "services.spm_mcp.auth.resolve_agent_by_mcp_token", _ok)

    out = await verify_mcp_token("plain-token")
    assert out["id"] == "ag-1"


@pytest.mark.asyncio
async def test_verify_rejects_unknown(monkeypatch):
    async def _none(token: str):
        return None
    monkeypatch.setattr(
        "services.spm_mcp.auth.resolve_agent_by_mcp_token", _none)

    with pytest.raises(PermissionError, match="Unknown"):
        await verify_mcp_token("Bearer nope")


@pytest.mark.asyncio
async def test_verify_rejects_empty():
    with pytest.raises(PermissionError, match="Missing"):
        await verify_mcp_token("")
    with pytest.raises(PermissionError, match="Missing"):
        await verify_mcp_token("Bearer ")


# ─── HTTP surface — /health is unauthenticated ─────────────────────────────

class TestHealthRoute:
    def test_health_no_auth_required(self):
        c = TestClient(app)
        r = c.get("/health")
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    def test_app_metadata(self):
        assert app.title == "spm-mcp"
        assert app.version == "0.1.0"
