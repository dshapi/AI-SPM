from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class FindingRecord:
    id:           str
    batch_hash:   str
    title:        str
    severity:     str
    description:  str
    evidence:     List[Any]   # was Dict; list matches Finding.evidence: List[str]
    ttps:         List[str]
    tenant_id:    str
    status:       str = "open"
    created_at:   str = field(default_factory=_utcnow)
    closed_at:    Optional[str] = None
    deduplicated: bool = False     # transient — not persisted

    # ── New Finding fields ────────────────────────────────────────────
    timestamp:           Optional[str]        = None
    confidence:          Optional[float]      = None
    risk_score:          Optional[float]      = None
    hypothesis:          Optional[str]        = None
    asset:               Optional[str]        = None
    environment:         Optional[str]        = None
    correlated_events:   Optional[List[str]]  = None
    correlated_findings: Optional[List[str]]  = None
    triggered_policies:  Optional[List[str]]  = None
    policy_signals:      Optional[List[Any]]  = None
    recommended_actions: Optional[List[str]]  = None
    should_open_case:    bool                 = False
    case_id:             Optional[str]        = None
    source:              Optional[str]        = None
    updated_at:          Optional[str]        = None
    is_proactive:        bool                 = False


class CreateFindingRequest(BaseModel):
    title:       str   = Field(..., min_length=1)
    severity:    str   = Field(..., pattern="^(low|medium|high|critical)$")
    description: str   = Field(..., min_length=1)
    evidence:    List[Any] = Field(default_factory=list)
    ttps:        List[str] = Field(default_factory=list)
    tenant_id:   str   = Field(..., min_length=1)
    batch_hash:  str   = Field(..., min_length=1)

    # ── New fields (all optional for backward compat) ─────────────────
    timestamp:           Optional[str]       = None
    confidence:          Optional[float]     = Field(None, ge=0.0, le=1.0)
    risk_score:          Optional[float]     = Field(None, ge=0.0, le=1.0)
    hypothesis:          Optional[str]       = None
    asset:               Optional[str]       = None
    environment:         Optional[str]       = None
    correlated_events:   Optional[List[str]] = None
    correlated_findings: Optional[List[str]] = None
    triggered_policies:  Optional[List[str]] = None
    policy_signals:      Optional[List[Any]] = None
    recommended_actions: Optional[List[str]] = None
    should_open_case:    bool                = False
    case_id:             Optional[str]       = None
    source:              Optional[str]       = None
    is_proactive:        bool                = False


@dataclass
class FindingFilter:
    severity:   Optional[str]  = None
    status:     Optional[str]  = None
    asset:      Optional[str]  = None
    tenant_id:  Optional[str]  = None
    has_case:   Optional[bool] = None
    from_ts:    Optional[str]  = None
    to_ts:      Optional[str]  = None
    limit:      int            = 50
    offset:     int            = 0
    min_risk_score: Optional[float] = None
    sort_by:        Optional[str]   = None


class FindingResponse(BaseModel):
    id:           str
    title:        str
    severity:     str
    status:       str
    created_at:   str
    deduplicated: bool = False
    confidence:   Optional[float] = None
    risk_score:   Optional[float] = None
    should_open_case: bool = False

    @classmethod
    def from_record(cls, rec: FindingRecord) -> "FindingResponse":
        return cls(
            id=rec.id, title=rec.title, severity=rec.severity,
            status=rec.status, created_at=rec.created_at,
            deduplicated=rec.deduplicated,
            confidence=rec.confidence,
            risk_score=rec.risk_score,
            should_open_case=rec.should_open_case,
        )
