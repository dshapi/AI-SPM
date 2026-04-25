"""Tests for GET /integrations ?vendor= filter and the options_provider helper.

The ?category= filter has been there since the integrations module shipped;
this file covers the additions that the agent-runtime ConnectorType depends
on (Phase 1, Task 4):

  - new query param ``?vendor=`` on GET /integrations
  - new ``enum_integration`` value in the FieldType Literal
  - new ``options_provider`` optional key on FieldSpec TypedDict
  - new ``options_provider_filters()`` helper that maps a string name to
    the (category, vendor) pair the frontend should pass to the route
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient

import integrations_routes as ir  # noqa: E402  — sys.path set in conftest
from integrations_routes import router, verify_jwt  # noqa: E402


# ─── 1. options_provider_filters helper ────────────────────────────────────

def test_options_provider_filters_known_names():
    from connector_registry import options_provider_filters

    cat, vend = options_provider_filters("ai_provider_integrations")
    assert cat  == "AI Providers"
    assert vend is None

    cat, vend = options_provider_filters("tavily_integrations")
    assert cat  == "AI Providers"
    assert vend == "Tavily"


def test_options_provider_filters_unknown_returns_nones():
    from connector_registry import options_provider_filters

    assert options_provider_filters("does-not-exist") == (None, None)


# ─── 2. FieldType / FieldSpec extensions ───────────────────────────────────

def test_field_type_includes_enum_integration():
    """`enum_integration` must be in the FieldType Literal so that
    ConnectorType definitions can declare fields that reference other
    integrations (e.g. agent-runtime → default LLM picker)."""
    from typing import get_args
    from connector_registry import FieldType

    assert "enum_integration" in get_args(FieldType)
    # Sanity: the existing types are still there.
    assert "string"   in get_args(FieldType)
    assert "password" in get_args(FieldType)


def test_field_spec_accepts_options_provider():
    """FieldSpec is a TypedDict (total=False), so all we can verify
    statically is the annotation surface — `options_provider` must be
    declared so type-checkers don't reject it."""
    from connector_registry import FieldSpec

    assert "options_provider" in FieldSpec.__annotations__


# ─── 3. GET /integrations ?vendor=… filter ─────────────────────────────────

@pytest.fixture
def vendor_capturing_db():
    """Mock async session that records the vendor predicate on the executed
    SELECT, so tests can assert the route appended the right WHERE clause.

    Capturing strategy: the route calls `db.execute(stmt)`. We capture the
    stmt and let the tests inspect its compiled string. Compilation uses
    SQLAlchemy's default dialect (no Postgres-specific binding)."""
    captured: Dict[str, Any] = {"stmt": None}

    session = MagicMock()
    result  = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = []
    result.scalars.return_value = scalars

    async def _exec(stmt):
        captured["stmt"] = stmt
        return result

    session.execute = AsyncMock(side_effect=_exec)
    session.commit  = AsyncMock()
    session.close   = AsyncMock()
    session.__captured__ = captured
    return session


@pytest.fixture
def client_with_vendor_db(vendor_capturing_db):
    from spm.db.session import get_db

    app = FastAPI()
    app.include_router(router)

    async def _override_get_db():
        yield vendor_capturing_db

    def _override_verify_jwt(authorization: Optional[str] = Header(None)):
        if not authorization:
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="Missing bearer token")
        return {"sub": "u1", "roles": ["spm:admin"]}

    app.dependency_overrides[get_db]      = _override_get_db
    app.dependency_overrides[verify_jwt]  = _override_verify_jwt

    return TestClient(app), vendor_capturing_db


def _stmt_sql(stmt) -> str:
    """Compile a SQLAlchemy statement to a literal string for assertion."""
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


class TestVendorFilter:
    def test_vendor_query_param_accepted(self, client_with_vendor_db):
        client, _ = client_with_vendor_db
        resp = client.get(
            "/integrations?vendor=Tavily",
            headers={"Authorization": "Bearer x"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == []

    def test_vendor_filter_appears_in_query(self, client_with_vendor_db):
        client, db = client_with_vendor_db
        resp = client.get(
            "/integrations?vendor=Tavily",
            headers={"Authorization": "Bearer x"},
        )
        assert resp.status_code == 200, resp.text
        sql = _stmt_sql(db.__captured__["stmt"]).lower()
        # Verifies the route appended a vendor=… predicate to the SELECT.
        assert "vendor" in sql
        assert "tavily" in sql

    def test_no_vendor_means_no_vendor_predicate(self, client_with_vendor_db):
        client, db = client_with_vendor_db
        resp = client.get(
            "/integrations",
            headers={"Authorization": "Bearer x"},
        )
        assert resp.status_code == 200, resp.text
        sql = _stmt_sql(db.__captured__["stmt"]).lower()
        # When the param is absent the route must NOT inject a vendor
        # predicate (else it would over-filter on NULL vendor rows).
        assert "vendor =" not in sql

    def test_category_and_vendor_compose(self, client_with_vendor_db):
        """Both filters can be applied in the same request."""
        client, db = client_with_vendor_db
        resp = client.get(
            "/integrations?category=AI%20Providers&vendor=Tavily",
            headers={"Authorization": "Bearer x"},
        )
        assert resp.status_code == 200, resp.text
        sql = _stmt_sql(db.__captured__["stmt"]).lower()
        assert "ai providers" in sql
        assert "tavily"       in sql
