"""
agent/finding.py
─────────────────
Pydantic models for structured threat-hunt findings.

The Finding schema is the canonical output of run_hunt().
All fields are deterministically computed except those in the
LLM-controlled subset (title, hypothesis, severity, evidence, etc.).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Literal

from pydantic import BaseModel, Field


class PolicySignal(BaseModel):
    """A signal that a policy may be misconfigured or have a gap."""
    type: Literal["false_negative_candidate", "noisy_rule", "gap_detected"]
    policy: str
    confidence: float = Field(ge=0.0, le=1.0)


class Finding(BaseModel):
    """
    Structured threat-hunt finding.  Always returned by run_hunt().
    Deterministic fields (risk_score, confidence) are computed by scorer.py.
    LLM-controlled fields (title, hypothesis, severity, evidence, …) come
    from the parsed agent output via parser.py.
    """
    # Identity
    finding_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # Scores — deterministic (never from LLM)
    severity: Literal["low", "medium", "high", "critical"]
    confidence: float = Field(ge=0.0, le=1.0)
    risk_score: float = Field(ge=0.0, le=1.0)

    # LLM narrative
    title: str
    hypothesis: str

    # Context
    asset: str = "Threat Hunting AI Agent"
    environment: str = "production"
    source: str = "threat_hunt"

    # Evidence lists
    evidence: List[str] = Field(default_factory=list)
    correlated_events: List[str] = Field(default_factory=list)
    correlated_findings: List[str] = Field(default_factory=list)
    triggered_policies: List[str] = Field(default_factory=list)
    policy_signals: List[PolicySignal] = Field(default_factory=list)

    # Decisions
    recommended_actions: List[str] = Field(default_factory=list)
    should_open_case: bool = False


def safe_fallback_finding(tenant_id: str, event_count: int) -> dict:
    """
    Return a minimal safe Finding dict when agent invocation or parsing fails.
    should_open_case is always False in fallback — no false positives.
    """
    return Finding(
        severity="low",
        confidence=0.0,
        risk_score=0.0,
        title="Hunt completed — no finding produced",
        hypothesis=(
            f"Agent analysis of {event_count} event(s) for tenant '{tenant_id}' "
            "did not produce a parseable finding. Manual review may be required."
        ),
        should_open_case=False,
    ).model_dump()
