"""Integration tests for POST /api/v1/cases and GET /api/v1/cases."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from starlette.middleware.base import BaseHTTPMiddleware

from cases.router import router as cases_router
from cases.schemas import CaseRecord, CaseResponse
from cases.service import CasesService
from dependencies.rbac import require_session_read, require_session_override
from dependencies.db import get_session_repo, get_event_repo, get_case_repo


class TraceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request.state.trace_id = "test-trace"
        return await call_next(request)


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(cases_router)
    app.add_middleware(TraceMiddleware)
    return app


def _make_case(session_id: str = "sess-1") -> CaseRecord:
    return CaseRecord(
        case_id=str(uuid4()),
        session_id=session_id,
        reason="Suspicious activity",
        summary="Session sess-1 (agent: TestAgent) escalated. Risk tier: high (score 0.80). Policy decision: escalate. Events observed: 4.",
        risk_score=0.80,
        decision="escalate",
        created_at=datetime.now(timezone.utc),
    )


# ── POST /api/v1/cases ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_cases_201():
    """Happy path: valid session_id → 201 with case_id and session_id."""
    app = _make_app()
    case = _make_case("sess-1")

    mock_identity = MagicMock()
    mock_identity.user_id = "analyst-1"

    mock_svc = MagicMock(spec=CasesService)
    mock_svc.create_case = AsyncMock(return_value=case)
    app.state.cases_service = mock_svc
    # results_service needed by router to pass to create_case
    app.state.results_service = MagicMock()

    app.dependency_overrides[require_session_override] = lambda: mock_identity
    app.dependency_overrides[get_session_repo] = lambda: AsyncMock()
    app.dependency_overrides[get_event_repo] = lambda: AsyncMock()
    app.dependency_overrides[get_case_repo] = lambda: AsyncMock()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/cases",
                json={"session_id": "sess-1", "reason": "Suspicious activity"},
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["case_id"] == case.case_id
        assert data["session_id"] == "sess-1"
        assert data["status"] == "open"
        assert "reason" in data
        assert "summary" in data
        assert "risk_score" in data
        assert "decision" in data
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_post_cases_404_session_not_found():
    """Session not found → 404 with SESSION_NOT_FOUND code."""
    app = _make_app()

    mock_identity = MagicMock()
    mock_identity.user_id = "analyst-1"

    mock_svc = MagicMock(spec=CasesService)
    mock_svc.create_case = AsyncMock(return_value=None)  # service returns None = not found
    app.state.cases_service = mock_svc
    app.state.results_service = MagicMock()

    app.dependency_overrides[require_session_override] = lambda: mock_identity
    app.dependency_overrides[get_session_repo] = lambda: AsyncMock()
    app.dependency_overrides[get_event_repo] = lambda: AsyncMock()
    app.dependency_overrides[get_case_repo] = lambda: AsyncMock()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/cases",
                json={"session_id": "nonexistent", "reason": "test"},
            )

        assert resp.status_code == 404
        detail = resp.json()["detail"]
        assert detail["code"] == "SESSION_NOT_FOUND"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_post_cases_422_missing_fields():
    """Missing required fields → 422 validation error."""
    app = _make_app()

    mock_identity = MagicMock()
    app.dependency_overrides[require_session_override] = lambda: mock_identity
    app.dependency_overrides[get_session_repo] = lambda: AsyncMock()
    app.dependency_overrides[get_event_repo] = lambda: AsyncMock()
    app.dependency_overrides[get_case_repo] = lambda: AsyncMock()
    app.state.cases_service = MagicMock()
    app.state.results_service = MagicMock()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/cases", json={"session_id": "only-one-field"})

        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


# ── GET /api/v1/cases ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_cases_200_empty():
    """Empty service → 200 with cases=[] and total=0."""
    app = _make_app()

    mock_identity = MagicMock()
    mock_svc = MagicMock(spec=CasesService)
    mock_svc.list_cases = AsyncMock(return_value=[])
    app.state.cases_service = mock_svc

    app.dependency_overrides[require_session_read] = lambda: mock_identity
    app.dependency_overrides[get_case_repo] = lambda: AsyncMock()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/cases")

        assert resp.status_code == 200
        data = resp.json()
        assert data["cases"] == []
        assert data["total"] == 0
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_cases_200_with_cases():
    """Service has cases → 200 with correct total."""
    app = _make_app()

    mock_identity = MagicMock()
    case1 = _make_case("s1")
    case2 = _make_case("s2")
    mock_svc = MagicMock(spec=CasesService)
    mock_svc.list_cases = AsyncMock(return_value=[case1, case2])
    app.state.cases_service = mock_svc

    app.dependency_overrides[require_session_read] = lambda: mock_identity
    app.dependency_overrides[get_case_repo] = lambda: AsyncMock()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/cases")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["cases"]) == 2
        assert data["cases"][0]["session_id"] in ("s1", "s2")
    finally:
        app.dependency_overrides.clear()
