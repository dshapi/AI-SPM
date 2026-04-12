from __future__ import annotations

from typing import Any, List, Optional
from pydantic import BaseModel, Field

from threat_findings.schemas import FindingRecord


# ── List-level item (compact) ─────────────────────────────────────────────────

class FindingListItem(BaseModel):
    id:               str
    title:            str
    severity:         str
    status:           str
    created_at:       str
    updated_at:       Optional[str]  = None
    risk_score:       Optional[float] = None
    confidence:       Optional[float] = None
    asset:            Optional[str]  = None
    should_open_case: bool           = False
    case_id:          Optional[str]  = None
    source:           Optional[str]  = None

    @classmethod
    def from_record(cls, rec: FindingRecord) -> "FindingListItem":
        return cls(
            id=rec.id,
            title=rec.title,
            severity=rec.severity,
            status=rec.status,
            created_at=rec.created_at,
            updated_at=rec.updated_at,
            risk_score=rec.risk_score,
            confidence=rec.confidence,
            asset=rec.asset,
            should_open_case=rec.should_open_case,
            case_id=rec.case_id,
            source=rec.source,
        )


# ── Paginated list wrapper ────────────────────────────────────────────────────

class FindingListResponse(BaseModel):
    items:  List[FindingListItem]
    total:  int
    limit:  int
    offset: int


# ── Full detail (single finding) ─────────────────────────────────────────────

class FindingDetailResponse(BaseModel):
    id:                   str
    title:                str
    severity:             str
    status:               str
    created_at:           str
    updated_at:           Optional[str]       = None
    closed_at:            Optional[str]       = None
    tenant_id:            str
    batch_hash:           str
    description:          str
    evidence:             List[Any]           = Field(default_factory=list)
    ttps:                 List[str]           = Field(default_factory=list)
    timestamp:            Optional[str]       = None
    confidence:           Optional[float]     = None
    risk_score:           Optional[float]     = None
    hypothesis:           Optional[str]       = None
    asset:                Optional[str]       = None
    environment:          Optional[str]       = None
    correlated_events:    Optional[List[str]] = None
    correlated_findings:  Optional[List[str]] = None
    triggered_policies:   Optional[List[str]] = None
    policy_signals:       Optional[List[Any]] = None
    recommended_actions:  Optional[List[str]] = None
    should_open_case:     bool                = False
    case_id:              Optional[str]       = None
    source:               Optional[str]       = None

    @classmethod
    def from_record(cls, rec: FindingRecord) -> "FindingDetailResponse":
        return cls(
            id=rec.id,
            title=rec.title,
            severity=rec.severity,
            status=rec.status,
            created_at=rec.created_at,
            updated_at=rec.updated_at,
            closed_at=rec.closed_at,
            tenant_id=rec.tenant_id,
            batch_hash=rec.batch_hash,
            description=rec.description,
            evidence=rec.evidence if isinstance(rec.evidence, list) else ([rec.evidence] if rec.evidence else []),
            ttps=rec.ttps if isinstance(rec.ttps, list) else ([rec.ttps] if rec.ttps else []),
            timestamp=rec.timestamp,
            confidence=rec.confidence,
            risk_score=rec.risk_score,
            hypothesis=rec.hypothesis,
            asset=rec.asset,
            environment=rec.environment,
            correlated_events=rec.correlated_events,
            correlated_findings=rec.correlated_findings,
            triggered_policies=rec.triggered_policies,
            policy_signals=rec.policy_signals,
            recommended_actions=rec.recommended_actions,
            should_open_case=rec.should_open_case,
            case_id=rec.case_id,
            source=rec.source,
        )


# ── Mutation request bodies ───────────────────────────────────────────────────

class UpdateStatusRequest(BaseModel):
    status: str = Field(..., pattern="^(open|investigating|resolved)$")


class LinkCaseRequest(BaseModel):
    case_id: str = Field(..., min_length=1)


# ── Bulk query body ───────────────────────────────────────────────────────────

class QueryFindingsRequest(BaseModel):
    severity:       Optional[str]   = None
    status:         Optional[str]   = Field(None, pattern="^(open|investigating|resolved)$")
    asset:          Optional[str]   = None
    tenant_id:      Optional[str]   = None
    has_case:       Optional[bool]  = None
    from_time:      Optional[str]   = None
    to_time:        Optional[str]   = None
    min_risk_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    limit:          int             = Field(50, ge=1, le=200)
    offset:         int             = Field(0, ge=0)
    sort_by:        Optional[str]   = Field(None, pattern="^(risk_score|timestamp)$")
