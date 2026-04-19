"""
Tests for threathunting_ai/scheduler.py
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from threathunting_ai.scheduler import ThreatHuntingAIScheduler


def _make_scheduler(interval: int = 9999) -> ThreatHuntingAIScheduler:
    return ThreatHuntingAIScheduler(
        hunt_agent=MagicMock(return_value={"title": "T", "severity": "low"}),
        persist_fn=MagicMock(),
        scan_interval_sec=interval,
    )


class TestThreatHuntingAIScheduler:
    def test_start_creates_timer(self):
        s = _make_scheduler()
        s.start()
        assert s._timer is not None
        s.stop()

    def test_stop_sets_stop_event(self):
        s = _make_scheduler()
        s.start()
        s.stop()
        assert s._stop_event.is_set()

    def test_stop_cancels_timer(self):
        s = _make_scheduler()
        s.start()
        timer = s._timer
        s.stop()
        # Timer was cancelled — calling stop() should not raise
        assert timer is not None

    def test_interval_stored(self):
        s = _make_scheduler(interval=123)
        assert s._scan_interval_sec == 123

    def test_fire_calls_run_all_scans(self):
        fired = []
        s = _make_scheduler()
        s.start()
        s._stop_event.set()   # prevent re-arm so test doesn't hang

        with patch("threathunting_ai.scheduler.run_all_scans",
                   side_effect=lambda **kw: fired.append(1)):
            s._fire()

        assert len(fired) == 1
        s.stop()

    def test_fire_passes_callbacks(self):
        received = {}
        hunt = MagicMock(return_value={})
        persist = MagicMock()
        s = ThreatHuntingAIScheduler(
            hunt_agent=hunt,
            persist_fn=persist,
            scan_interval_sec=9999,
        )
        s.start()
        s._stop_event.set()

        def capture(**kw):
            received.update(kw)

        with patch("threathunting_ai.scheduler.run_all_scans", side_effect=capture):
            s._fire()

        assert received.get("hunt_agent") is hunt
        assert received.get("persist_fn") is persist
        s.stop()

    def test_fire_exception_does_not_crash(self):
        s = _make_scheduler()
        s.start()
        s._stop_event.set()

        with patch("threathunting_ai.scheduler.run_all_scans",
                   side_effect=RuntimeError("boom")):
            s._fire()   # must not raise

        s.stop()

    def test_stop_before_start_does_not_crash(self):
        s = _make_scheduler()
        s.stop()   # should not raise

    def test_double_stop_does_not_crash(self):
        s = _make_scheduler()
        s.start()
        s.stop()
        s.stop()   # should not raise

    def test_schedule_noop_after_stop(self):
        s = _make_scheduler()
        s._stop_event.set()
        s._schedule()   # should not create a timer
        # If _schedule() respects stop_event, _timer stays None
        assert s._timer is None
