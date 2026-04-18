"""
threathunting_ai/scheduler.py
──────────────────────────────
Scheduler for the ThreatHunting AI continuous scan loop.

Fires run_all_scans() every scan_interval_sec seconds in a daemon thread,
without blocking the FastAPI event loop.

Interface:
  start() — arm the first timer; scans begin after one full interval
  stop()  — cancel the pending timer and prevent re-arming
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional

from threathunting_ai.scan_runner import run_all_scans

logger = logging.getLogger(__name__)


class ThreatHuntingAIScheduler:
    """
    Fires run_all_scans() every scan_interval_sec seconds.

    Args:
        hunt_agent:        Callable(tenant_id, events) → dict
        persist_fn:        Callable(tenant_id, finding_dict) → None
        scan_interval_sec: Seconds between full scan cycles (default 300).
    """

    def __init__(
        self,
        hunt_agent: Callable[[str, List[Dict[str, Any]]], dict],
        persist_fn: Optional[Callable[[str, dict], None]],
        scan_interval_sec: int = 300,
    ) -> None:
        self._hunt_agent        = hunt_agent
        self._persist_fn        = persist_fn
        self._scan_interval_sec = scan_interval_sec

        self._stop_event = threading.Event()
        self._timer: Optional[threading.Timer] = None

    # ── Lifecycle ────────────────────────────────────────────────────────

    def start(self) -> None:
        """Arm the first timer. First scan fires after one full interval."""
        logger.info(
            "ThreatHuntingAI scheduler starting: interval=%ds",
            self._scan_interval_sec,
        )
        self._schedule()

    def stop(self) -> None:
        """Cancel the pending timer. No-op if not started or already stopped."""
        logger.info("ThreatHuntingAI scheduler stopping")
        self._stop_event.set()
        if self._timer is not None:
            self._timer.cancel()
        logger.info("ThreatHuntingAI scheduler stopped")

    # ── Internal ─────────────────────────────────────────────────────────

    def _schedule(self) -> None:
        """Arm a one-shot timer. Does nothing if stop() was already called."""
        if self._stop_event.is_set():
            return
        self._timer = threading.Timer(self._scan_interval_sec, self._fire)
        self._timer.daemon = True
        self._timer.start()

    def _fire(self) -> None:
        """Run all scans, then re-arm the timer (unless stopped)."""
        try:
            run_all_scans(
                hunt_agent=self._hunt_agent,
                persist_fn=self._persist_fn,
            )
        except Exception as exc:
            logger.exception(
                "ThreatHuntingAI scheduler: unhandled error in scan cycle: %s", exc
            )
        finally:
            self._schedule()
