"""
tests/test_postgres_tool.py
────────────────────────────
Unit tests for tools/postgres_tool.py.

The Postgres connection is replaced with a fake that returns controlled rows,
so no real database is required.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

import tools.postgres_tool as pg_mod
from tools.postgres_tool import (
    query_audit_logs,
    query_model_registry,
    query_posture_history,
    set_connection_factory,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_fake_conn(rows: list[dict]):
    """Return a fake psycopg2-like connection that yields `rows` from fetchall."""
    fake_cursor = MagicMock()
    fake_cursor.fetchall.return_value = [dict(r) for r in rows]
    # Support use as context manager
    fake_cursor.__enter__ = lambda s: s
    fake_cursor.__exit__ = MagicMock(return_value=False)

    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cursor
    fake_conn.close = MagicMock()
    return fake_conn


def _setup_factory(rows: list[dict]):
    """Inject a factory that returns a fake connection with the given rows."""
    set_connection_factory(lambda: _make_fake_conn(rows))


# ─────────────────────────────────────────────────────────────────────────────
# query_audit_logs
# ─────────────────────────────────────────────────────────────────────────────

class TestQueryAuditLogs:
    def test_returns_rows_as_json(self):
        ts = datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc)
        _setup_factory([
            {"event_id": "e1", "tenant_id": "t1", "event_type": "login",
             "actor": "alice", "timestamp": ts, "payload": {"ip": "1.2.3.4"}},
        ])
        result = query_audit_logs(tenant_id="t1")
        rows = json.loads(result)
        assert len(rows) == 1
        assert rows[0]["event_id"] == "e1"
        assert rows[0]["event_type"] == "login"
        assert "2024-01-15" in rows[0]["timestamp"]

    def test_empty_result(self):
        _setup_factory([])
        result = query_audit_logs(tenant_id="t1")
        assert json.loads(result) == []

    def test_limit_capped_at_200(self):
        """Even if caller requests 9999 rows, SQL gets limit=200."""
        _setup_factory([])
        with patch.object(pg_mod, "_query", return_value=[]) as mock_q:
            query_audit_logs(tenant_id="t1", limit=9999)
            sql, params = mock_q.call_args[0]
            assert params[-1] == 200  # last param is the LIMIT value

    def test_event_type_filter_included_in_params(self):
        _setup_factory([])
        with patch.object(pg_mod, "_query", return_value=[]) as mock_q:
            query_audit_logs(tenant_id="t1", event_type="decision.block")
            _, params = mock_q.call_args[0]
            assert "decision.block" in params

    def test_actor_filter_included_in_params(self):
        _setup_factory([])
        with patch.object(pg_mod, "_query", return_value=[]) as mock_q:
            query_audit_logs(tenant_id="t1", actor="bob")
            _, params = mock_q.call_args[0]
            assert "bob" in params

    def test_returns_error_json_on_exception(self):
        set_connection_factory(lambda: (_ for _ in ()).throw(Exception("db down")))
        result = query_audit_logs(tenant_id="t1")
        data = json.loads(result)
        assert "error" in data


# ─────────────────────────────────────────────────────────────────────────────
# query_posture_history
# ─────────────────────────────────────────────────────────────────────────────

class TestQueryPostureHistory:
    def test_returns_snapshot_rows(self):
        ts = datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)
        _setup_factory([
            {"id": 1, "model_id": "uuid-1", "tenant_id": "t1",
             "snapshot_at": ts, "request_count": 100, "block_count": 5,
             "escalation_count": 2, "avg_risk_score": 0.35, "max_risk_score": 0.9,
             "intent_drift_avg": 0.1, "ttp_hit_count": 3,
             "model_name": "gpt-sentinel", "model_risk_tier": "high"},
        ])
        result = query_posture_history(tenant_id="t1")
        rows = json.loads(result)
        assert rows[0]["request_count"] == 100
        assert rows[0]["model_name"] == "gpt-sentinel"
        assert "2024-01-15" in rows[0]["snapshot_at"]

    def test_hours_capped_at_168(self):
        _setup_factory([])
        with patch.object(pg_mod, "_query", return_value=[]) as mock_q:
            query_posture_history(tenant_id="t1", hours=9999)
            _, params = mock_q.call_args[0]
            assert 168 in params

    def test_limit_capped_at_500(self):
        _setup_factory([])
        with patch.object(pg_mod, "_query", return_value=[]) as mock_q:
            query_posture_history(tenant_id="t1", limit=9999)
            _, params = mock_q.call_args[0]
            assert params[-1] == 500

    def test_model_id_filter_in_params(self):
        _setup_factory([])
        with patch.object(pg_mod, "_query", return_value=[]) as mock_q:
            query_posture_history(tenant_id="t1", model_id="uuid-abc")
            _, params = mock_q.call_args[0]
            assert "uuid-abc" in params

    def test_error_returns_json(self):
        set_connection_factory(lambda: (_ for _ in ()).throw(RuntimeError("oops")))
        result = query_posture_history(tenant_id="t1")
        assert "error" in json.loads(result)


# ─────────────────────────────────────────────────────────────────────────────
# query_model_registry
# ─────────────────────────────────────────────────────────────────────────────

class TestQueryModelRegistry:
    def test_returns_model_rows(self):
        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        _setup_factory([
            {"model_id": "uuid-m1", "name": "FinanceGPT", "version": "1.0",
             "provider": "openai", "purpose": "analytics", "risk_tier": "high",
             "tenant_id": "t1", "status": "approved", "approved_by": "admin",
             "approved_at": ts, "created_at": ts, "updated_at": ts},
        ])
        result = query_model_registry(tenant_id="t1")
        rows = json.loads(result)
        assert rows[0]["name"] == "FinanceGPT"
        assert rows[0]["risk_tier"] == "high"

    def test_risk_tier_filter_in_params(self):
        _setup_factory([])
        with patch.object(pg_mod, "_query", return_value=[]) as mock_q:
            query_model_registry(tenant_id="t1", risk_tier="unacceptable")
            _, params = mock_q.call_args[0]
            assert "unacceptable" in params

    def test_status_filter_in_params(self):
        _setup_factory([])
        with patch.object(pg_mod, "_query", return_value=[]) as mock_q:
            query_model_registry(tenant_id="t1", status="under_review")
            _, params = mock_q.call_args[0]
            assert "under_review" in params

    def test_limit_capped_at_200(self):
        _setup_factory([])
        with patch.object(pg_mod, "_query", return_value=[]) as mock_q:
            query_model_registry(tenant_id="t1", limit=9999)
            _, params = mock_q.call_args[0]
            assert params[-1] == 200

    def test_error_returns_json(self):
        set_connection_factory(lambda: (_ for _ in ()).throw(Exception("conn failed")))
        result = query_model_registry(tenant_id="t1")
        assert "error" in json.loads(result)


# ─────────────────────────────────────────────────────────────────────────────
# set_connection_factory / RuntimeError guard
# ─────────────────────────────────────────────────────────────────────────────

class TestConnectionFactory:
    def test_raises_if_factory_not_set(self):
        original = pg_mod._connection_factory
        pg_mod._connection_factory = None
        try:
            with pytest.raises(RuntimeError, match="not initialised"):
                pg_mod._get_conn()
        finally:
            pg_mod._connection_factory = original

    def test_set_connection_factory_replaces_factory(self):
        sentinel = lambda: "fake"
        set_connection_factory(sentinel)
        assert pg_mod._connection_factory is sentinel
