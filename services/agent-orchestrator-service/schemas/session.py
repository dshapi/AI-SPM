"""
schemas/session.py
──────────────────
Pydantic v2 request / response contracts for the sessions endpoint.
All public-facing data shapes live here; routers import only these.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────────────────────────────────────

class SessionStatus(str, Enum):
    STARTED   = "started"
    RUNNING   = "running"
    BLOCKED   = "blocked"
    COMPLETED = "completed"
    FAILED    = "failed"


class PolicyDecision(str, Enum):
    ALLOW     = "allow"
    BLOCK     = "block"
    ESCALATE  = "escalate"


class RiskTier(str, Enum):
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


# ─────────────────────────────────────────────────────────────────────────────
# Request schemas
# ─────────────────────────────────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    """Body for POST /api/v1/sessions"""

    agent_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Unique identifier of the registered AI agent.",
        examples=["agent-sales-copilot-v2"],
    )
    prompt: str = Field(
        ...,
        min_length=1,
        max_length=32_768,
        description="The user prompt that initiates the agent session.",
    )
    tools: List[str] = Field(
        default_factory=list,
        description="Optional list of tool names the agent may invoke.",
        examples=[["web_search", "sql_query"]],
    )
    context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary caller-supplied context (user metadata, env flags, etc.).",
    )

    @field_validator("tools")
    @classmethod
    def tools_no_duplicates(cls, v: List[str]) -> List[str]:
        seen: set[str] = set()
        out: List[str] = []
        for t in v:
            if t not in seen:
                seen.add(t)
                out.append(t)
        return out


# ─────────────────────────────────────────────────────────────────────────────
# Response schemas
# ─────────────────────────────────────────────────────────────────────────────

class RiskSummary(BaseModel):
    score: float = Field(..., ge=0.0, le=1.0)
    tier: RiskTier
    signals: List[str] = Field(default_factory=list)


class PolicyOutcome(BaseModel):
    decision: PolicyDecision
    reason: str
    policy_version: str


class CreateSessionResponse(BaseModel):
    """Successful response for POST /api/v1/sessions"""

    session_id: UUID
    status: SessionStatus
    agent_id: str
    risk: RiskSummary
    policy: PolicyOutcome
    trace_id: str
    created_at: datetime


class ErrorDetail(BaseModel):
    code: str
    message: str
    trace_id: Optional[str] = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
