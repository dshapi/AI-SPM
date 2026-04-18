from __future__ import annotations
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.findings_schemas import (
    FindingDetailResponse,
    FindingListItem,
    FindingListResponse,
    LinkCaseRequest,
    QueryFindingsRequest,
    UpdateStatusRequest,
)
from dependencies.auth import IdentityContext
from dependencies.rbac import require_session_override, require_session_read
from events.publisher import EventPublisher
from schemas.session import ErrorDetail, ErrorResponse
from threat_findings.models import ThreatFindingRepository
from threat_findings.schemas import FindingFilter
from threat_findings.service import ThreatFindingsService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/findings", tags=["Findings"])

_MAX_LIMIT = 200


# ── Dependency functions ──────────────────────────────────────────────────────

def get_findings_service(request: Request) -> ThreatFindingsService:
    return request.app.state.threat_findings_service


def get_publisher(request: Request) -> Optional[EventPublisher]:
    """Return the EventPublisher if available; None otherwise (degrades gracefully)."""
    return getattr(request.app.state, "event_publisher", None)


async def get_async_db(request: Request):
    factory = request.app.state.db_session_factory
    async with factory() as session:
        yield session


async def get_finding_repo(
    session: AsyncSession = Depends(get_async_db),
) -> ThreatFindingRepository:
    return ThreatFindingRepository(session)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_or_404(
    finding_id: str,
    svc: ThreatFindingsService,
    repo: ThreatFindingRepository,
    trace_id: str,
) -> FindingDetailResponse:
    rec = await svc.get_finding_by_id(finding_id, repo)
    if rec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorDetail(
                code="FINDING_NOT_FOUND",
                message=f"Finding '{finding_id}' not found.",
                trace_id=trace_id,
            ).model_dump(),
        )
    return FindingDetailResponse.from_record(rec)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get(
    "",
    summary="List findings with optional filters",
    responses={
        200: {"description": "Paginated list of findings"},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    },
)
async def list_findings(
    request:        Request,
    response:       Response,
    severity:       Optional[str]   = Query(None),
    status_filter:  Optional[str]   = Query(None, alias="status"),
    asset:          Optional[str]   = Query(None),
    tenant_id:      Optional[str]   = Query(None),
    has_case:       Optional[bool]  = Query(None),
    from_time:      Optional[str]   = Query(None),
    to_time:        Optional[str]   = Query(None),
    min_risk_score: Optional[float] = Query(None, ge=0.0, le=1.0),
    sort_by:        Optional[str]   = Query(None, pattern="^(risk_score|timestamp|created_at)$"),
    limit:          int             = Query(50, ge=1, le=_MAX_LIMIT),
    offset:         int             = Query(0, ge=0),
    identity:       IdentityContext         = Depends(require_session_read),
    repo:           ThreatFindingRepository = Depends(get_finding_repo),
    svc:            ThreatFindingsService   = Depends(get_findings_service),
) -> FindingListResponse:
    trace_id = getattr(request.state, "trace_id", "")
    logger.info(
        "GET /findings user=%s severity=%s status=%s tenant=%s trace=%s",
        identity.user_id, severity, status_filter, tenant_id, trace_id,
    )
    filters = FindingFilter(
        severity=severity,
        status=status_filter,
        asset=asset,
        tenant_id=tenant_id,
        has_case=has_case,
        from_ts=from_time,
        to_ts=to_time,
        min_risk_score=min_risk_score,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
    )
    items = await svc.list_findings(filters, repo)
    # count_findings calls _apply_filters (WHERE only, no LIMIT/OFFSET applied),
    # so passing the same filters gives the correct total count across all pages.
    total = await svc.count_findings(filters, repo)
    response.headers["X-Trace-ID"] = trace_id
    return FindingListResponse(
        items=[FindingListItem.from_record(r) for r in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/query",
    summary="Bulk-query findings (body-based filters)",
    responses={
        200: {"description": "Paginated list of findings"},
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    },
)
async def query_findings(
    body:      QueryFindingsRequest,
    request:   Request,
    response:  Response,
    identity:  IdentityContext         = Depends(require_session_read),
    repo:      ThreatFindingRepository = Depends(get_finding_repo),
    svc:       ThreatFindingsService   = Depends(get_findings_service),
) -> FindingListResponse:
    trace_id = getattr(request.state, "trace_id", "")
    logger.info(
        "POST /findings/query user=%s trace=%s body=%s",
        identity.user_id, trace_id, body.model_dump(exclude_none=True),
    )
    filters = FindingFilter(
        severity=body.severity,
        status=body.status,
        asset=body.asset,
        tenant_id=body.tenant_id,
        has_case=body.has_case,
        from_ts=body.from_time,
        to_ts=body.to_time,
        min_risk_score=body.min_risk_score,
        sort_by=body.sort_by,
        limit=body.limit,
        offset=body.offset,
    )
    items = await svc.list_findings(filters, repo)
    # count_findings calls _apply_filters (WHERE only, no LIMIT/OFFSET), so
    # passing `filters` returns the correct total count across all pages.
    total = await svc.count_findings(filters, repo)
    response.headers["X-Trace-ID"] = trace_id
    return FindingListResponse(
        items=[FindingListItem.from_record(r) for r in items],
        total=total,
        limit=body.limit,
        offset=body.offset,
    )


@router.get(
    "/{finding_id}",
    summary="Get full finding detail",
    responses={
        200: {"description": "Full finding object"},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def get_finding(
    finding_id: str,
    request:    Request,
    response:   Response,
    identity:   IdentityContext         = Depends(require_session_read),
    repo:       ThreatFindingRepository = Depends(get_finding_repo),
    svc:        ThreatFindingsService   = Depends(get_findings_service),
) -> FindingDetailResponse:
    trace_id = getattr(request.state, "trace_id", "")
    logger.info(
        "GET /findings/%s user=%s trace=%s", finding_id, identity.user_id, trace_id,
    )
    detail = await _get_or_404(finding_id, svc, repo, trace_id)
    response.headers["X-Trace-ID"] = trace_id
    return detail


@router.patch(
    "/{finding_id}/status",
    summary="Update finding status",
    responses={
        200: {"description": "Updated finding"},
        400: {"model": ErrorResponse, "description": "Invalid status value"},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def update_status(
    finding_id: str,
    body:       UpdateStatusRequest,
    request:    Request,
    response:   Response,
    identity:   IdentityContext             = Depends(require_session_override),
    repo:       ThreatFindingRepository     = Depends(get_finding_repo),
    svc:        ThreatFindingsService       = Depends(get_findings_service),
    publisher:  Optional[EventPublisher]    = Depends(get_publisher),
) -> FindingDetailResponse:
    trace_id = getattr(request.state, "trace_id", "")
    logger.info(
        "PATCH /findings/%s/status user=%s new_status=%s trace=%s",
        finding_id, identity.user_id, body.status, trace_id,
    )
    try:
        # Capture current status before update so we can emit old_status
        existing = await _get_or_404(finding_id, svc, repo, trace_id)
        old_status = existing.status.lower() if existing.status else None
        await svc.mark_status(
            finding_id, body.status, repo,
            publisher=publisher,
            tenant_id=getattr(identity, "tenant_id", "t1"),
            changed_by=identity.user_id,
            old_status=old_status,
        )
        # Re-fetch updated record
        detail = await _get_or_404(finding_id, svc, repo, trace_id)
        response.headers["X-Trace-ID"] = trace_id
        return detail
    except HTTPException:
        raise
    except AssertionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorDetail(
                code="INVALID_STATUS", message=str(exc), trace_id=trace_id,
            ).model_dump(),
        )
    except Exception as exc:
        logger.error("update_status error finding_id=%s: %s", finding_id, exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorDetail(
                code="INTERNAL_ERROR", message=str(exc), trace_id=trace_id,
            ).model_dump(),
        )


@router.post(
    "/{finding_id}/link-case",
    summary="Link an existing case to a finding",
    responses={
        200: {"description": "Updated finding with case_id set"},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def link_case(
    finding_id: str,
    body:       LinkCaseRequest,
    request:    Request,
    response:   Response,
    identity:   IdentityContext         = Depends(require_session_override),
    repo:       ThreatFindingRepository = Depends(get_finding_repo),
    svc:        ThreatFindingsService   = Depends(get_findings_service),
) -> FindingDetailResponse:
    trace_id = getattr(request.state, "trace_id", "")
    logger.info(
        "POST /findings/%s/link-case user=%s case_id=%s trace=%s",
        finding_id, identity.user_id, body.case_id, trace_id,
    )
    # Verify finding exists
    await _get_or_404(finding_id, svc, repo, trace_id)
    await svc.link_case(finding_id, body.case_id, repo)
    detail = await _get_or_404(finding_id, svc, repo, trace_id)
    response.headers["X-Trace-ID"] = trace_id
    return detail
