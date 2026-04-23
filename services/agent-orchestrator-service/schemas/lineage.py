"""
schemas/lineage.py
──────────────────
Pydantic models for the /api/v1/lineage/events ingestion endpoint.

Context
───────
The api service (chat gateway) emits UI-lineage events directly to WebSocket
clients via ConnectionManager.broadcast(). Those events were previously only
held in memory and were lost when the ConnectionManager's LRU cache evicted
old sessions (cap=50). This caused the Lineage UI to fall back to a synthetic
reconstruction built from the Finding record — a schematic, not the real run.

To fix that without adding a DB dependency to the api service, the api side
dual-writes each UI-lineage event to this orchestrator endpoint. The
orchestrator is the only service with Postgres access and already owns the
session_events table + EventRepository.

Intentional looseness
─────────────────────
`payload` is a free-form dict — unlike the strict EventType enum for
orchestrator-internal events, these come from the api service's UI layer and
carry per-event-type shapes (session.started, tool.invoked, policy.allowed,
etc.) that aren't worth enumerating server-side. We persist the payload as-is
and let the UI render it. Validation beyond "is a dict" would force the api
service and orchestrator to version-lock a schema for UI-only data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class LineageEventIngest(BaseModel):
    """One UI-lineage event submitted by the api service for persistence."""
    session_id:     str
    event_type:     str                       # e.g. "session.started", "tool.invoked"
    payload:        Dict[str, Any] = Field(default_factory=dict)
    timestamp:      Optional[datetime] = None # server fills `now()` if omitted
    correlation_id: Optional[str] = None

    # Optional parent-session upsert hints — used ONLY when the parent
    # agent_sessions row doesn't exist yet (FK prerequisite for the insert).
    # If the parent already exists, these are ignored.
    agent_id:       Optional[str] = None      # default: "chat-agent"
    user_id:        Optional[str] = None      # default: "anonymous"
    tenant_id:      Optional[str] = None
    source:         Optional[str] = None      # e.g. "api-chat", "simulation"


class LineageEventIngestResponse(BaseModel):
    """Acknowledge persist. 202 on success, so clients know it's best-effort."""
    session_id:    str
    event_id:      str
    session_created: bool = Field(
        description="True if this call also created the parent agent_sessions row.",
    )


class BulkLineageIngestRequest(BaseModel):
    """
    Bulk variant — useful for replay / catch-up when the api service wants to
    flush a queue. Events MUST all share the same session_id.
    """
    session_id: str
    events:     List[LineageEventIngest]


class BulkLineageIngestResponse(BaseModel):
    session_id:      str
    inserted_count:  int
    session_created: bool


# ─────────────────────────────────────────────────────────────────────────────
# Read-back models — serve the UI directly, in the same WS-wire envelope the
# api service's ConnectionManager broadcasts. By returning exactly that shape
# the UI can feed these events through the same normaliser it uses for live
# WebSocket frames, with no adapter layer.
# ─────────────────────────────────────────────────────────────────────────────

class WSLineageEvent(BaseModel):
    """
    WS-wire envelope for a persisted lineage event. Mirrors what the api
    service broadcasts via ConnectionManager.broadcast() so the UI can hydrate
    the Lineage graph identically from live frames or historical reads.
    """
    session_id:     str
    event_type:     str
    source_service: str
    correlation_id: Optional[str] = None
    timestamp:      str                       # ISO-8601 UTC (e.g. 2026-04-22T10:15:00Z)
    payload:        Dict[str, Any] = Field(default_factory=dict)


class SessionEventsResponse(BaseModel):
    """Read-back for a single session's full persisted event history."""
    session_id: str
    events:     List[WSLineageEvent]


class SessionSummary(BaseModel):
    """Summary row for the Lineage page's recent-sessions picker."""
    session_id:        str
    event_count:       int
    first_timestamp:   Optional[str] = None
    last_timestamp:    Optional[str] = None
    first_event_type:  Optional[str] = None
    last_event_type:   Optional[str] = None
    prompt:            Optional[str] = None


class SessionsListResponse(BaseModel):
    sessions: List[SessionSummary]
