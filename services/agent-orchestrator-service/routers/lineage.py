"""
routers/lineage.py
──────────────────
Ingest endpoint for UI-lineage events emitted by the api service (chat
gateway). This is the persistence layer for Lineage-page replay fidelity.

Why this exists
───────────────
The api service emits a stream of UI-shaped lineage events
(session.started, context.retrieved, risk.calculated, tool.invoked,
policy.allowed/blocked, output.generated, session.completed) directly to
WebSocket clients via ConnectionManager.broadcast(). Those events were
only held in memory (LRU cap 50 sessions). When the cap evicted a session,
the Lineage page could no longer replay it — it fell back to a synthetic
reconstruction built from the Finding's narrative fields.

To fix that without adding Postgres to the stateless api service, the api
side dual-writes every broadcast to this endpoint. The orchestrator is the
only service with DB access and already owns `session_events` + the
EventRepository. The api service becomes a hot cache; the orchestrator DB
becomes the source of truth.

FK constraint
─────────────
`session_events.session_id` has a FK to `agent_sessions.id` with
ON DELETE CASCADE. Every insert requires the parent row to exist first.
For chat sessions that already went through `POST /api/v1/sessions`, the
parent exists — the insert is a plain append. For sessions that haven't
been formally registered yet (events racing ahead of the orchestrator's
own pipeline, or UI-only flows like simulation playback), we UPSERT a
placeholder parent row with sensible defaults. The placeholder gets
superseded if/when the real session is registered later.

Design
──────
- Best-effort, 202 Accepted on success — callers MUST treat this as
  fire-and-forget. Errors are logged, never propagated.
- No RBAC for now. Internal backend-to-backend only; network isolation
  is the control. A future hardening pass can add a service token check.
- Single-event + bulk variants. Bulk is for catch-up flushes.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status

from dependencies.db import get_event_repo, get_session_repo
from models.event import EventRecord, EventRepository
from models.session import SessionRecord, SessionRepository
from schemas.lineage import (
    BulkLineageIngestRequest,
    BulkLineageIngestResponse,
    LineageEventIngest,
    LineageEventIngestResponse,
    SessionEventsResponse,
    SessionSummary,
    SessionsListResponse,
    WSLineageEvent,
)
from services.lineage_ingest import (
    LineageEventInput,
    ensure_parent_session,
    persist_lineage_event,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/lineage", tags=["Lineage"])


# NOTE: _placeholder_session + _ensure_parent_session moved to
# services/lineage_ingest.py so the new Kafka consumer
# (consumers/lineage_consumer.py) can call the same helpers.
# Re-exported here as `ensure_parent_session` (no underscore) for the
# bulk endpoint below.


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/lineage/events  — single event
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/events",
    response_model=LineageEventIngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Persist a single UI-lineage event (internal, from api service)",
    description=(
        "Internal endpoint. The api service (chat gateway) calls this after "
        "each `ConnectionManager.broadcast()` so the event survives LRU "
        "eviction of the in-memory log and the Lineage page can render it "
        "from persistent storage forever. Returns 202 to signal best-effort."
    ),
)
async def ingest_event(
    body:         LineageEventIngest,
    request:      Request,
    session_repo: SessionRepository = Depends(get_session_repo),
    event_repo:   EventRepository   = Depends(get_event_repo),
) -> LineageEventIngestResponse:
    trace_id = getattr(request.state, "trace_id", None) or body.correlation_id

    try:
        # Delegate to the shared persistence service so the Kafka consumer
        # and this HTTP handler take the SAME code path — guarantees the
        # persisted EventRecord is byte-identical regardless of transport.
        result = await persist_lineage_event(
            session_repo,
            event_repo,
            LineageEventInput(
                session_id     = body.session_id,
                event_type     = body.event_type,
                payload        = body.payload or {},
                timestamp      = body.timestamp,
                correlation_id = body.correlation_id,
                agent_id       = body.agent_id,
                user_id        = body.user_id,
                tenant_id      = body.tenant_id,
                source         = body.source,
            ),
            trace_id_fallback = trace_id,
        )

        return LineageEventIngestResponse(
            session_id      = result.session_id,
            event_id        = result.event_id,
            session_created = result.session_created,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(
            "lineage-ingest failed session=%s type=%s err=%s",
            body.session_id, body.event_type, exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="lineage-ingest failed",
        )


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/lineage/events/bulk  — batched variant
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/events/bulk",
    response_model=BulkLineageIngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Persist a batch of UI-lineage events for one session (internal)",
    description=(
        "Bulk variant of /events. All events MUST share the same session_id. "
        "Used for catch-up flushes from the api service, e.g. on reconnect."
    ),
)
async def ingest_events_bulk(
    body:         BulkLineageIngestRequest,
    request:      Request,
    session_repo: SessionRepository = Depends(get_session_repo),
    event_repo:   EventRepository   = Depends(get_event_repo),
) -> BulkLineageIngestResponse:
    if not body.events:
        return BulkLineageIngestResponse(
            session_id=body.session_id, inserted_count=0, session_created=False,
        )

    # Validate that every event in the batch actually belongs to this session.
    for ev in body.events:
        if ev.session_id != body.session_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"event session_id {ev.session_id!r} does not match batch session_id {body.session_id!r}",
            )

    trace_id = getattr(request.state, "trace_id", None)

    # Parent row upsert uses the first event's upsert hints (they should all
    # be identical for a single session anyway).
    first = body.events[0]
    try:
        session_created = await ensure_parent_session(
            session_repo,
            session_id=body.session_id,
            agent_id=first.agent_id,
            user_id=first.user_id,
            tenant_id=first.tenant_id,
            source=first.source,
            trace_id=trace_id,
        )

        records = [
            EventRecord(
                session_id=ev.session_id,
                event_type=ev.event_type,
                payload=json.dumps(ev.payload or {}),
                timestamp=ev.timestamp or datetime.now(timezone.utc),
            )
            for ev in body.events
        ]
        await event_repo.bulk_insert(records)

        return BulkLineageIngestResponse(
            session_id=body.session_id,
            inserted_count=len(records),
            session_created=session_created,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(
            "lineage-ingest bulk failed session=%s count=%d err=%s",
            body.session_id, len(body.events), exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="lineage-ingest bulk failed",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Read-back: serve the UI directly in WS-wire shape
# ─────────────────────────────────────────────────────────────────────────────
#
# The api service has a bounded in-memory log (LRU cap 50 sessions). When it
# evicts a session, these endpoints let the UI/api service fall back to the
# persistent store and still hydrate the Lineage graph. They return data in
# the EXACT shape the api service broadcasts over WebSocket, so the UI's
# normaliser works unchanged for both live frames and historical reads.

def _event_to_ws_wire(
    record: EventRecord,
    *,
    session_id: str,
    source_service: str = "api-chat",
) -> WSLineageEvent:
    """Decode the stored JSON payload back into a dict and wrap in the WS envelope."""
    try:
        payload = json.loads(record.payload) if record.payload else {}
    except Exception:
        # Legacy rows may hold a non-JSON string — keep it inspectable rather
        # than failing the whole read.
        payload = {"_raw": record.payload}

    return WSLineageEvent(
        session_id     = session_id,
        event_type     = record.event_type,
        source_service = source_service,
        correlation_id = None,                 # correlation_id isn't stored on session_events; api side derives per-event if needed
        timestamp      = record.timestamp.isoformat().replace("+00:00", "Z"),
        payload        = payload,
    )


@router.get(
    "/sessions/{session_id}/events",
    response_model=SessionEventsResponse,
    summary="Replay a session's persisted lineage events (internal, WS-wire shape)",
    description=(
        "Read-back endpoint for the api service's Lineage fallback. Returns "
        "every persisted event for `session_id` in the same WS-wire envelope "
        "shape the api service's ConnectionManager.broadcast() emits, so the "
        "UI normaliser handles live frames and historical reads identically. "
        "Returns an empty list (never 404) when the session has no events."
    ),
)
async def replay_session_events(
    session_id: str,
    request:    Request,
    event_repo:   EventRepository   = Depends(get_event_repo),
    session_repo: SessionRepository = Depends(get_session_repo),
) -> SessionEventsResponse:
    records = await event_repo.get_by_session_id(session_id)

    # ── Lazy backfill for threat-hunt synthetic sessions ──────────────────
    # Cases auto-opened by the threat-hunting agent use a session_id of
    # ``threat-hunt:{finding_id}`` and weren't always populated with lineage
    # events at create time (the Kafka emit path was added later, and any
    # case opened while the broker was unreachable would have skipped the
    # publish). When the Lineage page asks for one of these and we have no
    # rows, look the finding up and persist the canonical event track from
    # its real fields, then re-read.
    if not records and session_id.startswith("threat-hunt:"):
        finding_id = session_id.split(":", 1)[1]
        try:
            from threat_findings.models import ThreatFindingRepository
            from threat_findings.service import ThreatFindingsService

            db_session   = event_repo._session
            finding_repo = ThreatFindingRepository(db_session)
            finding      = await finding_repo.get_by_id(finding_id)
            if finding is not None:
                await ThreatFindingsService.backfill_threat_hunt_lineage(
                    finding      = finding,
                    session_id   = session_id,
                    session_repo = session_repo,
                    event_repo   = event_repo,
                )
                records = await event_repo.get_by_session_id(session_id)
            else:
                logger.info(
                    "lineage_backfill: no finding found for session=%s — returning empty",
                    session_id,
                )
        except Exception as exc:
            logger.warning(
                "lineage_backfill_failed session=%s err=%s",
                session_id, exc,
            )

    events = [_event_to_ws_wire(r, session_id=session_id) for r in records]
    return SessionEventsResponse(session_id=session_id, events=events)


@router.get(
    "/sessions",
    response_model=SessionsListResponse,
    summary="List recent sessions with persisted lineage events (internal)",
    description=(
        "Lineage-picker backing store. Returns sessions that have at least "
        "one persisted event, ordered most-recent-activity first. Summary "
        "shape matches the api service's in-memory ConnectionManager."
        "list_sessions() so UI code can union the two streams."
    ),
)
async def list_lineage_sessions(
    limit: int = 50,
    session_repo: SessionRepository = Depends(get_session_repo),
    event_repo:   EventRepository   = Depends(get_event_repo),
) -> SessionsListResponse:
    # Pull recent sessions by created_at desc. We then hydrate each with its
    # persisted event list to fill in first/last timestamps + event types and
    # the session-started prompt. Kept simple (no SQL aggregation) because the
    # LRU-matching cap means we only need ~50 rows and this endpoint is hit
    # from one UI client at a time.
    session_rows = await session_repo.list_all(limit=max(1, min(limit, 200)))

    summaries: list[SessionSummary] = []
    for s in session_rows:
        events = await event_repo.get_by_session_id(s.session_id)
        if not events:
            # Skip sessions with no persisted events — they'd show up as empty
            # rows in the picker, which is worse than not showing them at all.
            continue

        events_sorted = sorted(events, key=lambda e: e.timestamp)
        first = events_sorted[0]
        last  = events_sorted[-1]

        prompt: Optional[str] = None
        for e in events_sorted:
            try:
                p = json.loads(e.payload) if e.payload else {}
            except Exception:
                p = {}
            if isinstance(p, dict) and p.get("prompt"):
                prompt = p["prompt"]
                break

        summaries.append(SessionSummary(
            session_id       = s.session_id,
            event_count      = len(events_sorted),
            first_timestamp  = first.timestamp.isoformat().replace("+00:00", "Z"),
            last_timestamp   = last.timestamp.isoformat().replace("+00:00", "Z"),
            first_event_type = first.event_type,
            last_event_type  = last.event_type,
            prompt           = prompt,
        ))

    # Most-recent-activity first.
    summaries.sort(key=lambda s: s.last_timestamp or "", reverse=True)
    return SessionsListResponse(sessions=summaries)
