"""
tests/test_credentials_live.py — coverage for platform_shared.credentials.

This is the unit-level safety net for the live-credential lookup that
replaces process-restart credential rotation.  An end-to-end smoke (real
Postgres + Redis + spm-api configure roundtrip) lives outside CI; this
file exercises the in-process invariants:

    1. Cache HIT  → no DB round-trip
    2. Cache MISS → DB query → cache populated with TTL
    3. Rotation   → invalidate_credential_cache(vendor) drops the entry
                    so the next get_credential reads the new DB value
    4. Redis down → fail-soft, fall through to DB
    5. DB down    → fail-soft, return ``default``
    6. Env fallback for vars not in ENV_EXPORT_MAP

The Redis fake is a small shim that records calls; the DB fake is a
patched ``_db_lookup`` that returns whatever the test sets, so we can
prove the cache is consulted before the DB on hit and skipped after
invalidation.
"""
from __future__ import annotations

import os
import time
from typing import Optional
from unittest.mock import patch

import pytest

from platform_shared import credentials as cred_mod


# ─────────────────────────────────────────────────────────────────────────────
# Fakes
# ─────────────────────────────────────────────────────────────────────────────
class FakeRedis:
    """Minimal in-memory Redis with TTL accounting + call counters."""

    def __init__(self):
        self._store: dict[str, tuple[str, float]] = {}  # key -> (value, expires_at)
        self.get_calls: list[str] = []
        self.set_calls: list[tuple[str, int, str]] = []
        self.delete_calls: list[str] = []

    def ping(self) -> bool:
        return True

    def get(self, key: str) -> Optional[str]:
        self.get_calls.append(key)
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.time() >= expires_at:
            del self._store[key]
            return None
        return value

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.set_calls.append((key, ttl, value))
        self._store[key] = (value, time.time() + ttl)

    def scan_iter(self, match: str, count: int = 100):
        # naive prefix match (good enough for "cred:int-003:*")
        prefix = match.rstrip("*")
        return [k for k in list(self._store.keys()) if k.startswith(prefix)]

    def delete(self, key: str) -> int:
        self.delete_calls.append(key)
        return 1 if self._store.pop(key, None) else 0


@pytest.fixture
def fake_redis(monkeypatch):
    """Replace credentials._get_redis with a stub returning a fresh FakeRedis."""
    cred_mod.reset_redis_client()
    fake = FakeRedis()
    monkeypatch.setattr(cred_mod, "_get_redis", lambda: fake)
    yield fake
    cred_mod.reset_redis_client()


@pytest.fixture
def no_redis(monkeypatch):
    """Force _get_redis to return None — simulates Redis down."""
    cred_mod.reset_redis_client()
    monkeypatch.setattr(cred_mod, "_get_redis", lambda: None)
    yield
    cred_mod.reset_redis_client()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Cache HIT bypasses DB
# ─────────────────────────────────────────────────────────────────────────────
def test_cache_hit_skips_db(fake_redis):
    fake_redis._store["cred:int-003:credential:api_key"] = (
        "sk-ant-cached", time.time() + 60,
    )
    with patch.object(cred_mod, "_db_lookup") as mock_db:
        v = cred_mod.get_credential("int-003", field="api_key")
        assert v == "sk-ant-cached"
        mock_db.assert_not_called()
    assert fake_redis.get_calls == ["cred:int-003:credential:api_key"]


# ─────────────────────────────────────────────────────────────────────────────
# 2. Cache MISS → DB lookup → cache populated
# ─────────────────────────────────────────────────────────────────────────────
def test_cache_miss_queries_db_and_populates(fake_redis):
    with patch.object(cred_mod, "_db_lookup", return_value="sk-ant-from-db") as mock_db:
        v = cred_mod.get_credential("int-003", field="api_key", ttl=60)
        assert v == "sk-ant-from-db"
        mock_db.assert_called_once_with("int-003", "credential", "api_key", 3.0)
    assert fake_redis.set_calls == [("cred:int-003:credential:api_key", 60, "sk-ant-from-db")]


