"""
threat_findings/prioritization/engine.py
──────────────────────────────────────────
Orchestrates: dedup → group → rank → suppress.

Usage (from service.py):
    from threat_findings.prioritization.engine import PrioritizationEngine

    async def _lookup_prior(dedup_key: str):
        row = await repo.get_by_dedup_key(dedup_key)
        if row:
            return {"first_seen": row.first_seen, "occurrence_count": row.occurrence_count}
        return None

    rec = await PrioritizationEngine.run(rec, _lookup_prior)

The engine mutates FindingRecord fields in-place and returns the same object.
No DB writes happen here — the caller (service.py) is responsible for persistence.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from threat_findings.prioritization.dedup import compute_dedup_key, merge_occurrence
from threat_findings.prioritization.grouping import compute_group_id
from threat_findings.prioritization.ranking import compute_priority_score
from threat_findings.prioritization.suppression import should_suppress
from threat_findings.schemas import FindingRecord

logger = logging.getLogger(__name__)

LookupFn = Callable[[str], Awaitable[Optional[Dict[str, Any]]]]


class PrioritizationEngine:
    @staticmethod
    async def run(rec: FindingRecord, lookup_fn: LookupFn) -> FindingRecord:
        """
        Enrich a FindingRecord with prioritization metadata.

        Steps:
          1. Compute dedup_key from (title, asset, scan_type, evidence).
          2. Look up prior occurrence via lookup_fn(dedup_key).
          3. Merge occurrence tracking (first_seen, last_seen, occurrence_count).
          4. Compute group_id from (asset, scan_type, created_at hour bucket).
          5. Compute priority_score using the ranking formula.
          6. Set suppressed flag.

        Args:
            rec:       Partially-populated FindingRecord (pre-insert).
            lookup_fn: Async callable returning prior occurrence metadata or None.

        Returns:
            The same FindingRecord with prioritization fields set.
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        # ── 1. Dedup key ────────────────────────────────────────────────────
        # Use triggered_policies[0] as scan_type proxy; fall back to source.
        # Explicit len-check avoids empty-list truthiness footgun.
        scan_type = (
            rec.triggered_policies[0]
            if rec.triggered_policies and len(rec.triggered_policies) > 0
            else (rec.source or "")
        )
        rec.dedup_key = compute_dedup_key(rec.title, rec.asset, scan_type, rec.evidence)

        # ── 2. Look up prior occurrence ─────────────────────────────────────
        prior = None
        try:
            prior = await lookup_fn(rec.dedup_key)
        except Exception as exc:
            logger.warning("PrioritizationEngine: lookup_fn failed: %s", exc)

        existing_first_seen = prior["first_seen"]       if prior else None
        existing_count      = prior["occurrence_count"] if prior else 0

        # ── 3. Merge occurrence tracking ────────────────────────────────────
        occ = merge_occurrence(existing_first_seen, now_iso, existing_count)
        rec.first_seen       = occ["first_seen"]
        rec.last_seen        = occ["last_seen"]
        rec.occurrence_count = occ["occurrence_count"]

        # ── 4. Group ID ──────────────────────────────────────────────────────
        rec.group_id   = compute_group_id(rec.asset, scan_type, rec.created_at)
        rec.group_size = 1  # Engine sets to 1; caller may update after counting siblings.

        # ── 5. Priority score ────────────────────────────────────────────────
        try:
            created = datetime.fromisoformat(rec.created_at)
            now_dt  = datetime.now(timezone.utc)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_hours = (now_dt - created).total_seconds() / 3600.0
        except Exception:
            # Unparseable created_at — default to 24 h (neutral recency_score=0.8)
            # rather than 0 h which would artificially inflate priority.
            logger.warning(
                "PrioritizationEngine: unparseable created_at=%r — defaulting age_hours=24",
                rec.created_at,
            )
            age_hours = 24.0

        rec.priority_score = compute_priority_score(
            risk_score=rec.risk_score,
            confidence=rec.confidence,
            severity=rec.severity,
            age_hours=age_hours,
            occurrence_count=rec.occurrence_count,
        )

        # ── 6. Suppress ──────────────────────────────────────────────────────
        rec.suppressed = should_suppress(rec.priority_score)

        logger.debug(
            "PrioritizationEngine: id=%s dedup_key=%s priority=%.3f suppressed=%s",
            rec.id, rec.dedup_key[:12], rec.priority_score, rec.suppressed,
        )
        return rec
