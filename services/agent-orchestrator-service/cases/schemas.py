"""
cases/schemas.py
────────────────
Pydantic v2 models for POST /api/v1/cases and GET /api/v1/cases.

CaseRecord     — internal domain dataclass (never serialised directly to routes)
CreateCaseRequest — request body: { session_id, reason }
CaseResponse   — single case in API responses
CaseListResponse — response body for GET /api/v1/cases
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Internal domain record (not a Pydantic model) ─────────────────────────────

@dataclass
class CaseRecord:
    case_id: str
    session_id: str
    reason: str
    summary: str
    risk_score: float
    decision: str
    status: str = "open"
    created_at: datetime = field(default_factory=_utcnow)


# ── API models ────────────────────────────────────────────────────────────────

class CreateCaseRequest(BaseModel):
    session_id: str = Field(..., description="ID of the session to escalate")
    reason: str = Field(..., min_length=1, description="Human-readable reason for escalation")


class CaseResponse(BaseModel):
    case_id: str
    session_id: str
    status: str
    created_at: datetime
    reason: str
    summary: str
    risk_score: float
    decision: str

    @classmethod
    def from_record(cls, rec: CaseRecord) -> "CaseResponse":
        return cls(
            case_id=rec.case_id,
            session_id=rec.session_id,
            status=rec.status,
            created_at=rec.created_at,
            reason=rec.reason,
            summary=rec.summary,
            risk_score=rec.risk_score,
            decision=rec.decision,
        )


class CaseListResponse(BaseModel):
    cases: List[CaseResponse]
    total: int
