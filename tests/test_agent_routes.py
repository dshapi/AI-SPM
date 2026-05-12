"""Tests for services.spm_api.agent_routes — Tasks 15 + 16.

Same testing approach as ``test_integrations_routes.py``: mount the
real router on a minimal FastAPI app, override ``get_db`` and
``verify_jwt`` to provide canned claims, and run requests through
``TestClient``.
"""
from __future__ import annotations

import io
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import agent_routes
from agent_routes import router
from platform_shared.rbac import get_current_identity, IdentityContext
from spm.db.session import get_db


def _make_identity(claims):
    """Convert a canned-claims dict into an IdentityContext for DI override."""
    return IdentityContext(
        user_id=claims.get("sub", "u1"),
        tenant_id=claims.get("tenant_id", "t1"),
        email=claims.get("email"),
        roles=claims.get("roles", []),
        raw_claims=claims,
    )


# ─── Shared infrastructure ────────────────────────────────────────────────

ADMIN_CLAIMS    = {"sub": "u1", "roles": ["spm:admin"]}
NON_ADMIN_CLAIMS = {"sub": "u1", "roles": []}


def _make_db_with_rows(rows: List[Any]):
    """Async-session-shaped MagicMock that returns ``rows`` from
    list_agents and stores added rows. db.get() returns the first row
    matching by id (string compare)."""
    saved: List[Any] = list(rows)

    scalars = MagicMock()
    scalars.all.return_value = saved
    result = MagicMock()
    result.scalars.return_value = scalars

    db = MagicMock()
    db.execute  = AsyncMock(return_value=result)
    db.add      = MagicMock(side_effect=saved.append)
    db.commit   = AsyncMock()
    db.refresh  = AsyncMock()
    db.delete   = MagicMock(side_effect=saved.remove)

    def _get(_cls, agent_id):
        for r in saved:
            if str(getattr(r, "id", None)) == str(agent_id):
                return r
        return None
    db.get = _get
    db.__saved__ = saved
    return db


def _make_agent_row(*, id=None, name="x", version="1", agent_type="custom",
                     provider="internal", owner=None, description="",
                     risk="low", policy_status="none",
                     runtime_state="stopped",
                     code_path="/x.py", code_sha256="0"*64,
                     mcp_token="m", llm_api_key="l",
                     tenant_id="t1"):
    """SQLAlchemy-row-shaped MagicMock with attribute-style access."""
    a = MagicMock()
    a.id            = id or uuid.uuid4()
    a.name          = name
    a.version       = version
    a.agent_type    = agent_type
    a.provider      = provider
    a.owner         = owner
    a.description   = description
    a.risk          = risk
    a.policy_status = policy_status
    a.runtime_state = runtime_state
    a.code_path     = code_path
    a.code_sha256   = code_sha256
    a.mcp_token     = mcp_token
    a.llm_api_key   = llm_api_key
    a.tenant_id     = tenant_id
    a.created_at    = None
    a.updated_at    = None
    a.last_seen_at  = None
    return a


@pytest.fixture
def client_factory():
    """Build a TestClient with overrides for get_db and get_current_identity."""
    def _factory(*, claims=ADMIN_CLAIMS, rows: Optional[List[Any]] = None):
        rows = rows or []
        db = _make_db_with_rows(rows)
        identity = _make_identity(claims)

        app = FastAPI()
        app.include_router(router)

        async def _override_db():
            yield db

        def _override_identity():
            return identity

        app.dependency_overrides[get_db]               = _override_db
        app.dependency_overrides[get_current_identity] = _override_identity

        return TestClient(app), db

    return _factory


# ─── POST /agents — create / upload / validate ────────────────────────────

