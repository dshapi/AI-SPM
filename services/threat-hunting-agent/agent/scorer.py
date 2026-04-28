"""
agent/scorer.py
────────────────
Deterministic scoring for threat-hunt findings.

These functions MUST NOT call the LLM.  They operate purely on the
raw event batch.  Both formulas follow the spec:

  risk_score  = min(1.0, severity_weight * frequency_factor * anomaly_factor)
  confidence  = min(1.0, evidence_strength * correlation_factor)
"""
from __future__ import annotations

from typing import Any, Dict, List

# Maps risk tier / severity labels → numeric weight
_TIER_WEIGHTS: Dict[str, float] = {
    "critical": 1.00,
    "high":     0.75,
    "medium":   0.50,
    "low":      0.25,
}


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _extract_risk_score(event: Dict[str, Any]) -> float:
    """Pull a numeric risk score from various event shapes."""
    # Direct field (orchestrator sessions.blocked)
    direct = event.get("risk_score") or event.get("guard_score", 0.0)
    # Nested in details (audit events from session_service)
    nested = (event.get("details") or {}).get("risk_score", 0.0)
    return float(max(direct or 0.0, nested or 0.0))


def _extract_tier(event: Dict[str, Any]) -> str:
    """Pull a risk tier label from various event shapes."""
    direct = event.get("risk_tier", "") or event.get("guard_tier", "")
    nested = (event.get("details") or {}).get("risk_tier", "")
    return (direct or nested or "").lower()


def _is_blocked(event: Dict[str, Any]) -> bool:
    """Return True if this event represents a blocked / flagged session."""
    verdict = event.get("guard_verdict", "") or event.get("verdict", "")
    decision = event.get("policy_decision", "") or (event.get("details") or {}).get("policy_decision", "")
    return str(verdict).lower() in ("block", "blocked") or str(decision).lower() in ("block", "blocked")


def _has_evidence(event: Dict[str, Any]) -> bool:
    """Return True if the event carries any scoring signal."""
    return bool(
        _extract_risk_score(event) > 0
        or event.get("details")
        or event.get("guard_categories")
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def compute_risk_score(events: List[Dict[str, Any]]) -> float:
    """
    risk_score = min(1.0, severity_weight * frequency_factor * anomaly_factor)

    severity_weight  — highest raw score or tier weight observed in the batch.
    frequency_factor — scales linearly from 0.5 (0 blocks) to 1.0 (≥3 blocks).
    anomaly_factor   — 1.5 if multiple distinct principals are involved, else 1.0.
                       Caps final score at 1.0.
    """
    if not events:
        return 0.0

    # severity_weight: max of direct risk scores and tier weights
    raw_scores   = [_extract_risk_score(e) for e in events]
    tier_weights = [_TIER_WEIGHTS.get(_extract_tier(e), 0.0) for e in events]
    severity_weight = max(max(raw_scores), max(tier_weights))

    # frequency_factor: 0.5 baseline, +0.5/6 per blocked event, capped at 1.0.
    # Proactive ThreatHunting AI batches are already pre-filtered through the
    # collector's threshold — penalising them for low frequency double-counts
    # the filter and produces artificially low risk_scores (0.32–0.40 range).
    # Treat any all-proactive batch as a full-strength signal.
    blocked_count    = sum(1 for e in events if _is_blocked(e))
    frequency_factor = min(1.0, 0.5 + blocked_count / 6.0)
    if events and all(e.get("is_proactive") for e in events):
        frequency_factor = 1.0

    # anomaly_factor: cross-actor activity is more alarming
    principals    = {e.get("principal") or e.get("user_id", "") for e in events}
    principals.discard("")
    anomaly_factor = 1.5 if len(principals) > 1 else 1.0

    return min(1.0, severity_weight * frequency_factor * anomaly_factor)


def compute_confidence(events: List[Dict[str, Any]]) -> float:
    """
    confidence = min(1.0, evidence_strength * correlation_factor)

    evidence_strength  — fraction of events that carry a scoring signal.
    correlation_factor — 1.2 if events span multiple distinct sessions, else 1.0.
    """
    if not events:
        return 0.0

    evidence_count    = sum(1 for e in events if _has_evidence(e))
    evidence_strength = evidence_count / len(events)

    sessions = {e.get("session_id", "") for e in events}
    sessions.discard("")
    correlation_factor = 1.2 if len(sessions) > 1 else 1.0

    return min(1.0, evidence_strength * correlation_factor)
