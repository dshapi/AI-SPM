"""
schemas/events.py
─────────────────
Pydantic v2 models for every event emitted by agent-orchestrator-service.

Two layers live here:
  1. Domain payload types  — the data inside each specific event.
  2. Transport layer       — EventEnvelope (Kafka wire format) and
                             SessionLifecycleEvent (API / in-memory store format).

Session lifecycle order
───────────────────────
  prompt.received   →  risk.calculated  →  policy.decision
  →  session.created | session.blocked  →  session.completed
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Lifecycle event type enum
# ─────────────────────────────────────────────────────────────────────────────

class EventType(str, Enum):
    PROMPT_RECEIVED  = "prompt.received"
    RISK_CALCULATED  = "risk.calculated"
    POLICY_DECISION  = "policy.decision"
    SESSION_CREATED  = "session.created"
    SESSION_BLOCKED  = "session.blocked"
    SESSION_COMPLETED = "session.completed"
    LLM_RESPONSE     = "llm.response"
    OUTPUT_SCANNED   = "output.scanned"
    TOOL_REQUEST     = "tool.request"
    TOOL_OBSERVATION = "tool.observation"
    MEMORY_REQUEST   = "memory.request"
    MEMORY_RESULT    = "memory.result"
    FINAL_RESPONSE   = "final.response"
    UNKNOWN          = "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Kafka wire envelope  (CloudEvents-inspired)
# ─────────────────────────────────────────────────────────────────────────────

class EventEnvelope(BaseModel):
    """
    Standard transport wrapper — every Kafka message uses this shape.
    The `data` field holds the domain payload (model_dump of the specific
    *Payload class below).
    """
    event_id:      UUID            = Field(default_factory=uuid4)
    event_type:    str             = Field(..., description="Dot-namespaced type, e.g. session.created")
    source:        str             = Field(default="agent-orchestrator-service")
    spec_version:  str             = Field(default="1.0")
    time:          datetime        = Field(default_factory=_utcnow)
    correlation_id: str            = Field(..., description="Trace/correlation ID from the HTTP request")
    session_id:    Optional[UUID]  = Field(None, description="Session this event belongs to")
    tenant_id:     Optional[str]   = Field(None)
    data:          Dict[str, Any]  = Field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# In-memory / API representation of a single lifecycle event
# ─────────────────────────────────────────────────────────────────────────────

class SessionLifecycleEvent(BaseModel):
    """
    Stored in EventStore and returned by the API.
    Combines envelope metadata with the typed payload for easy consumption.
    """
    event_id:       UUID           = Field(default_factory=uuid4)
    event_type:     EventType
    session_id:     UUID
    correlation_id: str            = Field(..., description="Shared trace ID across all steps")
    timestamp:      datetime       = Field(default_factory=_utcnow)
    step:           int            = Field(..., description="Sequence position in the session pipeline (1-based)")
    status:         str            = Field(..., description="Outcome of this step, e.g. ok / blocked / scored")
    summary:        str            = Field(..., description="Human-readable one-liner for timeline display")
    payload:        Dict[str, Any] = Field(default_factory=dict, description="Full step-specific data")


# ─────────────────────────────────────────────────────────────────────────────
# Domain payload: prompt.received  (step 1)
# ─────────────────────────────────────────────────────────────────────────────

class PromptReceivedPayload(BaseModel):
    session_id:   UUID
    agent_id:     str
    user_id:      str
    user_email:   Optional[str]     = None  # Extracted from JWT email claim
    user_name:    Optional[str]     = None  # Extracted from JWT name claim
    tenant_id:    Optional[str]     = None
    prompt_hash:  str               = ""    # SHA-256
    prompt_len:   int               = 0     # Character count
    prompt:       Optional[str]     = None  # Raw prompt text (stored for dev/demo)
    tools:        List[str]         = Field(default_factory=list)
    context_keys: List[str]         = Field(default_factory=list)  # Keys present in context (not values)
    received_at:  datetime          = Field(default_factory=_utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# Domain payload: risk.calculated  (step 2)
# ─────────────────────────────────────────────────────────────────────────────

class RiskCalculatedPayload(BaseModel):
    session_id:  UUID
    risk_score:  float
    risk_tier:   str
    signals:     List[str]
    scored_at:   datetime           = Field(default_factory=_utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# Domain payload: policy.decision  (step 3)
# ─────────────────────────────────────────────────────────────────────────────

class PolicyDecisionPayload(BaseModel):
    session_id:      UUID
    decision:        str            # allow | block | escalate
    reason:          str
    policy_version:  str
    risk_score_at_decision: float
    decided_at:      datetime       = Field(default_factory=_utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# Domain payload: session.created  (step 4a — allowed path)
# ─────────────────────────────────────────────────────────────────────────────

class SessionCreatedPayload(BaseModel):
    session_id:      UUID
    agent_id:        str
    user_id:         str
    tenant_id:       Optional[str]
    prompt_hash:     str
    tools:           List[str]
    risk_score:      float
    risk_tier:       str
    policy_decision: str
    policy_version:  str
    created_at:      datetime       = Field(default_factory=_utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# Domain payload: session.blocked  (step 4b — blocked path)
# ─────────────────────────────────────────────────────────────────────────────

class SessionBlockedPayload(BaseModel):
    session_id:      UUID
    agent_id:        str
    user_id:         str
    reason:          str
    policy_version:  str
    risk_score:      float
    blocked_at:      datetime       = Field(default_factory=_utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# Domain payload: llm.response  (step 6 — LLM execution metrics)
# ─────────────────────────────────────────────────────────────────────────────

class LLMResponsePayload(BaseModel):
    model: str
    input_tokens: int
    output_tokens: int
    stop_reason: str
    response_length: int          # char count only, no raw text in events
    latency_ms: int


# ─────────────────────────────────────────────────────────────────────────────
# Domain payload: output.scanned  (step 7 — output security scanning)
# ─────────────────────────────────────────────────────────────────────────────

class OutputScannedPayload(BaseModel):
    verdict: str                  # allow | flag | block
    pii_types: List[str] = []
    secret_types: List[str] = []
    scan_notes: List[str] = []
    llm_scan_enabled: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# Domain payload: session.completed  (step 5 — always last)
# ─────────────────────────────────────────────────────────────────────────────

class SessionCompletedPayload(BaseModel):
    session_id:       UUID
    final_status:     str           # started | blocked | escalated
    policy_decision:  str
    risk_score:       float
    duration_ms:      float         # Wall-clock time for the full pipeline
    event_count:      int           # How many lifecycle events were emitted
    completed_at:     datetime      = Field(default_factory=_utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# API response models
# ─────────────────────────────────────────────────────────────────────────────

class SessionEventListResponse(BaseModel):
    session_id:     UUID
    correlation_id: str
    event_count:    int
    events:         List[SessionLifecycleEvent]


class SessionTimelineEntry(BaseModel):
    """Condensed view used in GET /sessions/{id} timeline array."""
    step:       int
    event_type: EventType
    status:     str
    summary:    str
    timestamp:  datetime
