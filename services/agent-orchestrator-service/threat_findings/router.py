from __future__ import annotations
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies.auth import IdentityContext
from dependencies.rbac import require_session_override
from models.cases import CaseRepository
from schemas.session import ErrorDetail, ErrorResponse
from threat_findings.models import ThreatFindingRepository
from threat_findings.schemas import CreateFindingRequest, FindingResponse
from threat_findings.service import ThreatFindingsService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/threat-findings", tags=["ThreatFindings"])


# ── Dependency functions ──────────────────────────────────────────────────────

def get_findings_service(request: Request) -> ThreatFindingsService:
    return request.app.state.threat_findings_service


async def get_async_db(request: Request):
    factory = request.app.state.db_session_factory
    async with factory() as session:
        yield session


async def get_finding_repo(
    session: AsyncSession = Depends(get_async_db),
) -> ThreatFindingRepository:
    return ThreatFindingRepository(session)


async def get_case_repo(
    session: AsyncSession = Depends(get_async_db),
) -> CaseRepository:
    return CaseRepository(session)


# ── Route ─────────────────────────────────────────────────────────────────────

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Finding created"},
        200: {"description": "Deduplicated — finding already exists"},
        401: {"model": ErrorResponse},
        403: {
            "model": ErrorResponse,
            "description": "PERMISSION_DENIED: requires session.override",
        },
        500: {"model": ErrorResponse},
    },
    summary="Create a threat finding (internal — threat-hunting-agent only)",
    description=(
        "**Required permission:** `session.override`\n\n"
        "Called by the threat-hunting-agent with a dev-token (admin role). "
        "Human analysts with the `security_analyst` role can also POST findings manually."
    ),
)
async def create_finding(
    body:      CreateFindingRequest,
    request:   Request,
    response:  Response,
    identity:  IdentityContext             = Depends(require_session_override),
    repo:      ThreatFindingRepository     = Depends(get_finding_repo),
    case_repo: CaseRepository              = Depends(get_case_repo),
    svc:       ThreatFindingsService       = Depends(get_findings_service),
) -> FindingResponse:
    trace_id = getattr(request.state, "trace_id", "")
    logger.info(
        "POST /threat-findings tenant=%s user=%s trace=%s",
        body.tenant_id, identity.user_id, trace_id,
    )
    try:
        rec = await svc.create_finding(body, repo, case_repo)
        if rec.deduplicated:
            response.status_code = status.HTTP_200_OK
        return FindingResponse.from_record(rec)
    except Exception as exc:
        logger.error("create_finding error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorDetail(
                code="INTERNAL_ERROR", message=str(exc), trace_id=trace_id,
            ).model_dump(),
        )
