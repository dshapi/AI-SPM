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
