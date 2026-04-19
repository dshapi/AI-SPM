"""
Tests for all four ThreatHunting AI collectors.
All external I/O is mocked — no real Redis, Postgres, or network calls.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# ── secrets_collector ────────────────────────────────────────────────────────

class TestSecretsCollector:
    def test_returns_list(self):
        from threathunting_ai.collectors.secrets_collector import collect
        with patch("tools.redis_tool._redis_client") as mock_redis:
            mock_redis.scan_iter.return_value = iter([])
            result = collect()
        assert isinstance(result, list)

    def test_detects_api_key_pattern(self):
        from threathunting_ai.collectors.secrets_collector import collect
        suspicious = [b"session:user1:api_key", b"config:openai_token"]
        with patch("tools.redis_tool._redis_client") as mock_redis:
            mock_redis.scan_iter.return_value = iter(suspicious)
            result = collect()
        assert len(result) == 2
        assert result[0]["type"] == "secret_exposure"
        assert "location" in result[0]
        assert "key_name" in result[0]

    def test_ignores_safe_keys(self):
        from threathunting_ai.collectors.secrets_collector import collect
        safe = [b"freeze:user1", b"session:abc123", b"mem:session:t1:u1:chat"]
        with patch("tools.redis_tool._redis_client") as mock_redis:
            mock_redis.scan_iter.return_value = iter(safe)
            result = collect()
        assert result == []

    def test_collect_sensitive_data_returns_list(self):
        from threathunting_ai.collectors.secrets_collector import collect_sensitive_data
        with patch("tools.redis_tool._redis_client") as mock_redis:
            mock_redis.scan_iter.return_value = iter([])
            result = collect_sensitive_data()
        assert isinstance(result, list)

    def test_redis_unavailable_returns_empty(self):
        from threathunting_ai.collectors.secrets_collector import collect
        with patch("tools.redis_tool._redis_client", None):
            result = collect()
        assert result == []


# ── network_collector ────────────────────────────────────────────────────────

class TestNetworkCollector:
    def test_returns_list(self):
        from threathunting_ai.collectors.network_collector import collect
        with patch("socket.create_connection", side_effect=ConnectionRefusedError):
            result = collect()
        assert isinstance(result, list)

    def test_open_port_detected(self):
        from threathunting_ai.collectors.network_collector import collect
        mock_sock = MagicMock()
        mock_sock.__enter__ = lambda s: s
        mock_sock.__exit__ = MagicMock(return_value=False)

        def _connect(addr, timeout):
            host, port = addr
            if port == 8094:
                return mock_sock
            raise ConnectionRefusedError

        with patch("socket.create_connection", side_effect=_connect):
            result = collect()
        assert any(r["port"] == 8094 and r["reachable"] is True for r in result)

    def test_each_result_has_required_fields(self):
        from threathunting_ai.collectors.network_collector import collect
        with patch("socket.create_connection", side_effect=ConnectionRefusedError):
            result = collect()
        for item in result:
            assert "type" in item
            assert item["type"] == "port_status"
            assert "host" in item
            assert "port" in item
            assert "reachable" in item


# ── agent_config_collector ───────────────────────────────────────────────────

class TestAgentConfigCollector:
    def _pg_factory(self, rows):
        """Return a Postgres connection factory returning `rows` from fetchall."""
        import psycopg2.extras

        mock_cursor = MagicMock()
        mock_cursor.__enter__ = lambda s: s
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchall.return_value = rows

        mock_conn = MagicMock()
        # cursor() must support keyword args (cursor_factory=...)
        mock_conn.cursor.return_value = mock_cursor

        return lambda: mock_conn

    def test_returns_list(self):
        from threathunting_ai.collectors.agent_config_collector import collect
        import tools.postgres_tool as pt

        # query_model_registry is called, not raw cursor — patch it
        with patch("tools.postgres_tool.query_model_registry", return_value="[]"):
            pt.set_connection_factory(lambda: MagicMock())
            result = collect()
        assert isinstance(result, list)

    def test_detects_unacceptable_risk_model(self):
        from threathunting_ai.collectors.agent_config_collector import collect
        import tools.postgres_tool as pt

        models = [{
            "model_id": "m1", "name": "DangerBot",
            "risk_tier": "unacceptable", "status": "approved",
            "approved_by": None, "approved_at": None, "tenant_id": "t1",
        }]
        with patch("tools.postgres_tool.query_model_registry", return_value=json.dumps(models)):
            pt.set_connection_factory(lambda: MagicMock())
            result = collect()
        assert len(result) >= 1
        assert result[0]["type"] == "unsafe_config"
        assert "model_id" in result[0]

    def test_each_result_has_required_fields(self):
        from threathunting_ai.collectors.agent_config_collector import collect
        import tools.postgres_tool as pt

        models = [{
            "model_id": "m2", "name": "RiskyBot",
            "risk_tier": "high", "status": "registered",
            "approved_by": None, "approved_at": None, "tenant_id": "t1",
        }]
        with patch("tools.postgres_tool.query_model_registry", return_value=json.dumps(models)):
            pt.set_connection_factory(lambda: MagicMock())
            result = collect()
        for item in result:
            assert "type" in item
            assert item["type"] == "unsafe_config"
            assert "model_id" in item
            assert "issue" in item
            assert "risk_tier" in item

    def test_postgres_unavailable_returns_empty(self):
        from threathunting_ai.collectors.agent_config_collector import collect
        import tools.postgres_tool as pt
        pt.set_connection_factory(None)
        result = collect()
        assert result == []


# ── runtime_collector ────────────────────────────────────────────────────────

class TestRuntimeCollector:
    def _make_pg_factory(self, rows):
        """Return factory whose cursor.fetchall() returns rows."""
        mock_cursor = MagicMock(spec=["__enter__", "__exit__", "execute", "fetchall"])
        mock_cursor.__enter__ = lambda s: s
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchall.return_value = rows

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.close = MagicMock()
        return lambda: mock_conn

    def test_returns_list(self):
        from threathunting_ai.collectors.runtime_collector import collect
        import tools.postgres_tool as pt
        pt.set_connection_factory(self._make_pg_factory([]))
        result = collect()
        assert isinstance(result, list)

    def test_detects_repeated_actor(self):
        from threathunting_ai.collectors.runtime_collector import collect
        import tools.postgres_tool as pt
        rows = [{"actor": "bad-user", "event_count": 10, "last_seen": "2026-01-01T00:00:00"}]
        pt.set_connection_factory(self._make_pg_factory(rows))
        result = collect()
        assert any(r["type"] == "anomalous_pattern" for r in result)

    def test_each_result_has_required_fields(self):
        from threathunting_ai.collectors.runtime_collector import collect
        import tools.postgres_tool as pt
        rows = [{"actor": "u1", "event_count": 8, "last_seen": "2026-01-01T00:00:00"}]
        pt.set_connection_factory(self._make_pg_factory(rows))
        result = collect()
        for item in result:
            assert "type" in item
            assert "pattern" in item
            assert "description" in item

    def test_postgres_unavailable_returns_empty(self):
        from threathunting_ai.collectors.runtime_collector import collect
        import tools.postgres_tool as pt
        pt.set_connection_factory(None)
        result = collect()
        assert result == []
