"""
results/router.py
─────────────────
FastAPI router: GET /api/v1/sessions/{session_id}/results

Registered in main.py alongside the existing sessions router.

RBAC:    requires session.read (same permission as GET /api/v1/sessions/{id})
Caching: ResultsService is read from app.state (shared across requests)
404:     returned when no events exist for the session_id
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from dependencies.auth import IdentityContext
from dependencies.db import get_event_repo
from dependencies.rbac import require_session_read
from models.event import EventRepository
from results.schemas import SessionResults
from results.service import ResultsService
from schemas.session import ErrorDetail, ErrorResponse  # ErrorResponse used in responses={} dict

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/sessions", tags=["Results"])


def _get_results_service(request: Request) -> ResultsService:
    """Return the shared ResultsService from app.state."""
    return request.app.state.results_service


@router.get(
    "/{session_id}/results",
    response_model=SessionResults,
    summary="Structured session results",
    description=(
        "**Required permission:** `session.read`\n\n"
        "Returns a structured `SessionResults` object derived from lifecycle "
        "events. Returns `meta.partial=true` while the session pipeline is "
        "still running. Results are cached per session by event count."
    ),
    responses={
        200: {"description": "SessionResults — may be partial if session is active"},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse, "description": "PERMISSION_DENIED: requires session.read"},
        404: {"model": ErrorResponse, "description": "Session not found or has no events"},
    },
)
async def get_session_results(
    session_id: UUID,
    request: Request,
    response: Response,
    identity: IdentityContext = Depends(require_session_read),
    event_repo: EventRepository = Depends(get_event_repo),
) -> SessionResults:
    trace_id = request.state.trace_id
    response.headers["X-Trace-ID"] = trace_id

    logger.info(
        "GET /sessions/%s/results user=%s trace=%s",
        session_id, identity.user_id, trace_id,
    )

    # Check events exist before transforming
    records = await event_repo.get_by_session_id(str(session_id))
    if not records:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorDetail(
                code="SESSION_NOT_FOUND",
                message=f"Session {session_id} has no events or does not exist.",
                trace_id=trace_id,
            ).model_dump(),
        )

    # Get the results service directly instead of via Depends()
    results_svc = _get_results_service(request)
    return await results_svc.get_results(str(session_id), event_repo)
