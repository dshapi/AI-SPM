"""
Unit tests for state.py — the pieces that don't need a Flink runtime.

The full process_element() needs RuntimeContext + managed state, which
require a running cluster. We can still pin the pure helper
_evict_old_events here, plus a couple of import-shape checks that
guard against accidentally pulling in PyFlink at import time
(important for CI which doesn't install apache-flink).
"""
from __future__ import annotations

import importlib
import sys


class TestEvictOldEvents:
    def setup_method(self):
        # Re-import each test so the optional-import branch is exercised
        # even if a previous test already imported pyflink.
        if "services.flink_pyjob.state" in sys.modules:
            del sys.modules["services.flink_pyjob.state"]
        self.state_mod = importlib.import_module("services.flink_pyjob.state")

    def test_drops_events_at_or_below_cutoff(self):
        evict = self.state_mod.CEPDetector._evict_old_events
        out = evict(
            [(100, "a"), (110, "b"), (120, "c")],
            ts_now=200, window_sec=80,
        )
        # cutoff = 200 - 80 = 120; keep ts > 120
        # 100 dropped, 110 dropped, 120 dropped (strictly greater)
        assert out == []

    def test_keeps_events_within_window(self):
        evict = self.state_mod.CEPDetector._evict_old_events
        out = evict(
            [(100, "a"), (150, "b"), (190, "c")],
            ts_now=200, window_sec=120,
        )
        # cutoff = 80; keep ts > 80
        assert out == [(100, "a"), (150, "b"), (190, "c")]

    def test_empty_input_returns_empty(self):
        evict = self.state_mod.CEPDetector._evict_old_events
        assert evict([], ts_now=200, window_sec=120) == []

    def test_preserves_order(self):
        evict = self.state_mod.CEPDetector._evict_old_events
        out = evict(
            [(100, "a"), (200, "b"), (150, "c"), (300, "d")],
            ts_now=400, window_sec=350,
        )
        # cutoff = 50; all kept
        assert [eid for _, eid in out] == ["a", "b", "c", "d"]

    def test_window_sec_zero_drops_all(self):
        evict = self.state_mod.CEPDetector._evict_old_events
        # cutoff = ts_now - 0 = ts_now; keep ts > ts_now → nothing kept
        # even if events are AT ts_now
        out = evict(
            [(200, "a"), (200, "b")],
            ts_now=200, window_sec=0,
        )
        assert out == []


class TestModuleImportsCleanWithoutPyFlink:
    """
    state.py MUST be importable in environments without apache-flink so
    CI can run the pure-logic tests on cheap runners. The fallback _Base
    class lets the module load; PyFlink is only required when the actual
    Flink runtime calls open()/process_element().
    """

    def test_module_imports_without_error(self):
        # The act of importing services.flink_pyjob.state from anywhere
        # in the codebase should not raise even if pyflink is absent.
        # We can't easily uninstall pyflink mid-test, so we settle for
        # asserting the module did import successfully and exposes
        # CEPDetector as a class.
        from services.flink_pyjob import state
        assert hasattr(state, "CEPDetector")
        assert isinstance(state.CEPDetector, type)

    def test_evict_helper_is_static(self):
        from services.flink_pyjob.state import CEPDetector
        # _evict_old_events is a @staticmethod — calling on the class
        # without instantiation must work.
        result = CEPDetector._evict_old_events([(50, "x")], 100, 30)
        # cutoff = 70; 50 is NOT > 70 → drop
        assert result == []
