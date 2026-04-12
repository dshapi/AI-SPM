"""
routers/sessions.py
────────────────────
Thin HTTP routing layer — zero business logic.

RBAC enforcement
────────────────
  POST   /api/v1/sessions          → requires  agent.invoke
  GET    /api/v1/sessions          → requires  session.read
  GET    /api/v1/sessions/{id}     → requires  session.read
  GET    /api/v1/sessions/{id}/events → requires  session.read

The RequirePermission dependency handles both authentication (via the
inner get_current_identity dep) and authorization in a single Depends()
call.  Routes receive the IdentityContext directly from the dependency
— no separate auth dep needed.
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from dependencies.auth import IdentityContext
from dependencies.db import get_session_repo, get_event_repo, get_case_repo
from dependencies.rbac import (
    effective_permissions,
    require_agent_invoke,
    require_session_read,
)
from events.store import EventStore
from models.cases import CaseRepository
from models.event import EventRepository
from models.session import SessionRepository
from schemas.events import SessionEventListResponse, SessionTimelineEntry
from schemas.session import (
    CreateSessionRequest,
    CreateSessionResponse,
    ErrorDetail,
    ErrorResponse,
    PolicyOutcome,
)
from services.session_service import SessionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/sessions", tags=["Sessions"])


# ─────────────────────────────────────────────────────────────────────────────
# Internal dependency: assemble SessionService
# ─────────────────────────────────────────────────────────────────────────────

def get_session_service(
    request: Request,
    repo: SessionRepository = Depends(get_session_repo),
    event_repo: EventRepository = Depends(get_event_repo),
) -> SessionService:
    return SessionService(
        risk_engine=request.app.state.risk_engine,
        policy_client=request.app.state.policy_client,
        event_publisher=request.app.state.event_publisher,
        session_repo=repo,
        event_store=request.app.state.event_store,
        llm_client=getattr(request.app.state, "llm_client", None),
        prompt_processor=getattr(request.app.state, "prompt_processor", None),
        event_repo=event_repo,
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/sessions/me  — caller identity + effective permissions
#
# MUST be declared BEFORE /{session_id} so FastAPI matches the literal
# path segment "me" rather than treating it as a UUID parameter.
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/me",
    tags=["Identity"],
    summary="Caller identity and effective permissions",
    description=(
        "Returns the decoded identity from the Bearer token plus the "
        "full set of permissions the caller currently holds. "
        "Useful for UI permission gating and debugging auth issues."
    ),
    responses={401: {"model": ErrorResponse}},
)
async def whoami(
    request: Request,
    response: Response,
    identity: IdentityContext = Depends(require_session_read),
) -> dict:
    response.headers["X-Trace-ID"] = request.state.trace_id
    return {
        "user_id":               identity.user_id,
        "email":                 identity.email,
        "tenant_id":             identity.tenant_id,
        "roles":                 identity.roles,
        "groups":                identity.groups,
        "env":                   identity.env,
        "effective_permissions": effective_permissions(identity),
        "trace_id":              request.state.trace_id,
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/sessions  — create session
# Permission: agent.invoke
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=CreateSessionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Session created; inspect policy.decision for allow/block status"},
        401: {"model": ErrorResponse, "description": "Missing or invalid Bearer token"},
        403: {"model": ErrorResponse, "description": "PERMISSION_DENIED: requires agent.invoke"},
        422: {"description": "Request body validation error"},
    },
    summary="Create an AI agent session",
    description=(
        "**Required permission:** `agent.invoke`\n\n"
        "Roles that satisfy this: `agent_operator`, `admin`, `spm:admin`.\n\n"
        "Validates caller identity, scores prompt risk, evaluates policy, "
        "persists the session record, and publishes all 5 lifecycle events."
    ),
)
async def create_session(
    body: CreateSessionRequest,
    request: Request,
    response: Response,
    # RequirePermission checks auth + RBAC; returns IdentityContext on success
    identity: IdentityContext = Depends(require_agent_invoke),
    service: SessionService = Depends(get_session_service),
    session_repo: SessionRepository = Depends(get_session_repo),
    event_repo: EventRepository = Depends(get_event_repo),
    case_repo: CaseRepository = Depends(get_case_repo),
) -> CreateSessionResponse:
    trace_id = request.state.trace_id
    response.headers["X-Trace-ID"] = trace_id

    logger.info(
        "POST /sessions agent=%s user=%s roles=%s trace=%s",
        body.agent_id, identity.user_id, identity.roles, trace_id,
    )

    result = await service.create_session(
        request=body,
        identity=identity,
        trace_id=trace_id,
    )

    # Auto-escalate blocked/escalated sessions to a case so they appear
    # in the Cases tab without requiring manual triage from the Runtime page.
    if result.policy.decision.value in ("block", "escalate"):
        try:
            cases_svc   = request.app.state.cases_service
            results_svc = request.app.state.results_service
            await cases_svc.create_case(
                session_id=str(result.session_id),
                reason=result.policy.reason or result.policy.decision.value,
                session_repo=session_repo,
                event_repo=event_repo,
                results_svc=results_svc,
                case_repo=case_repo,
            )
            logger.info(
                "Auto-created case for blocked session=%s decision=%s",
                result.session_id, result.policy.decision.value,
            )
        except Exception as exc:
            # Never let case creation break the session response
            logger.warning("Auto-case creation failed session=%s: %s", result.session_id, exc)

    return CreateSessionResponse(
        session_id=result.session_id,
        status=result.status,
        agent_id=body.agent_id,
        risk=result.risk.to_schema(),
        policy=PolicyOutcome(
            decision=result.policy.decision,
            reason=result.policy.reason,
            policy_version=result.policy.policy_version,
        ),
        trace_id=trace_id,
        created_at=result.created_at,
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/sessions/{session_id}  — detail + events timeline
# Permission: session.read
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/{session_id}",
    summary="Session detail with events timeline",
    description=(
        "**Required permission:** `session.read`\n\n"
        "Roles: `agent_operator`, `security_analyst`, `viewer`, `admin`.\n\n"
        "Returns the session record plus a condensed `events_timeline`. "
        "Use `GET /{id}/events` for full payloads."
    ),
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse, "description": "PERMISSION_DENIED: requires session.read"},
        404: {"model": ErrorResponse},
    },
)
async def get_session(
    session_id: UUID,
    request: Request,
    response: Response,
    identity: IdentityContext = Depends(require_session_read),
    service: SessionService = Depends(get_session_service),
) -> dict:
    trace_id = request.state.trace_id
    response.headers["X-Trace-ID"] = trace_id

    record = await service.get_session(str(session_id))
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorDetail(
                code="SESSION_NOT_FOUND",
                message=f"Session {session_id} does not exist.",
                trace_id=trace_id,
            ).model_dump(),
        )

    raw_events = await service.get_events(str(session_id))
    timeline = [
        SessionTimelineEntry(
            step=e.step,
            event_type=e.event_type,
            status=e.status,
            summary=e.summary,
            timestamp=e.timestamp,
        ).model_dump(mode="json")
        for e in sorted(raw_events, key=lambda x: x.step)
    ]

    return {
        "session_id":  record.session_id,
        "agent_id":    record.agent_id,
        "user_id":     record.user_id,
        "tenant_id":   record.tenant_id,
        "status":      record.status,
        "risk": {
            "score":   record.risk_score,
            "tier":    record.risk_tier,
            "signals": record.risk_signals,
        },
        "policy": {
            "decision": record.policy_decision,
            "reason":   record.policy_reason,
            "version":  record.policy_version,
        },
        "correlation_id":   record.trace_id,
        "created_at":       record.created_at.isoformat(),
        "updated_at":       record.updated_at.isoformat(),
        "events_timeline":  timeline,
        "event_count":      len(raw_events),
        "_links": {
            "events": f"/api/v1/sessions/{session_id}/events",
            "self":   f"/api/v1/sessions/{session_id}",
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/sessions/{session_id}/events  — full event history
# Permission: session.read
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/{session_id}/events",
    response_model=SessionEventListResponse,
    summary="Full lifecycle event history",
    description=(
        "**Required permission:** `session.read`\n\n"
        "Returns all 5 lifecycle events in pipeline order with full payloads, "
        "timestamps, and the shared `correlation_id`."
    ),
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse, "description": "PERMISSION_DENIED: requires session.read"},
        404: {"model": ErrorResponse},
    },
)
async def get_session_events(
    session_id: UUID,
    request: Request,
    response: Response,
    identity: IdentityContext = Depends(require_session_read),
    service: SessionService = Depends(get_session_service),
) -> SessionEventListResponse:
    trace_id = request.state.trace_id
    response.headers["X-Trace-ID"] = trace_id

    record = await service.get_session(str(session_id))
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorDetail(
                code="SESSION_NOT_FOUND",
                message=f"Session {session_id} does not exist.",
                trace_id=trace_id,
            ).model_dump(),
        )

    events = await service.get_events(str(session_id))

    # Backfill user identity into prompt.received events that predate the
    # user_email / user_name payload fields (or were created without them).
    ctx = record.context or {}
    ctx_email = ctx.get("email")
    ctx_name  = ctx.get("name") or ctx.get("user_id")
    if ctx_email or ctx_name:
        import copy
        patched = []
        for ev in events:
            if ev.event_type == "prompt.received":
                payload = ev.payload or {}
                if not payload.get("user_email") and not payload.get("user_name"):
                    ev = copy.copy(ev)
                    payload = dict(payload)
                    if ctx_email: payload["user_email"] = ctx_email
                    if ctx_name:  payload["user_name"]  = ctx_name
                    ev.payload = payload
            patched.append(ev)
        events = patched

    return SessionEventListResponse(
        session_id=session_id,
        correlation_id=record.trace_id,
        event_count=len(events),
        events=sorted(events, key=lambda e: e.step),
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/sessions  — list by agent_id
# Permission: session.read
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "",
    summary="List recent sessions for an agent",
    description="**Required permission:** `session.read`",
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse, "description": "PERMISSION_DENIED: requires session.read"},
    },
)
async def list_sessions(
    agent_id: Optional[str] = None,
    limit: int = 50,
    request: Request = None,
    response: Response = None,
    identity: IdentityContext = Depends(require_session_read),
    service: SessionService = Depends(get_session_service),
) -> dict:
    if response:
        response.headers["X-Trace-ID"] = request.state.trace_id

    if agent_id:
        records = await service.list_sessions_for_agent(agent_id, limit=limit)
    else:
        records = await service.list_all_sessions(limit=limit)

    return {
        "agent_id": agent_id,
        "count":    len(records),
        "sessions": [
            {
                "session_id":      r.session_id,
                "agent_id":        r.agent_id,
                "status":          r.status,
                "risk_score":      r.risk_score,
                "risk_tier":       r.risk_tier,
                "policy_decision": r.policy_decision,
                "created_at":      r.created_at.isoformat(),
                "_links": {
                    "detail": f"/api/v1/sessions/{r.session_id}",
                    "events": f"/api/v1/sessions/{r.session_id}/events",
                },
            }
            for r in records
        ],
    }


