"""
tests/test_credentials_live.py — coverage for platform_shared.credentials.

Unit-level safety net for the live-credential lookup that replaces
process-restart credential rotation. An end-to-end smoke (real
Postgres + Redis + spm-api configure roundtrip) lives outside CI; this
file exercises the in-process invariants:

    1.  Fresh-window cache HIT             → no DB round-trip at all
    2.  Cache MISS                         → full DB lookup → cached as JSON
    3.  Rotation via invalidate            → next read pulls new value
    4.  Redis down                         → fail-soft, fall through to DB
    5.  DB down (cold)                     → return ``default``
    6.  DB returns blank                   → not cached, return ``default``
    7.  Env fallback for unmanaged vars    → plain os.environ
    8.  Managed-env: DB beats env          → rotated value wins
    9.  Managed-env: env wins on DB miss   → operator override preserved
   10.  invalidate wipes every field       → whole vendor's fields dropped
   11.  invalidate with no Redis           → no-op, no raise

   NEW (fail-closed-on-staleness model):
   12.  Stale cache, version matches      → cache extended, full lookup
                                              NOT called, only cheap check
   13.  Stale cache, version drifts       → full refetch, recache with
                                              the new value
   14.  Stale cache, DB unreachable       → serve cached (fail-soft) but
                                              DO NOT extend TTL, so the
                                              entry expires naturally
   15.  freshness_s=0 forces revalidation on every read
   16.  Legacy raw-string cache value     → dropped, full lookup, recached
                                              as JSON (safe forward
                                              migration with no manual
                                              flush required)

The DB fakes are patched ``_db_lookup`` / ``_db_version_check`` so we
can prove the cheap path is taken when it should be.
"""
from __future__ import annotations

import json
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


# Test fixture constant: an obviously-iso version string.
V1 = "2026-04-24T10:00:00+00:00"
V2 = "2026-04-24T11:30:00+00:00"


def _prime_cache(fake_redis: FakeRedis, *, key: str, value: str, version: str,
                 age_s: float = 0.0, ttl_s: int = 30) -> None:
    """Put a JSON-packed entry in the fake with a synthetic age."""
    blob = json.dumps(
        {"v": value, "ver": version, "t": time.time() - age_s},
        separators=(",", ":"),
    )
    fake_redis._store[key] = (blob, time.time() + ttl_s)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Fresh-window cache HIT bypasses DB entirely
# ─────────────────────────────────────────────────────────────────────────────
def test_fresh_cache_hit_skips_db(fake_redis):
    _prime_cache(
        fake_redis,
        key="cred:int-003:credential:api_key",
        value="sk-ant-cached", version=V1,
        age_s=0.0,                 # just cached → inside freshness window
    )
    with patch.object(cred_mod, "_db_lookup") as mock_full, \
         patch.object(cred_mod, "_db_version_check") as mock_cheap:
        v = cred_mod.get_credential("int-003", field="api_key")
    assert v == "sk-ant-cached"
    mock_full.assert_not_called()
    mock_cheap.assert_not_called()  # freshness window → no DB hit AT ALL


# ─────────────────────────────────────────────────────────────────────────────
# 2. Cache MISS → full DB lookup → cached as JSON with version stamp
# ─────────────────────────────────────────────────────────────────────────────
def test_cache_miss_queries_db_and_populates(fake_redis):
    with patch.object(cred_mod, "_db_lookup",
                      return_value=("sk-ant-from-db", V1)) as mock_db:
        v = cred_mod.get_credential("int-003", field="api_key", ttl=60)
    assert v == "sk-ant-from-db"
    mock_db.assert_called_once_with("int-003", "credential", "api_key", 3.0)
    # Exactly one SETEX, with the JSON-packed (value, version, t) triple.
    assert len(fake_redis.set_calls) == 1
    key, ttl, blob = fake_redis.set_calls[0]
    assert key == "cred:int-003:credential:api_key"
    assert ttl == 60
    parsed = json.loads(blob)
    assert parsed["v"] == "sk-ant-from-db"
    assert parsed["ver"] == V1
    assert isinstance(parsed["t"], (int, float))


