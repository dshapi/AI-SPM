"""Tests for platform_shared.agent_tokens — bearer-token → agent lookups.

These tests do NOT touch a real DB. The helper opens an async session
through ``spm.db.session.get_session_factory`` so we monkeypatch that to
return a mock async-sessionmaker that hands back a configured agent row
(or None) on demand.
"""
from __future__ import annotations

from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from platform_shared.agent_tokens import (
    resolve_agent_by_llm_token,
    resolve_agent_by_mcp_token,
)


# ─── Helpers to build a mock async session that yields a row ────────────────

def _make_session_factory_returning(row: Optional[Any]):
    """Return a callable that mimics get_session_factory().

    The returned object, when called, produces an async-context-manager
    session whose ``execute()`` yields a result with ``scalar_one_or_none()
    == row``.
    """
    result = MagicMock()
    result.scalar_one_or_none.return_value = row

    session = MagicMock()
    session.execute   = AsyncMock(return_value=result)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__  = AsyncMock(return_value=None)

    factory = MagicMock(return_value=session)
    return lambda: factory


def _fake_agent_row(*, id="ag-1", tenant_id="t1", name="my-agent"):
    """Lightweight stand-in for a SQLAlchemy Agent row."""
    row = MagicMock()
    row.id        = id
    row.tenant_id = tenant_id
    row.name      = name
    return row


# ─── mcp_token lookup ──────────────────────────────────────────────────────

class TestResolveAgentByMcpToken:
    @pytest.mark.asyncio
    async def test_known_token_returns_id_tenant_name(self, monkeypatch):
        row = _fake_agent_row(id="ag-001", tenant_id="t1", name="cs-bot")
        import spm.db.session as sess
        monkeypatch.setattr(sess, "get_session_factory",
                             _make_session_factory_returning(row))

        out = await resolve_agent_by_mcp_token("mcp-good")
        assert out == {"id": "ag-001", "tenant_id": "t1", "name": "cs-bot"}

    @pytest.mark.asyncio
    async def test_unknown_token_returns_none(self, monkeypatch):
        import spm.db.session as sess
        monkeypatch.setattr(sess, "get_session_factory",
                             _make_session_factory_returning(None))
        assert await resolve_agent_by_mcp_token("nope") is None

    @pytest.mark.asyncio
    async def test_empty_token_returns_none_without_db(self):
        # Empty token must short-circuit before touching the DB so the
        # auth middleware fast-path stays cheap.
        assert await resolve_agent_by_mcp_token("") is None
        assert await resolve_agent_by_mcp_token(None) is None  # type: ignore[arg-type]


# ─── llm_api_key lookup ────────────────────────────────────────────────────

class TestResolveAgentByLlmToken:
    @pytest.mark.asyncio
    async def test_known_token_returns_id_tenant_name(self, monkeypatch):
        row = _fake_agent_row(id="ag-002", tenant_id="t1", name="codereview")
        import spm.db.session as sess
        monkeypatch.setattr(sess, "get_session_factory",
                             _make_session_factory_returning(row))

        out = await resolve_agent_by_llm_token("llm-good")
        assert out == {"id": "ag-002", "tenant_id": "t1", "name": "codereview"}

    @pytest.mark.asyncio
    async def test_unknown_token_returns_none(self, monkeypatch):
        import spm.db.session as sess
        monkeypatch.setattr(sess, "get_session_factory",
                             _make_session_factory_returning(None))
        assert await resolve_agent_by_llm_token("nope") is None


# ─── Failure semantics — DB raises ─────────────────────────────────────────

class TestSwallowsDbErrors:
    @pytest.mark.asyncio
    async def test_db_exception_returns_none(self, monkeypatch):
        """If the DB lookup raises, the helpers MUST return None instead
        of propagating — auth middleware needs a clean 401, not a 500."""
        session = MagicMock()
        session.execute    = AsyncMock(side_effect=RuntimeError("db down"))
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__  = AsyncMock(return_value=None)
        factory_obj = MagicMock(return_value=session)

        import spm.db.session as sess
        monkeypatch.setattr(sess, "get_session_factory", lambda: factory_obj)

        assert await resolve_agent_by_mcp_token("any") is None
        assert await resolve_agent_by_llm_token("any") is None
