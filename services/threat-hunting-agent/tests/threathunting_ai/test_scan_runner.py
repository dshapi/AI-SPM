"""
Tests for threathunting_ai/event_adapter.py and threathunting_ai/scan_runner.py
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from threathunting_ai.event_adapter import adapt_to_events
from threathunting_ai.scan_runner import run_scan, run_all_scans
from threathunting_ai.scan_registry import SCAN_NAMES


# ── adapt_to_events ──────────────────────────────────────────────────────────

class TestAdaptToEvents:
    def test_returns_list(self):
        data = [{"type": "secret_exposure", "key_name": "api_key:prod"}]
        events = adapt_to_events("exposed_credentials", data)
        assert isinstance(events, list)
        assert len(events) == 1

    def test_event_shape(self):
        data = [{"type": "secret_exposure", "key_name": "token:abc"}]
        events = adapt_to_events("exposed_credentials", data)
        e = events[0]
        assert e["event_type"]   == "threathunting_scan"
        assert e["scan_type"]    == "exposed_credentials"
        assert e["source"]       == "threathunting_ai"
        assert e["is_proactive"] is True
        assert "timestamp" in e
        assert "tenant_id" in e
        assert "data" in e

    def test_empty_data_returns_empty(self):
        events = adapt_to_events("unused_open_ports", [])
        assert events == []

    def test_topic_tag(self):
        data = [{"type": "port_status", "port": 9999, "reachable": True}]
        events = adapt_to_events("unused_open_ports", data)
        assert events[0]["_topic"] == "cpm.t1.threathunting_scan"

    def test_anomalous_item_gets_flag_verdict(self):
        data = [{"type": "port_status", "anomalous": True}]
        events = adapt_to_events("unused_open_ports", data)
        assert events[0]["guard_verdict"] == "flag"

    def test_non_anomalous_item_gets_allow_verdict(self):
        data = [{"type": "port_status", "anomalous": False}]
        events = adapt_to_events("unused_open_ports", data)
        assert events[0]["guard_verdict"] == "allow"


# ── run_scan ─────────────────────────────────────────────────────────────────

class TestRunScan:
    def _make_hunt(self, title="Real Finding"):
        calls = []

        def hunt_agent(tenant_id, events):
            calls.append((tenant_id, events))
            return {
                "finding_id": "f1",
                "title": title,
                "severity": "medium",
                "should_open_case": False,
                "source": "threat_hunt",   # agent returns this; runner should override
            }

        return hunt_agent, calls

    def test_calls_hunt_agent_with_tenant(self):
        hunt_agent, calls = self._make_hunt()
        persisted = []
        mock_defn = MagicMock()
        mock_defn.collector.return_value = [{"type": "secret_exposure"}]

        with patch("threathunting_ai.scan_registry.SCAN_REGISTRY",
                   {"exposed_credentials": mock_defn}):
            run_scan("exposed_credentials", hunt_agent, lambda t, f: persisted.append((t, f)))

        assert len(calls) == 1
        assert calls[0][0] == "t1"

    def test_stamps_source_threathunting_ai(self):
        hunt_agent, _ = self._make_hunt()
        persisted = []
        mock_defn = MagicMock()
        mock_defn.collector.return_value = [{"type": "secret_exposure"}]

        with patch("threathunting_ai.scan_registry.SCAN_REGISTRY",
                   {"exposed_credentials": mock_defn}):
            run_scan("exposed_credentials", hunt_agent,
                     lambda t, f: persisted.append((t, f)))

        assert len(persisted) == 1
        assert persisted[0][1]["source"]       == "threathunting_ai"
        assert persisted[0][1]["is_proactive"] is True

    def test_skips_persist_for_fallback_finding(self):
        hunt_agent, _ = self._make_hunt(title="Hunt completed — no finding produced")
        persisted = []
        mock_defn = MagicMock()
        mock_defn.collector.return_value = [{"type": "secret_exposure"}]

        with patch("threathunting_ai.scan_registry.SCAN_REGISTRY",
                   {"exposed_credentials": mock_defn}):
            run_scan("exposed_credentials", hunt_agent,
                     lambda t, f: persisted.append((t, f)))

        assert persisted == []

    def test_empty_collector_skips_hunt(self):
        calls = []
        hunt_agent = lambda t, e: calls.append(e) or {}
        mock_defn = MagicMock()
        mock_defn.collector.return_value = []

        with patch("threathunting_ai.scan_registry.SCAN_REGISTRY",
                   {"unused_open_ports": mock_defn}):
            run_scan("unused_open_ports", hunt_agent, lambda t, f: None)

        assert calls == []

    def test_collector_exception_does_not_crash(self):
        def bad_collector():
            raise RuntimeError("collector exploded")

        mock_defn = MagicMock()
        mock_defn.collector.side_effect = RuntimeError("collector exploded")

        with patch("threathunting_ai.scan_registry.SCAN_REGISTRY",
                   {"exposed_credentials": mock_defn}):
            run_scan("exposed_credentials", lambda t, e: {}, lambda t, f: None)

    def test_hunt_exception_does_not_crash(self):
        def bad_hunt(t, e):
            raise RuntimeError("hunt failed")

        mock_defn = MagicMock()
        mock_defn.collector.return_value = [{"type": "x"}]

        with patch("threathunting_ai.scan_registry.SCAN_REGISTRY",
                   {"exposed_credentials": mock_defn}):
            run_scan("exposed_credentials", bad_hunt, lambda t, f: None)

    def test_unknown_scan_type_does_not_crash(self):
        run_scan("nonexistent_scan", lambda t, e: {}, lambda t, f: None)


# ── run_all_scans ────────────────────────────────────────────────────────────

class TestRunAllScans:
    def test_calls_run_scan_for_each_registry_entry(self):
        called = []

        def fake_run_scan(scan_type, hunt_agent, persist_fn):
            called.append(scan_type)

        with patch("threathunting_ai.scan_runner.run_scan", side_effect=fake_run_scan):
            run_all_scans(hunt_agent=MagicMock(), persist_fn=MagicMock())

        assert set(called) == set(SCAN_NAMES)

    def test_individual_scan_exception_does_not_stop_others(self):
        called = []

        def fake_run_scan(scan_type, hunt_agent, persist_fn):
            called.append(scan_type)
            if scan_type == SCAN_NAMES[0]:
                raise RuntimeError("first scan exploded")

        with patch("threathunting_ai.scan_runner.run_scan", side_effect=fake_run_scan):
            run_all_scans(hunt_agent=MagicMock(), persist_fn=MagicMock())

        # All scans should have been attempted
        assert set(called) == set(SCAN_NAMES)