# ─────────────────────────────────────────────────────────────────────────────
# 3. Rotation flow via explicit invalidate_credential_cache
# ─────────────────────────────────────────────────────────────────────────────
def test_rotation_propagates_after_invalidation(fake_redis):
    state = {"value": "sk-old-key", "version": V1}

    def fake_lookup(vendor, kind, field, timeout):
        return state["value"], state["version"]

    with patch.object(cred_mod, "_db_lookup", side_effect=fake_lookup):
        # First read: DB → cache populated.
        assert cred_mod.get_credential("int-003", field="api_key") == "sk-old-key"
        assert "cred:int-003:credential:api_key" in fake_redis._store

        # Admin rotates the credential; configure handler calls invalidate.
        state["value"] = "sk-new-key"
        state["version"] = V2
        deleted = cred_mod.invalidate_credential_cache("int-003")
        assert deleted == 1

        # Next read: cache miss → DB returns new value.
        assert cred_mod.get_credential("int-003", field="api_key") == "sk-new-key"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Redis down → fall through to DB without raising
# ─────────────────────────────────────────────────────────────────────────────
def test_redis_down_falls_through_to_db(no_redis):
    with patch.object(cred_mod, "_db_lookup",
                      return_value=("sk-from-db", V1)) as mock_db:
        v = cred_mod.get_credential("int-003", field="api_key", default="OOPS")
    assert v == "sk-from-db"
    mock_db.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# 5. DB down (cold, no cached entry) → return default
# ─────────────────────────────────────────────────────────────────────────────
def test_db_down_returns_default(no_redis):
    with patch.object(cred_mod, "_db_lookup", return_value=None):
        v = cred_mod.get_credential("int-003", field="api_key", default="FALLBACK")
    assert v == "FALLBACK"


# ─────────────────────────────────────────────────────────────────────────────
# 6. DB returns blank/empty → not cached, return default
# ─────────────────────────────────────────────────────────────────────────────
def test_db_returns_blank_treated_as_missing(fake_redis):
    with patch.object(cred_mod, "_db_lookup", return_value=("", V1)):
        v = cred_mod.get_credential("int-003", field="api_key", default="FALLBACK")
    assert v == "FALLBACK"
    assert fake_redis.set_calls == []