# ─────────────────────────────────────────────────────────────────────────────
# 3. Rotation flow: write → invalidate → next read sees new value
#
# Models the production sequence:
#   t=0  consumer reads "old-key", caches it
#   t=1  admin POST /integrations/{id}/configure with "new-key"
#   t=1  configure endpoint commits to DB, calls invalidate_credential_cache
#   t=2  consumer reads again — cache is empty, DB returns "new-key"
# ─────────────────────────────────────────────────────────────────────────────
def test_rotation_propagates_after_invalidation(fake_redis):
    db_value = {"value": "sk-old-key"}

    def fake_lookup(vendor, kind, field, timeout):
        return db_value["value"]

    with patch.object(cred_mod, "_db_lookup", side_effect=fake_lookup):
        # First read: DB → cache populated with old key
        assert cred_mod.get_credential("int-003", field="api_key") == "sk-old-key"
        assert "cred:int-003:credential:api_key" in fake_redis._store

        # Second read: cache hit, no DB call
        assert cred_mod.get_credential("int-003", field="api_key") == "sk-old-key"

        # Admin rotates the credential and configure calls invalidate.
        db_value["value"] = "sk-new-key"
        deleted = cred_mod.invalidate_credential_cache("int-003")
        assert deleted == 1
        assert "cred:int-003:credential:api_key" not in fake_redis._store

        # Third read: cache miss → DB returns new value, no restart needed.
        assert cred_mod.get_credential("int-003", field="api_key") == "sk-new-key"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Redis down → fall through to DB without raising
# ─────────────────────────────────────────────────────────────────────────────
def test_redis_down_falls_through_to_db(no_redis):
    with patch.object(cred_mod, "_db_lookup", return_value="sk-from-db") as mock_db:
        v = cred_mod.get_credential("int-003", field="api_key", default="OOPS")
        assert v == "sk-from-db"
        mock_db.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# 5. DB down → return default, do not raise
# ─────────────────────────────────────────────────────────────────────────────
def test_db_down_returns_default(no_redis):
    with patch.object(cred_mod, "_db_lookup", return_value=None):
        v = cred_mod.get_credential("int-003", field="api_key", default="FALLBACK")
        assert v == "FALLBACK"


def test_db_returns_blank_treated_as_missing(fake_redis):
    """Empty-string credential should NOT be cached — caller wants default."""
    with patch.object(cred_mod, "_db_lookup", return_value=""):
        v = cred_mod.get_credential("int-003", field="api_key", default="FALLBACK")
        assert v == "FALLBACK"
    # Crucially, no SETEX — we don't want to cache the blank.
    assert fake_redis.set_calls == []


# ─────────────────────────────────────────────────────────────────────────────
# 6. get_credential_by_env: managed + unmanaged paths
# ─────────────────────────────────────────────────────────────────────────────
def test_get_credential_by_env_managed_var(fake_redis, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-fallback")
    fake_redis._store["cred:int-003:credential:api_key"] = (
        "db-rotated", time.time() + 60,
    )
    v = cred_mod.get_credential_by_env("ANTHROPIC_API_KEY")
    # DB/cache value beats env when present
    assert v == "db-rotated"


def test_get_credential_by_env_managed_var_falls_back_to_env(fake_redis, monkeypatch):
    """When DB/cache returns nothing, the env value must win — preserves
    the operator-override semantics of the legacy hydrator and keeps
    local-dev .env files working."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "operator-set")
    with patch.object(cred_mod, "_db_lookup", return_value=None):
        v = cred_mod.get_credential_by_env("ANTHROPIC_API_KEY")
        assert v == "operator-set"


def test_get_credential_by_env_unmanaged_var(monkeypatch):
    """A var not in ENV_EXPORT_MAP is plain os.environ — no DB call."""
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    with patch.object(cred_mod, "_db_lookup") as mock_db:
        v = cred_mod.get_credential_by_env("LOG_LEVEL")
        assert v == "DEBUG"
        mock_db.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 7. invalidate_credential_cache wipes ALL fields for a vendor
# ─────────────────────────────────────────────────────────────────────────────
def test_invalidate_wipes_every_field_for_vendor(fake_redis):
    # Stash three fields under int-017 plus an unrelated vendor.
    now = time.time()
    fake_redis._store["cred:int-017:config:base_url"] = ("http://ollama:11434", now + 60)
    fake_redis._store["cred:int-017:config:model"]    = ("llama3", now + 60)
    fake_redis._store["cred:int-017:config:guard_prompt_mode"] = ("json", now + 60)
    fake_redis._store["cred:int-003:credential:api_key"] = ("untouched", now + 60)

    deleted = cred_mod.invalidate_credential_cache("int-017")
    assert deleted == 3
    assert "cred:int-003:credential:api_key" in fake_redis._store
    assert all(k.startswith("cred:int-017:") is False
               for k in fake_redis._store)


def test_invalidate_redis_down_returns_zero(no_redis):
    """No Redis → no-op, no exception."""
    assert cred_mod.invalidate_credential_cache("int-003") == 0
