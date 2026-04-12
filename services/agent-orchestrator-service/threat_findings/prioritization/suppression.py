"""
threat_findings/prioritization/suppression.py
──────────────────────────────────────────────
Noise suppression — mark a finding as suppressed when priority_score < threshold.

should_suppress(priority_score) → bool

No DB, no network, no LLM — pure deterministic function.
"""
from __future__ import annotations

from typing import Optional

SUPPRESSION_THRESHOLD = 0.30


def should_suppress(priority_score: Optional[float]) -> bool:
    """
    Return True when a finding's priority_score is too low to be actionable.

    Args:
        priority_score: Computed score in [0.0, 1.0], or None if not yet ranked.

    Returns:
        True  → suppress (hide from default API results)
        False → keep (include in default API results)
    """
    if priority_score is None:
        return True
    return priority_score < SUPPRESSION_THRESHOLD
