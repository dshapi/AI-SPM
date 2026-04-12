"""
threat_findings/prioritization/grouping.py
──────────────────────────────────────────
Compute a stable group_id that clusters findings by (asset, scan_type, hour bucket).

compute_group_id(asset, scan_type, created_at_iso) → 64-char hex SHA-256

No DB, no network, no LLM — pure deterministic function.
"""
from __future__ import annotations

import hashlib
import json
from typing import Optional


def _hour_bucket(iso_ts: str) -> str:
    """
    Truncate an ISO-8601 timestamp to the nearest hour.
    Works with or without timezone offset.
    Example: "2026-01-01T10:45:00+00:00" → "2026-01-01T10"
    """
    return iso_ts[:13] if iso_ts else "unknown"


def compute_group_id(
    asset: Optional[str],
    scan_type: Optional[str],
    created_at_iso: str,
) -> str:
    """
    Compute a stable 64-char hex SHA-256 group identifier.

    Findings with the same asset, scan_type, and creation hour will share
    a group_id, making it easy to cluster related alerts in the UI.
    """
    key = json.dumps(
        {
            "asset":     asset or "",
            "scan_type": scan_type or "",
            "bucket":    _hour_bucket(created_at_iso),
        },
        sort_keys=True,
    )
    return hashlib.sha256(key.encode()).hexdigest()
