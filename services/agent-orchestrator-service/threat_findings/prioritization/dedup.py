"""
threat_findings/prioritization/dedup.py
────────────────────────────────────────
Deduplication key computation and occurrence tracking.

compute_dedup_key(title, asset, scan_type, evidence) → 64-char hex SHA-256
merge_occurrence(existing_first_seen, now_iso, existing_count) → dict

No DB, no network, no LLM — pure deterministic functions.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, List, Optional


def _normalise_evidence(evidence: List[Any]) -> str:
    """Stable JSON representation of evidence regardless of key order."""
    return json.dumps(evidence, sort_keys=True, default=str)


def compute_dedup_key(
    title: str,
    asset: Optional[str],
    scan_type: Optional[str],
    evidence: List[Any],
) -> str:
    """
    Compute a stable 64-char hex SHA-256 deduplication key.

    Two findings with the same (title, asset, scan_type, normalised evidence)
    will produce an identical key regardless of when they were created.
    """
    canonical = json.dumps(
        {
            "title":      title,
            "asset":      asset or "",
            "scan_type":  scan_type or "",
            "evidence":   json.loads(_normalise_evidence(evidence)),
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def merge_occurrence(
    existing_first_seen: Optional[str],
    now_iso: str,
    existing_count: int,
) -> dict:
    """
    Compute updated occurrence tracking fields.

    Args:
        existing_first_seen: ISO-8601 timestamp from a prior occurrence, or None for first time.
        now_iso:             ISO-8601 timestamp for the current occurrence.
        existing_count:      Current occurrence_count (0 if first time).

    Returns:
        dict with keys: first_seen, last_seen, occurrence_count
    """
    first_seen = existing_first_seen if existing_first_seen else now_iso
    return {
        "first_seen":       first_seen,
        "last_seen":        now_iso,
        "occurrence_count": existing_count + 1,
    }