class TestPostAgents:
    def test_upload_valid_returns_201(self, client_factory, monkeypatch):
        async def _no_deploy(db, agent_id):
            pass
        monkeypatch.setattr(agent_routes, "deploy_agent", _no_deploy)

        # Don't actually write to DataVolumes during the test — patch the
        # write_text + mkdir to be no-ops.
        monkeypatch.setattr(
            "pathlib.Path.write_text", lambda self, s, *a, **k: None
        )

        client, db = client_factory(rows=[])
        code = b"import asyncio\nasync def main():\n    pass\nasyncio.run(main())\n"

        r = client.post(
            "/agents",
            headers={"Authorization": "Bearer x"},
            data={
                "name": "my-agent",
                "version": "1.0",
                "agent_type": "langchain",
                "owner": "dany",
                "description": "test",
                "deploy_after": "false",
            },
            files={"code": ("agent.py", io.BytesIO(code), "text/x-python")},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["name"]    == "my-agent"
        assert body["version"] == "1.0"
        assert body["runtime_state"] == "stopped"
        # Tokens MUST never appear in any response.
        assert "mcp_token" not in body
        assert "llm_api_key" not in body
        assert len(db.__saved__) == 1

    def test_bad_syntax_returns_422(self, client_factory):
        client, _ = client_factory()
        r = client.post(
            "/agents",
            headers={"Authorization": "Bearer x"},
            data={"name": "x", "version": "1", "agent_type": "custom"},
            files={"code": ("agent.py", io.BytesIO(b"def main(::"),
                            "text/x-python")},
        )
        assert r.status_code == 422
        assert any("syntax" in d.lower() for d in r.json()["detail"])

    def test_missing_async_main_returns_422(self, client_factory):
        client, _ = client_factory()
        r = client.post(
            "/agents",
            headers={"Authorization": "Bearer x"},
            data={"name": "x", "version": "1", "agent_type": "custom"},
            files={"code": ("agent.py",
                             io.BytesIO(b"def helper():\n    pass\n"),
                             "text/x-python")},
        )
        assert r.status_code == 422
        assert any("main" in d.lower() for d in r.json()["detail"])

    def test_non_admin_is_403(self, client_factory):
        client, _ = client_factory(claims=NON_ADMIN_CLAIMS)
        r = client.post(
            "/agents",
            headers={"Authorization": "Bearer x"},
            data={"name": "x", "version": "1", "agent_type": "custom"},
            files={"code": ("agent.py", io.BytesIO(b"async def main(): pass"),
                            "text/x-python")},
        )
        assert r.status_code == 403


# ─── GET /agents — list ────────────────────────────────────────────────────

class TestGetAgents:
    def test_returns_rows_in_tenant(self, client_factory):
        rows = [_make_agent_row(name="a"), _make_agent_row(name="b")]
        client, _ = client_factory(rows=rows)
        r = client.get(
            "/agents",
            headers={"Authorization": "Bearer x"},
        )
        assert r.status_code == 200
        names = {row["name"] for row in r.json()}
        assert names == {"a", "b"}

    def test_response_strips_tokens(self, client_factory):
        rows = [_make_agent_row(mcp_token="SECRET-MCP",
                                  llm_api_key="SECRET-LLM")]
        client, _ = client_factory(rows=rows)
        r = client.get(
            "/agents",
            headers={"Authorization": "Bearer x"},
        )
        body = r.text
        assert "SECRET-MCP" not in body
        assert "SECRET-LLM" not in body


# ─── GET /agents/{id} ──────────────────────────────────────────────────────

class TestGetAgent:
    def test_returns_404_when_unknown(self, client_factory):
        client, _ = client_factory(rows=[])
        r = client.get(
            f"/agents/{uuid.uuid4()}",
            headers={"Authorization": "Bearer x"},
        )
        assert r.status_code == 404

    def test_returns_row_when_known(self, client_factory):
        agent_id = uuid.uuid4()
        rows = [_make_agent_row(id=agent_id, name="found")]
        client, _ = client_factory(rows=rows)
        r = client.get(
            f"/agents/{agent_id}",
            headers={"Authorization": "Bearer x"},
        )
        assert r.status_code == 200
        assert r.json()["name"] == "found"


# ─── PATCH /agents/{id} ────────────────────────────────────────────────────

class TestPatchAgent:
    def test_updates_allowed_field(self, client_factory):
        agent_id = uuid.uuid4()
        row = _make_agent_row(id=agent_id, description="old")
        client, _ = client_factory(rows=[row])
        r = client.patch(
            f"/agents/{agent_id}",
            headers={"Authorization": "Bearer x"},
            json={"description": "new"},
        )
        assert r.status_code == 200, r.text
        assert row.description == "new"

    def test_rejects_disallowed_field(self, client_factory):
        agent_id = uuid.uuid4()
        row = _make_agent_row(id=agent_id)
        client, _ = client_factory(rows=[row])
        r = client.patch(
            f"/agents/{agent_id}",
            headers={"Authorization": "Bearer x"},
            json={"mcp_token": "stolen-attempt"},
        )
        assert r.status_code == 400
        assert "mcp_token" in r.json()["detail"]


# ─── start / stop / delete ─────────────────────────────────────────────────

class TestLifecycleEndpoints:
    def test_start_returns_202(self, client_factory, monkeypatch):
        async def _no_op(db, aid):
            pass
        monkeypatch.setattr(agent_routes, "start_agent", _no_op)

        agent_id = uuid.uuid4()
        client, _ = client_factory(rows=[_make_agent_row(id=agent_id)])
        r = client.post(
            f"/agents/{agent_id}/start",
            headers={"Authorization": "Bearer x"},
        )
        assert r.status_code == 202

    def test_stop_returns_202(self, client_factory, monkeypatch):
        async def _no_op(db, aid):
            pass
        monkeypatch.setattr(agent_routes, "stop_agent", _no_op)

        agent_id = uuid.uuid4()
        client, _ = client_factory(rows=[_make_agent_row(id=agent_id)])
        r = client.post(
            f"/agents/{agent_id}/stop",
            headers={"Authorization": "Bearer x"},
        )
        assert r.status_code == 202

    def test_delete_returns_204(self, client_factory, monkeypatch):
        async def _no_op(db, aid):
            pass
        monkeypatch.setattr(agent_routes, "retire_agent", _no_op)

        agent_id = uuid.uuid4()
        client, _ = client_factory(rows=[_make_agent_row(id=agent_id)])
        r = client.delete(
            f"/agents/{agent_id}",
            headers={"Authorization": "Bearer x"},
        )
        assert r.status_code == 204
        assert r.text == ""

    def test_lifecycle_endpoints_require_admin(self, client_factory):
        client, _ = client_factory(claims=NON_ADMIN_CLAIMS)
        for verb, path in [
            ("post",   "/agents/whatever/start"),
            ("post",   "/agents/whatever/stop"),
            ("delete", "/agents/whatever"),
        ]:
            r = getattr(client, verb)(
                path, headers={"Authorization": "Bearer x"},
            )
            assert r.status_code == 403, f"{verb.upper()} {path} -> {r.status_code}"
