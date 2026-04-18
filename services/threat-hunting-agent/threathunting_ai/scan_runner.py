"""
threathunting_ai/scan_runner.py
────────────────────────────────
Scan runner: orchestrates collect → adapt → hunt → persist for each scan type.

Public API:
  run_scan(scan_type, hunt_agent, persist_fn)
  run_all_scans(hunt_agent, persist_fn)
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from config import TENANT_ID
from threathunting_ai.event_adapter import adapt_to_events

logger = logging.getLogger(__name__)

_FALLBACK_TITLE = "Hunt completed — no finding produced"


def run_scan(
    scan_type: str,
    hunt_agent: Callable[[str, List[Dict[str, Any]]], dict],
    persist_fn: Optional[Callable[[str, dict], None]],
) -> None:
    """
    Run one proactive scan end-to-end:
      1. Call the collector (deterministic, read-only, no LLM)
      2. Adapt results to event dicts via event_adapter
      3. If events exist: call hunt_agent (LLM analysis via run_hunt)
      4. Stamp source = "threathunting_ai" and is_proactive = True
      5. Persist via persist_fn (skip fallback / no-op findings)
    """
    from threathunting_ai.scan_registry import SCAN_REGISTRY

    defn = SCAN_REGISTRY.get(scan_type)
    if defn is None:
        logger.warning("run_scan: unknown scan_type=%r — skipping", scan_type)
        return

    # ── 1. Collect ───────────────────────────────────────────────────────────
    try:
        data = defn.collector()
    except Exception as exc:
        logger.exception("run_scan: collector failed scan=%s: %s", scan_type, exc)
        return

    logger.debug("run_scan: scan=%s collector_items=%d", scan_type, len(data))

    # ── 2. Adapt to events ───────────────────────────────────────────────────
    events = adapt_to_events(scan_type, data)
    if not events:
        logger.debug("run_scan: scan=%s produced no events — skipping hunt", scan_type)
        return

    # ── 3. Hunt (LLM) ────────────────────────────────────────────────────────
    try:
        finding = hunt_agent(TENANT_ID, events)
    except Exception as exc:
        logger.exception("run_scan: hunt_agent failed scan=%s: %s", scan_type, exc)
        return

    if not isinstance(finding, dict):
        logger.warning("run_scan: hunt_agent returned non-dict scan=%s type=%s",
                       scan_type, type(finding))
        return

    # ── 4. Skip fallback placeholder ─────────────────────────────────────────
    if finding.get("title", "") == _FALLBACK_TITLE:
        logger.debug("run_scan: fallback finding scan=%s — not persisting", scan_type)
        return

    # ── 5. Stamp proactive provenance ────────────────────────────────────────
    finding["source"]       = "threathunting_ai"
    finding["is_proactive"] = True

    logger.info(
        "run_scan: scan=%s title=%r severity=%s should_open_case=%s",
        scan_type,
        finding.get("title"),
        finding.get("severity"),
        finding.get("should_open_case"),
    )

    # ── 6. Persist ───────────────────────────────────────────────────────────
    if persist_fn is not None:
        try:
            persist_fn(TENANT_ID, finding)
        except Exception as exc:
            logger.exception("run_scan: persist_fn failed scan=%s: %s", scan_type, exc)


def run_all_scans(
    hunt_agent: Callable[[str, List[Dict[str, Any]]], dict],
    persist_fn: Optional[Callable[[str, dict], None]],
) -> None:
    """
    Iterate the full SCAN_REGISTRY and run every scan in order.
    Individual scan failures are caught and logged; never propagates.
    """
    from threathunting_ai.scan_registry import SCAN_NAMES
    logger.info("run_all_scans: starting cycle scan_count=%d", len(SCAN_NAMES))
    for scan_type in SCAN_NAMES:
        try:
            run_scan(scan_type, hunt_agent, persist_fn)
        except Exception as exc:
            logger.exception("run_all_scans: unhandled error scan=%s: %s", scan_type, exc)
    logger.info("run_all_scans: cycle complete")
