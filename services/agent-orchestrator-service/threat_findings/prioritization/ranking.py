"""
threat_findings/prioritization/ranking.py
──────────────────────────────────────────
Compute a deterministic priority_score in [0.0, 1.0].

Formula:
  priority_score = risk_score*0.4 + confidence*0.2 + severity_weight*0.2
                 + recency_score*0.1 + frequency_score*0.1

No DB, no network, no LLM — pure deterministic function.
"""
from __future__ import annotations

from typing import Optional

_SEVERITY_WEIGHTS = {
    "critical": 1.00,
    "high":     0.75,
    "medium":   0.50,
    "low":      0.25,
}


def _recency_score(age_hours: float) -> float:
    if age_hours < 1:
        return 1.0
    if age_hours < 24:
        return 0.8
    if age_hours < 168:   # 7 days
        return 0.5
    return 0.2


def _frequency_score(occurrence_count: int) -> float:
    return min(occurrence_count / 10.0, 1.0)


def compute_priority_score(
    risk_score:       Optional[float],
    confidence:       Optional[float],
    severity:         str,
    age_hours:        float,
    occurrence_count: int,
) -> float:
    """
    Compute priority_score in [0.0, 1.0].

    Args:
        risk_score:       0.0–1.0 (None treated as 0.0).
        confidence:       0.0–1.0 (None treated as 0.0).
        severity:         "low" | "medium" | "high" | "critical".
        age_hours:        How many hours since the finding was first created.
        occurrence_count: How many times this dedup key has been seen.

    Returns:
        Clamped float in [0.0, 1.0].
    """
    rs  = float(risk_score  or 0.0)
    con = float(confidence  or 0.0)
    sw  = _SEVERITY_WEIGHTS.get(severity, 0.25)
    rec = _recency_score(age_hours)
    frq = _frequency_score(occurrence_count)

    raw = rs * 0.4 + con * 0.2 + sw * 0.2 + rec * 0.1 + frq * 0.1
    return max(0.0, min(1.0, raw))
