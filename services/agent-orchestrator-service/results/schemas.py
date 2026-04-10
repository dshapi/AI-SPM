from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class TraceStep(BaseModel):
    step: int
    event_type: str
    status: str
    summary: str
    timestamp: datetime
    latency_ms: Optional[int] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class RiskAnalysis(BaseModel):
    score: float = 0.0
    tier: str = "unknown"
    signals: List[str] = Field(default_factory=list)
    behavioral_risk: Optional[float] = None
    anomaly_flags: List[str] = Field(default_factory=list)


class PolicyImpact(BaseModel):
    decision: str = "unknown"
    reason: str = ""
    policy_version: str = ""
    risk_score_at_decision: Optional[float] = None


class OutputSummary(BaseModel):
    verdict: Optional[str] = None
    pii_types: List[str] = Field(default_factory=list)
    secret_types: List[str] = Field(default_factory=list)
    scan_notes: List[str] = Field(default_factory=list)
    llm_model: Optional[str] = None
    response_length: Optional[int] = None
    latency_ms: Optional[int] = None


class RecommendationItem(BaseModel):
    id: str
    priority: str          # urgent | high | medium | low
    title: str
    detail: str
    action: str


class SessionResultsMeta(BaseModel):
    session_id: str
    agent_id: Optional[str] = None
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event_count: int = 0
    partial: bool = False   # True when no terminal event has arrived yet


class SessionResults(BaseModel):
    meta: SessionResultsMeta
    status: str = "unknown"      # active | blocked | completed | failed
    decision: str = "unknown"    # allow | block | escalate | unknown
    decision_trace: List[TraceStep] = Field(default_factory=list)
    risk: RiskAnalysis = Field(default_factory=RiskAnalysis)
    policy: PolicyImpact = Field(default_factory=PolicyImpact)
    output: OutputSummary = Field(default_factory=OutputSummary)
    recommendations: List[RecommendationItem] = Field(default_factory=list)
