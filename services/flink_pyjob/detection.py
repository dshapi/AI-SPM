"""
CEP alert-level cascade — pure functions, no Flink imports.

Source of truth for "given window/signal/drift state, what alert level
should this event produce?". Kept as pure functions so the cascade
can be unit-tested without a Flink runtime AND so any future shadow
run (e.g. testing a CEP rule rewrite) can reuse the same logic.

Thresholds: short=5 events / 120s, long=15 events / 3600s, drift=0.85.
Callers may inject overrides for testing or tenant-specific tuning.
"""
from __future__ import annotations

from typing import List, Mapping

from platform_shared.risk import is_critical_combination


# Defaults pinned here so unit tests are deterministic without dragging
# in platform_shared.config (which reads env vars). Production callers
# should pass settings.cep_short_threshold etc. explicitly.
_DEFAULT_SHORT_THRESHOLD = 5
_DEFAULT_LONG_THRESHOLD = 15
_DEFAULT_DRIFT_THRESHOLD = 0.85


def determine_alert_level(
    *,
    short_count: int,
    long_count: int,
    avg_drift: float,
    posture_trend: Mapping[str, object],
    all_signals: List[str],
    has_signals: bool,
    short_threshold: int = _DEFAULT_SHORT_THRESHOLD,
    long_threshold: int = _DEFAULT_LONG_THRESHOLD,
    drift_threshold: float = _DEFAULT_DRIFT_THRESHOLD,
) -> str:
    """
    Cascade is checked top-down; first match wins. Returns one of
    ``"critical"``, ``"high"``, ``"medium"``, ``"low"``, ``"ok"``.
    """
    if is_critical_combination(all_signals):
        return "critical"
    if short_count >= short_threshold and long_count >= long_threshold:
        return "critical"
    if short_count >= short_threshold:
        return "high"
    if long_count >= long_threshold:
        return "high"
    if avg_drift >= drift_threshold:
        return "medium"
    if (
        posture_trend.get("trend") == "increasing"
        and float(posture_trend.get("avg", 0.0)) > 0.50
    ):
        return "medium"
    if has_signals and len(all_signals) >= 3:
        return "low"
    return "ok"


def build_alert_payload(
    *,
    short_count: int,
    long_count: int,
    all_signals: List[str],
    ttps: List[str],
    critical_combo: bool,
    avg_drift: float,
    posture_trend: Mapping[str, object],
    posture_score: float,
    alert_level: str,
) -> dict:
    """
    Build the ``details`` dict written into the security_alert / audit
    event.
    """
    return {
        "short_window_count": short_count,
        "long_window_count": long_count,
        "session_signals": list(all_signals),
        "ttps": list(ttps),
        "critical_combo": critical_combo,
        "avg_intent_drift": round(avg_drift, 4),
        "posture_trend": dict(posture_trend),
        "posture_score": posture_score,
        "alert_level": alert_level,
    }
