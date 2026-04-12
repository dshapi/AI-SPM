"""
tests/test_redis_tool.py
"""
from __future__ import annotations
import json
from unittest.mock import MagicMock
import pytest

import tools.redis_tool as redis_mod
from tools.redis_tool import get_freeze_state, scan_session_memory, set_redis_client


def _make_redis(get_val=None, ttl_val=30, scan_keys=None):
    r = MagicMock()
    r.get.return_value = get_val
    r.ttl.return_value = ttl_val
    scan_keys = scan_keys or []
    r.scan_iter.return_value = iter(scan_keys)
    return r


class TestGetFreezeState:
    def test_frozen_user(self):
        set_redis_client(_make_redis(get_val=b"true", ttl_val=120))
        result = json.loads(get_freeze_state("user", "alice"))
        assert result["frozen"] is True
        assert result["ttl_seconds"] == 120

    def test_not_frozen_user(self):
        set_redis_client(_make_redis(get_val=b"false", ttl_val=-1))
        result = json.loads(get_freeze_state("user", "alice"))
        assert result["frozen"] is False

    def test_missing_key(self):
        set_redis_client(_make_redis(get_val=None, ttl_val=-2))
        result = json.loads(get_freeze_state("user", "bob"))
        assert result["frozen"] is False
        assert result["ttl_seconds"] == -2

    def test_tenant_scope_key(self):
        r = _make_redis(get_val=b"true", ttl_val=60)
        set_redis_client(r)
        get_freeze_state("tenant", "acme")
        r.get.assert_called_once_with("freeze:acme:tenant")

    def test_session_scope_key(self):
        r = _make_redis(get_val=None)
        set_redis_client(r)
        get_freeze_state("session", "sess-123")
        r.get.assert_called_once_with("freeze:session:sess-123")

    def test_error_returns_json(self):
        r = MagicMock()
        r.get.side_effect = Exception("redis down")
        set_redis_client(r)
        result = json.loads(get_freeze_state("user", "x"))
        assert "error" in result

    def test_raises_if_client_not_set(self):
        redis_mod._redis_client = None
        with pytest.raises(RuntimeError, match="not initialised"):
            redis_mod._get_redis()


class TestScanSessionMemory:
    def test_returns_keys(self):
        keys = [b"mem:session:t1:alice:key1", b"mem:session:t1:alice:key2"]
        set_redis_client(_make_redis(scan_keys=keys))
        result = json.loads(scan_session_memory("t1", "alice"))
        assert result["count"] == 2
        assert "mem:session:t1:alice:key1" in result["keys"]

    def test_empty_scan(self):
        set_redis_client(_make_redis(scan_keys=[]))
        result = json.loads(scan_session_memory("t1", "alice"))
        assert result["count"] == 0
        assert result["keys"] == []

    def test_pattern_uses_namespace(self):
        r = _make_redis(scan_keys=[])
        set_redis_client(r)
        scan_session_memory("t1", "u1", namespace="longterm")
        r.scan_iter.assert_called_once_with("mem:longterm:t1:u1:*", count=100)

    def test_error_returns_json(self):
        r = MagicMock()
        r.scan_iter.side_effect = Exception("oops")
        set_redis_client(r)
        result = json.loads(scan_session_memory("t1", "u1"))
        assert "error" in result
