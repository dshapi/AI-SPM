"""Integration tests for GET /api/v1/sessions/{session_id}/results."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from results.router import router as results_router
from results.schemas import SessionResults, SessionResultsMeta
from dependencies.rbac import require_session_read
from dependencies.db import get_event_repo
from results.router import _get_results_service


def _make_app() -> FastAPI:
    app = FastAPI()
    # Use the pre-registered router from the module
    app.include_router(results_router)
    return app


def _make_results(partial: bool = False) -> SessionResults:
    return SessionResults(
        meta=SessionResultsMeta(session_id="sess-1", event_count=5, partial=partial),
        status="completed",
        decision="allow",
    )


@pytest.fixture
def app():
    return _make_app()


@pytest.mark.asyncio
async def test_get_results_200(app):
    """Happy path: session exists and has events."""
    mock_results = _make_results()
    mock_identity = MagicMock()
    mock_identity.user_id = "test-user"

    mock_repo = AsyncMock()
    mock_repo.get_by_session_id.return_value = [MagicMock()]  # non-empty

    mock_svc = AsyncMock()
    mock_svc.get_results.return_value = mock_results

    # Set up app.state for the results service
    app.state.results_service = mock_svc

    # Override dependencies using the actual dependency functions as keys
    async def override_auth():
        return mock_identity

    async def override_repo():
        return mock_repo

    app.dependency_overrides[require_session_read] = override_auth
    app.dependency_overrides[get_event_repo] = override_repo

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/sessions/12345678-1234-5678-1234-567812345678/results"
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "allow"
        assert data["status"] == "completed"
        assert "meta" in data
        assert "risk" in data
        assert "policy" in data
        assert "decision_trace" in data
        assert "recommendations" in data
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_results_partial_returns_200(app):
    """Partial (in-flight) session still returns 200 with meta.partial=True."""
    mock_results = _make_results(partial=True)
    mock_identity = MagicMock()
    mock_identity.user_id = "test-user"

    mock_repo = AsyncMock()
    mock_repo.get_by_session_id.return_value = [MagicMock()]

    mock_svc = AsyncMock()
    mock_svc.get_results.return_value = mock_results

    # Set up app.state for the results service
    app.state.results_service = mock_svc

    async def override_auth():
        return mock_identity

    async def override_repo():
        return mock_repo

    app.dependency_overrides[require_session_read] = override_auth
    app.dependency_overrides[get_event_repo] = override_repo

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/sessions/12345678-1234-5678-1234-567812345678/results"
            )

        assert resp.status_code == 200
        assert resp.json()["meta"]["partial"] is True
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_results_404_no_events(app):
    """Session with no events returns 404."""
    mock_identity = MagicMock()
    mock_identity.user_id = "test-user"

    mock_repo = AsyncMock()
    mock_repo.get_by_session_id.return_value = []  # empty

    mock_svc = AsyncMock()

    async def override_auth():
        return mock_identity

    async def override_repo():
        return mock_repo

    def override_svc(request):
        return mock_svc

    app.dependency_overrides[require_session_read] = override_auth
    app.dependency_overrides[get_event_repo] = override_repo
    app.dependency_overrides[_get_results_service] = override_svc

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/sessions/12345678-1234-5678-1234-567812345678/results"
            )

        assert resp.status_code == 404
        data = resp.json()
        assert "detail" in data
    finally:
        app.dependency_overrides.clear()
