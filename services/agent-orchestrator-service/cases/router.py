"""
cases/router.py
───────────────
FastAPI router for the Cases API.

  POST /api/v1/cases     — escalate a session into a tracked case
  GET  /api/v1/cases     — list all cases

RBAC:
  POST requires session.override (security analyst / admin)
  GET  requires session.read     (all authenticated roles)

The router reads the shared CasesService and ResultsService from app.state,
and receives per-request repositories as FastAPI dependencies.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from cases.schemas import CaseListResponse, CaseResponse, CreateCaseRequest, CreateHuntCaseRequest
from cases.service import CasesService
from dependencies.db import get_case_repo, get_event_repo, get_session_repo
from dependencies.auth import IdentityContext
from dependencies.rbac import require_session_override, require_session_read, require_agent_invoke
from models.cases import CaseRepository
from models.event import EventRepository
from models.session import SessionRepository
from results.service import ResultsService
from schemas.session import ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/cases", tags=["Cases"])


def _get_cases_service(request: Request) -> CasesService:
    return request.app.state.cases_service


def _get_results_service(request: Request) -> ResultsService:
    return request.app.state.results_service


@router.post(
    "",
    response_model=CaseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Escalate a session into a case",
    description=(
        "**Required permission:** `session.override`\n\n"
        "Fetches the session, its events, and computed results, then stores "
        "a new case record. Returns the created case."
    ),
    responses={
        201: {"description": "Case created"},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse, "description": "PERMISSION_DENIED: requires session.override"},
        404: {"model": ErrorResponse, "description": "Session not found"},
        422: {"description": "Validation error — missing or invalid fields"},
    },
)
async def create_case(
    body: CreateCaseRequest,
    request: Request,
    response: Response,
    identity: IdentityContext = Depends(require_session_override),
    session_repo: SessionRepository = Depends(get_session_repo),
    event_repo: EventRepository = Depends(get_event_repo),
    case_repo: CaseRepository = Depends(get_case_repo),
) -> CaseResponse:
    trace_id = request.state.trace_id
    response.headers["X-Trace-ID"] = trace_id

    logger.info(
        "POST /cases session_id=%s user=%s trace=%s",
        body.session_id, identity.user_id, trace_id,
    )

    cases_svc = _get_cases_service(request)
    results_svc = _get_results_service(request)

    case = await cases_svc.create_case(
        session_id=body.session_id,
        reason=body.reason,
        session_repo=session_repo,
        event_repo=event_repo,
        results_svc=results_svc,
        case_repo=case_repo,
    )

    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorDetail(
                code="SESSION_NOT_FOUND",
                message=f"Session '{body.session_id}' does not exist.",
                trace_id=trace_id,
            ).model_dump(),
        )

    return CaseResponse.from_record(case)


@router.post(
    "/hunt",
    response_model=CaseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a case directly from the threat-hunting agent",
    description=(
        "**Required permission:** `agent.invoke`\n\n"
        "Creates a case with a custom title and description — no real session required. "
        "Intended for the threat-hunting-agent which has no chat session to escalate."
    ),
    responses={
        201: {"description": "Hunt case created"},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    },
)
async def create_hunt_case(
    body: CreateHuntCaseRequest,
    request: Request,
    response: Response,
    identity: IdentityContext = Depends(require_agent_invoke),
    case_repo: CaseRepository = Depends(get_case_repo),
) -> CaseResponse:
    from cases.schemas import CaseRecord
    from uuid import uuid4

    trace_id = request.state.trace_id
    response.headers["X-Trace-ID"] = trace_id

    _SEVERITY_RISK = {"low": (0.25, "allow"), "medium": (0.55, "escalate"),
                      "high": (0.80, "escalate"), "critical": (0.95, "block")}
    risk_score, decision = _SEVERITY_RISK.get(body.severity.lower(), (0.5, "escalate"))
    ttps_str = ", ".join(body.ttps) if body.ttps else "none"
    summary = f"[{body.severity.upper()}] {body.title}"
    if body.description:
        summary += f" — {body.description}"

    case = CaseRecord(
        case_id=str(uuid4()),
        session_id=f"hunt:{uuid4()}",
        reason=body.reason or f"threat-hunt · TTPs: {ttps_str}",
        summary=summary,
        risk_score=risk_score,
        decision=decision,
    )
    await case_repo.insert(case)
    logger.info(
        "POST /cases/hunt case_id=%s severity=%s user=%s trace=%s",
        case.case_id, body.severity, identity.user_id, trace_id,
    )
    return CaseResponse.from_record(case)


@router.get(
    "",
    response_model=CaseListResponse,
    summary="List all cases",
    description=(
        "**Required permission:** `session.read`\n\n"
        "Returns all cases sorted newest-first."
    ),
    responses={
        200: {"description": "CaseListResponse"},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse, "description": "PERMISSION_DENIED: requires session.read"},
    },
)
async def list_cases(
    request: Request,
    response: Response,
    identity: IdentityContext = Depends(require_session_read),
    case_repo: CaseRepository = Depends(get_case_repo),
) -> CaseListResponse:
    trace_id = request.state.trace_id
    response.headers["X-Trace-ID"] = trace_id

    logger.info("GET /cases user=%s trace=%s", identity.user_id, trace_id)

    cases_svc = _get_cases_service(request)
    records = await cases_svc.list_cases(case_repo)
    cases = [CaseResponse.from_record(r) for r in records]
    return CaseListResponse(cases=cases, total=len(cases))
