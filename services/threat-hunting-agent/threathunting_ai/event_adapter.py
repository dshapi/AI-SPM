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

    now = datetime.now(timezone.utc).isoformat()
    events = []
    for item in data:
        # Derive a guard signal so scorer.py can weight events appropriately.
        # Anomalous items get a "flag" verdict; routine status items get "allow".
        is_anomalous = bool(item.get("anomalous"))
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
            # Scoring hints for scorer.py (used by compute_risk_score / compute_confidence)
            "guard_verdict": "flag" if is_anomalous else "allow",
            "guard_score":   0.65 if is_anomalous else 0.0,
        }
        events.append(event)

    return events
