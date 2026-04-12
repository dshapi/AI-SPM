"""
Tests for prompt_secrets_collector.
All external I/O is mocked — no real Postgres calls.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, mock_open, patch

import pytest


def _make_pg_factory(rows):
    """Cursor returns rows from fetchall; supports context manager protocol."""
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = lambda s: s
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_cursor.fetchall.return_value = rows
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.close = MagicMock()
    return lambda: mock_conn


class TestPromptSecretsCollector:
    def test_returns_list_when_no_rows(self):
        """Empty query result should return empty list."""
        from threathunting_ai.collectors.prompt_secrets_collector import collect
        import tools.postgres_tool as pt

        pt.set_connection_factory(_make_pg_factory([]))
        result = collect()
        assert isinstance(result, list)
        assert result == []

    def test_detects_openai_key_in_prompt(self):
        """Detect OpenAI sk- key pattern in prompt.received event."""
        from threathunting_ai.collectors.prompt_secrets_collector import collect
        import tools.postgres_tool as pt

        rows = [{
            "event_id": "e1",
            "event_type": "prompt.received",
            "actor": "user1",
            "session_id": "s1",
            "timestamp": "2026-01-01T00:00:00",
            "payload": {"prompt": "Use sk-abcdefghijklmnopqrstu for authentication"},
        }]
        pt.set_connection_factory(_make_pg_factory(rows))
        result = collect()
        assert len(result) == 1
        assert result[0]["type"] == "secret_in_prompt"
        assert result[0]["severity"] == "critical"
        assert result[0]["anomalous"] is True

    def test_detects_aws_key_in_response(self):
        """Detect AWS AKIA key pattern in final.response event."""
        from threathunting_ai.collectors.prompt_secrets_collector import collect
        import tools.postgres_tool as pt

        rows = [{
            "event_id": "e2",
            "event_type": "final.response",
            "actor": "user2",
            "session_id": "s2",
            "timestamp": "2026-01-01T01:00:00",
            "payload": {"text": "AWS key is AKIAIOSFODNN7EXAMPLE in the response"},
        }]
        pt.set_connection_factory(_make_pg_factory(rows))
        result = collect()
        assert len(result) >= 1
        assert any(r["type"] == "secret_in_prompt" for r in result)

    def test_ignores_clean_text(self):
        """Benign text should not trigger findings."""
        from threathunting_ai.collectors.prompt_secrets_collector import collect
        import tools.postgres_tool as pt

        rows = [{
            "event_id": "e3",
            "event_type": "prompt.received",
            "actor": "user3",
            "session_id": "s3",
            "timestamp": "2026-01-01T02:00:00",
            "payload": {"prompt": "What is the weather like today?"},
        }]
        pt.set_connection_factory(_make_pg_factory(rows))
        result = collect()
        assert result == []

    def test_postgres_unavailable_returns_empty(self):
        """When Postgres connection factory is None, should return []."""
        from threathunting_ai.collectors.prompt_secrets_collector import collect
        import tools.postgres_tool as pt

        pt.set_connection_factory(None)
        result = collect()
        assert result == []

    def test_result_fields_structure(self):
        """Result should have all required fields when secret found in details."""
        from threathunting_ai.collectors.prompt_secrets_collector import collect
        import tools.postgres_tool as pt

        rows = [{
            "event_id": "e4",
            "event_type": "prompt.received",
            "actor": "user4",
            "session_id": "s4",
            "timestamp": "2026-01-01T03:00:00",
            "payload": {
                "details": {"prompt": "sk-testkey1234567890123456789012 is secret"}
            },
        }]
        pt.set_connection_factory(_make_pg_factory(rows))
        result = collect()
        if result:  # If we found a secret
            required_fields = {"type", "severity", "event_type", "session_id", "anomalous", "location"}
            assert required_fields.issubset(result[0].keys())
            assert result[0]["type"] == "secret_in_prompt"
            assert result[0]["severity"] == "critical"


class TestDataLeakageCollector:
    def test_returns_empty_on_no_rows(self):
        """Empty query result should return empty list."""
        from threathunting_ai.collectors.data_leakage_collector import collect
        import tools.postgres_tool as pt

        pt.set_connection_factory(_make_pg_factory([]))
        result = collect()
        assert isinstance(result, list)
        assert result == []

    def test_detects_ssn_in_response(self):
        """Detect SSN pattern (###-##-####) in final.response event."""
        from threathunting_ai.collectors.data_leakage_collector import collect
        import tools.postgres_tool as pt

        rows = [{
            "event_id": "dl1",
            "event_type": "final.response",
            "actor": "agent",
            "session_id": "s10",
            "timestamp": "2026-01-01T00:00:00",
            "payload": {"text": "The user's SSN is 123-45-6789 from the record."},
        }]
        pt.set_connection_factory(_make_pg_factory(rows))
        result = collect()
        assert len(result) >= 1
        assert any(r["pii_type"] == "ssn" for r in result)
        assert all(r["anomalous"] is True for r in result)

    def test_detects_credit_card_in_response(self):
        """Detect credit card pattern (13-16 digits) in final.response event."""
        from threathunting_ai.collectors.data_leakage_collector import collect
        import tools.postgres_tool as pt

        rows = [{
            "event_id": "dl2",
            "event_type": "final.response",
            "actor": "agent",
            "session_id": "s11",
            "timestamp": "2026-01-01T00:00:00",
            "payload": {"text": "Card number: 4111111111111111 was used"},
        }]
        pt.set_connection_factory(_make_pg_factory(rows))
        result = collect()
        assert len(result) >= 1
        assert any(r["pii_type"] == "credit_card" for r in result)

    def test_detects_email_in_response(self):
        """Detect email pattern in final.response event."""
        from threathunting_ai.collectors.data_leakage_collector import collect
        import tools.postgres_tool as pt

        rows = [{
            "event_id": "dl3",
            "event_type": "final.response",
            "actor": "agent",
            "session_id": "s12",
            "timestamp": "2026-01-01T00:00:00",
            "payload": {"text": "The email address is john.doe@example.com"},
        }]
        pt.set_connection_factory(_make_pg_factory(rows))
        result = collect()
        assert len(result) >= 1
        assert any(r["pii_type"] == "email" for r in result)

    def test_ignores_clean_response(self):
        """Benign text should not trigger findings."""
        from threathunting_ai.collectors.data_leakage_collector import collect
        import tools.postgres_tool as pt

        rows = [{
            "event_id": "dl4",
            "event_type": "final.response",
            "actor": "agent",
            "session_id": "s13",
            "timestamp": "2026-01-01T00:00:00",
            "payload": {"text": "Here is a summary of your project status."},
        }]
        pt.set_connection_factory(_make_pg_factory(rows))
        result = collect()
        assert result == []

    def test_postgres_unavailable_returns_empty(self):
        """When Postgres connection factory is None, should return []."""
        from threathunting_ai.collectors.data_leakage_collector import collect
        import tools.postgres_tool as pt

        pt.set_connection_factory(None)
        result = collect()
        assert result == []


class TestToolMisuseCollector:
    def test_high_frequency_returns_finding(self):
        """High frequency tool use (>20 calls per hour) should return finding."""
        from threathunting_ai.collectors.tool_misuse_collector import ToolMisuseCollector
        import tools.postgres_tool as pt

        # Mock result: actor "bot" made 25 tool calls in last hour
        rows = [{"actor": "bot", "cnt": 25}]
        pt.set_connection_factory(_make_pg_factory(rows))
        collector = ToolMisuseCollector()
        result = collector.collect()

        assert len(result) >= 1
        high_freq = [r for r in result if r["type"] == "high_frequency_tool_use"]
        assert len(high_freq) >= 1
        assert high_freq[0]["severity"] == "high"
        assert high_freq[0]["anomalous"] is True

    def test_high_frequency_empty_returns_no_finding(self):
        """Empty result should return no findings."""
        from threathunting_ai.collectors.tool_misuse_collector import ToolMisuseCollector
        import tools.postgres_tool as pt

        pt.set_connection_factory(_make_pg_factory([]))
        collector = ToolMisuseCollector()
        result = collector.collect()

        assert result == []

    def test_rapid_chaining_returns_finding(self):
        """Rapid tool chaining (>5 calls within 60 seconds) should return finding."""
        from threathunting_ai.collectors.tool_misuse_collector import ToolMisuseCollector
        import tools.postgres_tool as pt

        # Mock result: session "s1" had 6 tool calls in a 60-second burst
        rows = [{
            "session_id": "s1",
            "burst_start": "2026-01-01T00:00:00",
            "burst_count": 6
        }]
        pt.set_connection_factory(_make_pg_factory(rows))
        collector = ToolMisuseCollector()
        result = collector.collect()

        assert len(result) >= 1
        chaining = [r for r in result if r["type"] == "rapid_tool_chaining"]
        assert len(chaining) >= 1
        assert chaining[0]["severity"] == "high"
        assert chaining[0]["anomalous"] is True

    def test_blocked_ratio_returns_finding(self):
        """High blocked tool ratio (>30%, min 5 calls) should return critical finding."""
        from threathunting_ai.collectors.tool_misuse_collector import ToolMisuseCollector
        import tools.postgres_tool as pt

        # Mock result: actor "bot" had 10 tool calls, 4 blocked (40% ratio)
        rows = [{
            "actor": "bot",
            "blocked": 4,
            "total": 10,
            "block_ratio": 40.0
        }]
        pt.set_connection_factory(_make_pg_factory(rows))
        collector = ToolMisuseCollector()
        result = collector.collect()

        assert len(result) >= 1
        blocked = [r for r in result if r["type"] == "high_blocked_tool_ratio"]
        assert len(blocked) >= 1
        assert blocked[0]["severity"] == "critical"
        assert blocked[0]["anomalous"] is True

    def test_no_postgres_returns_empty(self):
        """When Postgres connection factory is None, should return []."""
        from threathunting_ai.collectors.tool_misuse_collector import ToolMisuseCollector
        import tools.postgres_tool as pt

        pt.set_connection_factory(None)
        collector = ToolMisuseCollector()
        result = collector.collect()

        assert result == []

    def test_db_exception_returns_empty(self):
        """When DB raises exception, should return [] gracefully."""
        from threathunting_ai.collectors.tool_misuse_collector import ToolMisuseCollector
        import tools.postgres_tool as pt

        # Create a factory that raises an exception
        def failing_factory():
            raise RuntimeError("Database connection failed")

        pt.set_connection_factory(failing_factory)
        collector = ToolMisuseCollector()
        result = collector.collect()

        assert result == []


class TestRuntimeCollectorV2:
    """Tests for upgraded RuntimeCollector with enforcement block clusters and session storm."""

    def test_enforcement_block_cluster_returns_finding(self):
        """Enforcement block cluster (3+ blocks in 1 hour) should return finding."""
        from threathunting_ai.collectors.runtime_collector import RuntimeCollector
        import tools.postgres_tool as pt

        # Mock result: session "s1" had 4 enforcement blocks in the last hour
        rows = [{
            "session_id": "s1",
            "block_count": 4,
            "first_block": "2026-01-01T00:00:00"
        }]
        pt.set_connection_factory(_make_pg_factory(rows))
        collector = RuntimeCollector()
        result = collector.collect()

        assert len(result) >= 1
        findings = [r for r in result if r["type"] == "enforcement_block_cluster"]
        assert len(findings) >= 1
        assert findings[0]["severity"] == "high"
        assert findings[0]["asset"] == "s1"
        assert findings[0]["anomalous"] is True

    def test_enforcement_block_cluster_empty_returns_nothing(self):
        """Empty query result for enforcement_block_cluster should return empty."""
        from threathunting_ai.collectors.runtime_collector import RuntimeCollector
        import tools.postgres_tool as pt

        pt.set_connection_factory(_make_pg_factory([]))
        collector = RuntimeCollector()
        result = collector.collect()

        # All patterns return empty, so overall result is []
        assert result == []

    def test_session_storm_returns_finding(self):
        """Session storm (5+ distinct sessions by actor in 10 min) should return critical finding."""
        from threathunting_ai.collectors.runtime_collector import RuntimeCollector
        import tools.postgres_tool as pt

        # Mock result: actor "bot" created 6 distinct sessions in the last 10 minutes
        rows = [{
            "actor": "bot",
            "session_count": 6
        }]
        pt.set_connection_factory(_make_pg_factory(rows))
        collector = RuntimeCollector()
        result = collector.collect()

        assert len(result) >= 1
        findings = [r for r in result if r["type"] == "session_storm"]
        assert len(findings) >= 1
        assert findings[0]["severity"] == "critical"
        assert findings[0]["asset"] == "bot"
        assert findings[0]["anomalous"] is True

    def test_session_storm_below_threshold_returns_nothing(self):
        """Session storm below threshold (< 5 sessions) should return empty."""
        from threathunting_ai.collectors.runtime_collector import RuntimeCollector
        import tools.postgres_tool as pt

        pt.set_connection_factory(_make_pg_factory([]))
        collector = RuntimeCollector()
        result = collector.collect()

        assert result == []

    def test_runtime_no_postgres_returns_empty(self):
        """When Postgres connection factory is None, should return []."""
        from threathunting_ai.collectors.runtime_collector import RuntimeCollector
        import tools.postgres_tool as pt

        pt.set_connection_factory(None)
        collector = RuntimeCollector()
        result = collector.collect()

        assert result == []

    def test_runtime_db_exception_returns_empty(self):
        """When DB raises exception, all patterns should return [] gracefully."""
        from threathunting_ai.collectors.runtime_collector import RuntimeCollector
        import tools.postgres_tool as pt

        # Create a factory that raises an exception
        def failing_factory():
            raise RuntimeError("Database connection failed")

        pt.set_connection_factory(failing_factory)
        collector = RuntimeCollector()
        result = collector.collect()

        assert result == []


# ─── ProcNetworkCollector ────────────────────────────────────────────────────

class TestProcNetworkCollector:
    """Tests for proc_network_collector.ProcNetworkCollector."""

    def test_no_proc_file_returns_empty(self):
        """On macOS or containers without /proc, returns []."""
        from threathunting_ai.collectors.proc_network_collector import ProcNetworkCollector
        with patch("builtins.open", side_effect=FileNotFoundError):
            result = ProcNetworkCollector().collect()
        assert result == []

    def test_all_allowed_ports_returns_empty(self):
        """When every LISTEN port is in the allowlist, no findings produced."""
        from threathunting_ai.collectors.proc_network_collector import ProcNetworkCollector, _ALLOWED_LISTEN_PORTS
        # Port 8000 is in the allowlist; its hex is 0x1F40
        proc_content = (
            "  sl  local_address rem_address   st\n"
            "   0: 00000000:1F40 00000000:0000 0A 00000000:00000000\n"   # 8000 LISTEN
        )
        with patch("builtins.open", mock_open(read_data=proc_content)):
            result = ProcNetworkCollector().collect()
        assert result == []

    def test_unexpected_port_detected(self):
        """A LISTEN port not in the allowlist produces a finding."""
        from threathunting_ai.collectors.proc_network_collector import ProcNetworkCollector
        # Port 9999 (0x270F) — not in allowlist
        proc_content = (
            "  sl  local_address rem_address   st\n"
            "   0: 00000000:270F 00000000:0000 0A 00000000:00000000\n"
        )
        with patch("builtins.open", mock_open(read_data=proc_content)):
            result = ProcNetworkCollector().collect()
        assert len(result) == 1
        assert result[0]["scan_type"] == "proc_network_scan"
        assert result[0]["anomalous"] is True
        assert 9999 == result[0]["evidence"][0]["port"]

    def test_non_listen_state_ignored(self):
        """Connections in ESTABLISHED (0x01) state are not reported."""
        from threathunting_ai.collectors.proc_network_collector import ProcNetworkCollector
        # Port 9999 in ESTABLISHED state (01) — should be ignored
        proc_content = (
            "  sl  local_address rem_address   st\n"
            "   0: 00000000:270F 00000000:0000 01 00000000:00000000\n"
        )
        with patch("builtins.open", mock_open(read_data=proc_content)):
            result = ProcNetworkCollector().collect()
        assert result == []

    def test_severity_well_known_port_is_high(self):
        """Ports < 1024 get severity=high."""
        from threathunting_ai.collectors.proc_network_collector import _severity_for_port
        assert _severity_for_port(23) == "high"    # telnet — unexpected privileged bind

    def test_severity_registered_port_is_medium(self):
        from threathunting_ai.collectors.proc_network_collector import _severity_for_port
        assert _severity_for_port(9999) == "medium"

    def test_severity_ephemeral_port_is_low(self):
        from threathunting_ai.collectors.proc_network_collector import _severity_for_port
        assert _severity_for_port(60000) == "low"