# ─────────────────────────────────────────────────────────────────────────────
# 7/8/9. get_credential_by_env: managed + unmanaged paths
# ─────────────────────────────────────────────────────────────────────────────
def test_get_credential_by_env_managed_var(fake_redis, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-fallback")
    _prime_cache(
        fake_redis,
        key="cred:int-003:credential:api_key",
        value="db-rotated", version=V1, age_s=0.0,
    )
    v = cred_mod.get_credential_by_env("ANTHROPIC_API_KEY")
    assert v == "db-rotated"  # DB/cache beats env


def test_get_credential_by_env_managed_var_falls_back_to_env(fake_redis, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "operator-set")
    with patch.object(cred_mod, "_db_lookup", return_value=None):
        v = cred_mod.get_credential_by_env("ANTHROPIC_API_KEY")
    assert v == "operator-set"


def test_get_credential_by_env_unmanaged_var(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    with patch.object(cred_mod, "_db_lookup") as mock_db:
        v = cred_mod.get_credential_by_env("LOG_LEVEL")
    assert v == "DEBUG"
    mock_db.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 10. invalidate_credential_cache wipes every field for a vendor
# ─────────────────────────────────────────────────────────────────────────────
def test_invalidate_wipes_every_field_for_vendor(fake_redis):
    now = time.time()
    fake_redis._store["cred:int-017:config:base_url"] = ("x", now + 60)
    fake_redis._store["cred:int-017:config:model"]    = ("y", now + 60)
    fake_redis._store["cred:int-017:config:guard_prompt_mode"] = ("z", now + 60)
    fake_redis._store["cred:int-003:credential:api_key"] = ("untouched", now + 60)

    deleted = cred_mod.invalidate_credential_cache("int-017")
    assert deleted == 3
    assert "cred:int-003:credential:api_key" in fake_redis._store
    assert all(not k.startswith("cred:int-017:") for k in fake_redis._store)


def test_invalidate_redis_down_returns_zero(no_redis):
    assert cred_mod.invalidate_credential_cache("int-003") == 0


# ═════════════════════════════════════════════════════════════════════════════
# NEW — fail-closed-on-staleness semantics
# ═════════════════════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────────────────
# 12. Stale cache, version matches: cheap check only, TTL extended,
#     full _db_lookup NOT called.
# ─────────────────────────────────────────────────────────────────────────────
def test_stale_cache_version_match_extends_without_refetch(fake_redis):
    KEY = "cred:int-003:credential:api_key"
    _prime_cache(
        fake_redis, key=KEY,
        value="sk-still-current", version=V1,
        age_s=10.0,  # past default freshness_s=5
    )
    with patch.object(cred_mod, "_db_version_check", return_value=V1) as mock_cheap, \
         patch.object(cred_mod, "_db_lookup") as mock_full:
        v = cred_mod.get_credential("int-003", field="api_key")
    assert v == "sk-still-current"
    mock_cheap.assert_called_once_with("int-003", "credential", "api_key", 3.0)
    mock_full.assert_not_called()
    # TTL was extended — a SETEX happened with the cached value.
    assert len(fake_redis.set_calls) == 1
    key, _ttl, blob = fake_redis.set_calls[0]
    assert key == KEY
    parsed = json.loads(blob)
    assert parsed["v"] == "sk-still-current"
    assert parsed["ver"] == V1  # same version preserved


# ─────────────────────────────────────────────────────────────────────────────
# 13. Stale cache, version drifts: full refetch and recache with new value.
# ─────────────────────────────────────────────────────────────────────────────
def test_stale_cache_version_drift_triggers_refetch(fake_redis):
    KEY = "cred:int-003:credential:api_key"
    _prime_cache(
        fake_redis, key=KEY,
        value="sk-old-and-stale", version=V1,
        age_s=10.0,
    )
    with patch.object(cred_mod, "_db_version_check", return_value=V2) as mock_cheap, \
         patch.object(cred_mod, "_db_lookup",
                      return_value=("sk-brand-new", V2)) as mock_full:
        v = cred_mod.get_credential("int-003", field="api_key")
    assert v == "sk-brand-new"
    mock_cheap.assert_called_once()
    mock_full.assert_called_once()
    # Cache now holds the new value + new version.
    assert len(fake_redis.set_calls) == 1
    _key, _ttl, blob = fake_redis.set_calls[0]
    parsed = json.loads(blob)
    assert parsed["v"] == "sk-brand-new"
    assert parsed["ver"] == V2


# ─────────────────────────────────────────────────────────────────────────────
# 14. Stale cache, DB unreachable on version-check: serve cached, do NOT
#     extend TTL. This is the "fail-soft for correctness" path: a wobble
#     shouldn't 500 the request, but a prolonged outage must let the
#     entry naturally expire so we don't pin a stale credential forever.
# ─────────────────────────────────────────────────────────────────────────────
def test_stale_cache_db_down_serves_cached_without_extending(fake_redis):
    KEY = "cred:int-003:credential:api_key"
    _prime_cache(
        fake_redis, key=KEY,
        value="sk-last-known-good", version=V1,
        age_s=10.0,
    )
    with patch.object(cred_mod, "_db_version_check", return_value=None), \
         patch.object(cred_mod, "_db_lookup") as mock_full:
        v = cred_mod.get_credential("int-003", field="api_key")
    assert v == "sk-last-known-good"
    mock_full.assert_not_called()            # no retry of the expensive path
    assert fake_redis.set_calls == []        # TTL NOT extended


# ─────────────────────────────────────────────────────────────────────────────
# 15. freshness_s=0 forces revalidation on every read.
# ─────────────────────────────────────────────────────────────────────────────
def test_freshness_zero_always_revalidates(fake_redis):
    KEY = "cred:int-003:credential:api_key"
    _prime_cache(
        fake_redis, key=KEY,
        value="sk-just-cached", version=V1,
        age_s=0.0,  # *would* be fresh under default
    )
    with patch.object(cred_mod, "_db_version_check", return_value=V1) as mock_cheap, \
         patch.object(cred_mod, "_db_lookup") as mock_full:
        v = cred_mod.get_credential(
            "int-003", field="api_key", freshness_s=0,
        )
    assert v == "sk-just-cached"
    mock_cheap.assert_called_once()          # forced check even on fresh entry
    mock_full.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 16. Legacy raw-string cache value (from before this refactor): dropped,
#     full lookup runs, recached as JSON. No manual flush required.
# ─────────────────────────────────────────────────────────────────────────────
def test_legacy_raw_string_cache_is_migrated(fake_redis):
    KEY = "cred:int-003:credential:api_key"
    # Pre-refactor shape: value stored as a bare string, no JSON wrapper.
    fake_redis._store[KEY] = ("sk-legacy-bare-string", time.time() + 60)

    with patch.object(cred_mod, "_db_lookup",
                      return_value=("sk-fresh-from-db", V1)) as mock_full:
        v = cred_mod.get_credential("int-003", field="api_key")
    assert v == "sk-fresh-from-db"
    mock_full.assert_called_once()
    # New cache value is JSON-packed.
    assert any(json.loads(blob).get("v") == "sk-fresh-from-db"
               for (_k, _t, blob) in fake_redis.set_calls)
    # The legacy raw entry got explicitly DELeted before the recache.
    assert KEY in fake_redis.delete_calls
