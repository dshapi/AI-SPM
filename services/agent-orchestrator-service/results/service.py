# results/service.py
"""
results/service.py
──────────────────
ResultsService: fetches events from DB and transforms them to SessionResults.

Caching strategy: (session_id → (event_count, SessionResults)) dict.
  - On each call, fetch the full event list to get the current count.
  - If count matches the cached entry, return the cached SessionResults.
  - If count differs (stream still growing), re-transform and update cache.
  - For terminal sessions (partial=False), count is stable → computed once.

Instance-level cache: inject a shared ResultsService via app.state in main.py
for cross-request caching. Per-request instantiation gives no cache benefit.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from models.event import EventRecord, EventRepository
from results.schemas import SessionResults
from results.transformers import transform_session_events

logger = logging.getLogger(__name__)

# Cache entry type alias
_CacheEntry = Tuple[int, SessionResults]


class ResultsService:
    """
    Fetches, transforms, and caches SessionResults per session.

    Share one instance across requests via app.state.results_service.
    """

    def __init__(self) -> None:
        self._cache: Dict[str, _CacheEntry] = {}

    async def get_results(
        self,
        session_id: str,
        event_repo: EventRepository,
    ) -> SessionResults:
        """
        Return SessionResults for the given session_id.

        Fetches events from DB to check the current event count.
        Returns cached result if count is unchanged; re-transforms otherwise.
        """
        records: List[EventRecord] = await event_repo.get_by_session_id(session_id)
        current_count = len(records)

        cached = self._cache.get(session_id)
        if cached is not None:
            cached_count, cached_result = cached
            if cached_count == current_count:
                logger.debug(
                    "results cache hit session=%s events=%d", session_id, current_count
                )
                return cached_result

        logger.debug(
            "results cache miss session=%s events=%d", session_id, current_count
        )

        event_dicts = _records_to_dicts(records)
        result = transform_session_events(event_dicts)
        self._cache[session_id] = (current_count, result)
        return result

    def invalidate(self, session_id: str) -> None:
        """Manually evict a session from the cache."""
        evicted = self._cache.pop(session_id, None)
        if evicted is not None:
            logger.debug("results cache evicted session=%s", session_id)


def _records_to_dicts(records: List[EventRecord]) -> List[Dict[str, Any]]:
    """Convert EventRecord objects to dicts for transform_session_events."""
    out = []
    for r in records:
        try:
            payload = json.loads(r.payload) if r.payload else {}
        except (json.JSONDecodeError, TypeError):
            payload = {}
        out.append({
            "event_type":     r.event_type,
            "session_id":     r.session_id,
            "correlation_id": "",      # not stored on EventRecord; unused by transformer
            "timestamp":      r.timestamp.isoformat() if r.timestamp else None,
            "step":           0,       # not stored on EventRecord; transformer uses 0 as default
            "status":         "ok",    # not stored on EventRecord; default for DB-sourced events
            "summary":        "",      # not stored on EventRecord; transformer skips empty
            "payload":        payload,
        })
    return out
