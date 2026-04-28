"""
threathunting_ai/event_adapter.py
───────────────────────────────────
Convert collector output into agent-compatible event dicts.

The event shape follows the same pattern as Kafka consumer events so the
existing hunt agent (run_hunt) can process them without modification.

All proactive events are tagged:
  source       = "threathunting_ai"
  is_proactive = True
  event_type   = "threathunting_scan"
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from config import TENANT_ID


def adapt_to_events(
    scan_type: str,
    data: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Convert a list of collector items into agent-compatible event dicts.

    Each item in data becomes one event.  Common ThreatHunting AI metadata
    is attached to all events.  Empty data → empty list (nothing to hunt on).

    Args:
        scan_type: The scan name from SCAN_REGISTRY (e.g. "exposed_credentials").
        data:      Raw output from the collector.

    Returns:
        List of event dicts ready for run_hunt().
    """
    if not data:
        return []

    # Map collector-emitted severity labels to numeric guard scores so the
    # downstream scorer.compute_risk_score() picks up the collector's intent
    # instead of flattening every anomaly to a single 0.65 baseline.
    _SEV_TO_SCORE = {
        "critical": 0.95,
        "high":     0.85,
        "medium":   0.55,
        "low":      0.30,
    }

    now = datetime.now(timezone.utc).isoformat()
    events = []
    for item in data:
        is_anomalous = bool(item.get("anomalous"))
        sev = str(item.get("severity") or "").lower()
        guard_score = _SEV_TO_SCORE.get(
            sev,
            0.65 if is_anomalous else 0.0,   # back-compat for collectors
                                             # that don't set severity yet
        )
        event = {
            # Routing / tagging
            "_topic":       f"cpm.{TENANT_ID}.threathunting_scan",
            "event_type":   "threathunting_scan",
            "scan_type":    scan_type,
            "source":       "threathunting_ai",
            "is_proactive": True,
            # Timing
            "timestamp":    now,
            "tenant_id":    TENANT_ID,
            # Payload — the raw collector item
            "data":         item,
            # Scoring hints for scorer.py.
            #   - guard_verdict "block" makes the event count toward
            #     frequency_factor (anomalous findings are already pre-filtered
            #     as significant — flag/allow under-weighted them).
            #   - risk_tier carries the collector's severity label so
            #     _extract_tier() can map it to its tier weight.
            "guard_verdict": "block" if is_anomalous else "allow",
            "guard_score":   guard_score,
            "risk_tier":     sev or ("high" if is_anomalous else ""),
        }
        events.append(event)

    return events
