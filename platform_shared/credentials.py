"""
platform_shared.credentials — live credential lookup with Redis caching.

Why this exists
───────────────
``platform_shared.integration_config.hydrate_env_from_db()`` populates
``os.environ`` once at process start, so credential rotations performed
through the UI don't take effect until the consuming container is
restarted. That operational footgun is unacceptable for a security
posture product whose whole pitch is "rotate keys without rebuilding."

This module replaces the env-read pattern with an on-demand lookup:

    from platform_shared.credentials import get_credential
    api_key = get_credential("int-003", field="api_key", default="")

Each call goes:
    Redis cache (TTL ~30s, decode_responses=True)
        → spm-db direct query (psycopg2, short timeout)
            → ``default`` on any failure

Writes go through ``invalidate_credential_cache(vendor)``, which the
configure endpoint calls after ``db.commit()`` so the next request
sees the new value within the polling lag of every other consumer's
in-flight TTL (worst case = TTL seconds).

Design notes
────────────
* Fail-soft everywhere — Redis down, DB down, missing row, blank
  credential all return ``default`` without raising. The whole point
  is that a chat request shouldn't 500 because Redis blinked.
* Backwards compatible — ``get_credential_by_env(env_name)`` resolves
  through the existing ``ENV_EXPORT_MAP`` so callers can migrate
  one read site at a time without re-deriving the (vendor, field, kind)
  triple by hand.
* No SQLAlchemy / no ORM — ``services/`` containers that don't ship
  ``spm.db`` still need to import this. psycopg2 only, same as
  ``integration_config``.
* In-memory negative cache for "credential not configured" is
  deliberately omitted; if a credential is genuinely missing the
  caller has bigger problems than 1 extra DB query per request.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional, Tuple

from .integration_config import (
    ENV_EXPORT_MAP,
    _decode_secret,
    _resolve_db_url,
)

log = logging.getLogger("platform_shared.credentials")

# ─────────────────────────────────────────────────────────────────────────────
# Cache freshness model — fail-closed on staleness.
#
# Two windows govern how long a cached credential is trusted:
#
#   * FRESHNESS_S  — within this many seconds of the last *full* DB read,
#                    the cached value is served with no DB hit at all.
#                    Cheap, hot path.
#   * TTL_S        — absolute Redis expiry. Past this, the entry is gone
#                    and the next read does a full lookup.
#
# Between FRESHNESS_S and TTL_S we run a *cheap* version check against
# spm-db: a single indexed `SELECT updated_at` to ask "is what I have
# still current?". On match we extend both windows; on mismatch we
# refetch the full value; on DB error we serve the cached value but
# refuse to extend, so a transient outage cannot pin a stale credential
# in the cache forever.
#
# This makes the cache fail-closed on staleness without depending on
# the writer's invalidation call ever succeeding — important because
# during a Redis outage the configure endpoint's DEL silently fails
# (correct behaviour: a successful save should not be undone by a cache
# blip), and we still must not serve the old key from any consumer.
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_FRESHNESS_S = 5
DEFAULT_TTL_S = 30

# ─────────────────────────────────────────────────────────────────────────────
# Redis client (lazy, shared, decode_responses=True so cache values are str).
#
# We deliberately don't reuse ``platform_shared.security._get_redis`` because
# this module needs to be importable from containers (e.g. agent-orchestrator,
# guard_model) that don't depend on ``platform_shared.config`` /
# ``platform_shared.security``.  Instead we read REDIS_HOST/PORT/PASSWORD
# directly, matching the env contract every other service already honours.
# ─────────────────────────────────────────────────────────────────────────────
_redis_client = None  # type: ignore[var-annotated]
_redis_unavailable = False  # latch — once we fail to connect we stop trying


def _get_redis():
    """Return a redis.Redis or None if redis isn't installed/reachable.

    The first failed connection latches ``_redis_unavailable`` so we don't
    retry on every credential lookup.  Tests/operators wanting to recover
    after a Redis outage call ``reset_redis_client()``.
    """
    global _redis_client, _redis_unavailable
    if _redis_unavailable:
        return None
    if _redis_client is not None:
        return _redis_client
    try:
        import redis as redis_lib  # local import — keep optional
    except Exception as exc:  # pragma: no cover — dep missing
        log.info("credentials: redis module not installed (%s); cache disabled",
                 exc)
        _redis_unavailable = True
        return None
    # Build via shared helper so this caller benefits from Sentinel-aware
    # master discovery when REDIS_SENTINEL_HOSTS is set. Falls back to
    # direct REDIS_HOST:REDIS_PORT for single-node dev. We override the
    # default 5s socket timeout with the tighter 1s the credentials cache
    # uses — credential lookups are blocking and a slow Redis must not
    # add user-visible latency. Cache fail-closed (latch) on first error.
    try:
        from platform_shared.redis import get_redis_client
        client = get_redis_client(decode_responses=True, socket_timeout=1.0)
        # Cheap liveness probe so first real request doesn't take the
        # full timeout when Redis is unreachable.
        client.ping()
    except Exception as exc:
        log.warning(
            "credentials: redis unreachable (%s); cache disabled",
            exc,
        )
        _redis_unavailable = True
        return None
    _redis_client = client
    return _redis_client


def reset_redis_client() -> None:
    """Drop the cached Redis client. Tests + operators only."""
    global _redis_client, _redis_unavailable
    _redis_client = None
    _redis_unavailable = False


# ─────────────────────────────────────────────────────────────────────────────
# Cache key shape
# ─────────────────────────────────────────────────────────────────────────────
def _cache_key(vendor: str, kind: str, field: str) -> str:
    return f"cred:{vendor}:{kind}:{field}"


# ─────────────────────────────────────────────────────────────────────────────
# Direct DB lookup — single integration, single field
# ─────────────────────────────────────────────────────────────────────────────
def _db_lookup(
    vendor: str,
    kind: str,
    field: str,
    timeout_s: float,
) -> Optional[Tuple[str, str]]:
    """Pull one (kind, field) value for one integration external_id.

    Returns ``(value, version)`` on success, where ``version`` is an
    isoformat ``updated_at`` timestamp (the credential row's, or the
    integrations row's for ``kind="config"``). Returns ``None`` if
    anything goes wrong or the value is blank / unconfigured. The
    version is used by ``get_credential`` to revalidate cached entries
    against the DB without refetching the (potentially large) value.
    """
    url = _resolve_db_url()
    if not url:
        return None
    try:
        import psycopg2
        import psycopg2.extras
    except Exception as exc:  # pragma: no cover
        log.warning("credentials: psycopg2 missing (%s); cannot read DB", exc)
        return None

    try:
        conn = psycopg2.connect(url, connect_timeout=int(max(1, timeout_s)))
    except Exception as exc:
        log.warning(
            "credentials: spm-db unreachable (%s); returning None for %s/%s/%s",
            exc, vendor, kind, field,
        )
        return None

    try:
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            if kind == "config":
                cur.execute(
                    """
                    SELECT COALESCE(config, '{}'::jsonb) -> %s AS v,
                           updated_at
                    FROM   integrations
                    WHERE  external_id = %s
                    """,
                    (field, vendor),
                )
                row = cur.fetchone()
                if not row or row["v"] in (None, ""):
                    return None
                v = row["v"]
                # JSONB scalar is already deserialised by psycopg2 — strings
                # come back wrapped, so unwrap; non-strings are stringified.
                value = v if isinstance(v, str) else str(v)
                version = row["updated_at"].isoformat() if row["updated_at"] else ""
                return value, version
            elif kind == "credential":
                cur.execute(
                    """
                    SELECT c.value_enc, c.is_configured, c.updated_at
                    FROM   integration_credentials c
                    JOIN   integrations i ON i.id = c.integration_id
                    WHERE  i.external_id = %s
                      AND  c.credential_type = %s
                    LIMIT  1
                    """,
                    (vendor, field),
                )
                row = cur.fetchone()
                if not row:
                    return None
                if not row["is_configured"] or not row["value_enc"]:
                    return None
                value = _decode_secret(row["value_enc"]) or None
                if not value:
                    return None
                version = row["updated_at"].isoformat() if row["updated_at"] else ""
                return value, version
            else:
                log.warning("credentials: unknown kind=%r (vendor=%s field=%s)",
                            kind, vendor, field)
                return None
    except Exception as exc:
        log.warning(
            "credentials: query failed (%s) for %s/%s/%s",
            exc, vendor, kind, field,
        )
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Cheap version check — used to revalidate cached entries past the
# FRESHNESS_S window without refetching the (potentially large) value.
# Single indexed lookup; no value transfer; no decryption.
# ─────────────────────────────────────────────────────────────────────────────
def _db_version_check(
    vendor: str,
    kind: str,
    field: str,
    timeout_s: float,
) -> Optional[str]:
    """Return the current ``updated_at`` for ``(vendor, kind, field)`` or None.

    None means the row is gone / unconfigured / DB unreachable. Caller
    distinguishes "stale and we know it" (mismatch with cached version)
    from "we cannot tell" (DB error) by ALSO checking whether the
    underlying connection succeeded — but the cheap path here treats
    None as "cannot confirm freshness", and the caller chooses to either
    serve cached without extending TTL (fail-soft) or to recheck via
    full ``_db_lookup`` (fail-closed).
    """
    url = _resolve_db_url()
    if not url:
        return None
    try:
        import psycopg2
        import psycopg2.extras
    except Exception:  # pragma: no cover
        return None
    try:
        conn = psycopg2.connect(url, connect_timeout=int(max(1, timeout_s)))
    except Exception as exc:
        log.warning("credentials: version-check connect failed (%s)", exc)
        return None
    try:
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            if kind == "credential":
                cur.execute(
                    """
                    SELECT c.updated_at
                    FROM   integration_credentials c
                    JOIN   integrations i ON i.id = c.integration_id
                    WHERE  i.external_id = %s
                      AND  c.credential_type = %s
                    LIMIT  1
                    """,
                    (vendor, field),
                )
            elif kind == "config":
                # For config we use the parent integration's updated_at,
                # which fires onupdate for any field change in config jsonb.
                cur.execute(
                    """
                    SELECT updated_at
                    FROM   integrations
                    WHERE  external_id = %s
                    """,
                    (vendor,),
                )
            else:
                return None
            row = cur.fetchone()
            if not row or not row["updated_at"]:
                return None
            return row["updated_at"].isoformat()
    except Exception as exc:
        log.warning("credentials: version-check query failed (%s)", exc)
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Cache value packing — JSON {"v": value, "ver": isoformat, "t": epoch_secs}.
# Old raw-string entries fail json.loads -> _unpack_cache returns None ->
# treated as a miss -> safe forward migration with no flush required.
# ─────────────────────────────────────────────────────────────────────────────
def _pack_cache(value: str, version: str) -> str:
    return json.dumps(
        {"v": value, "ver": version, "t": time.time()},
        separators=(",", ":"),
    )


def _unpack_cache(blob: object) -> Optional[Tuple[str, str, float]]:
    if not isinstance(blob, str):
        return None
    if not blob.startswith("{"):
        return None
    try:
        d = json.loads(blob)
    except Exception:
        return None
    if not isinstance(d, dict) or "v" not in d:
        return None
    return d["v"], str(d.get("ver", "")), float(d.get("t", 0.0))


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────
def get_credential(
    vendor: str,
    field: str = "api_key",
    kind: str = "credential",
    ttl: int = DEFAULT_TTL_S,
    freshness_s: int = DEFAULT_FRESHNESS_S,
    timeout_s: float = 3.0,
    default: Optional[str] = None,
) -> Optional[str]:
    """Return the live value for ``(vendor, kind, field)`` or ``default``.

    Lookup is **fail-closed on staleness**:

    1. Cache MISS (or unreadable) → full DB lookup, cache the new value.
    2. Cache HIT within ``freshness_s`` seconds of the last full read →
       return immediately, no DB hit. Hot path.
    3. Cache HIT older than ``freshness_s`` but still inside Redis TTL →
       cheap ``SELECT updated_at`` against spm-db.
       * Match → extend cache window, return cached value.
       * Mismatch → full refetch, recache, return new value.
       * DB error → serve cached (fail-soft) but DO NOT extend TTL,
         so the key naturally expires and the next reader retries.

    Misses (blank value / missing row / DB or Redis errors during full
    lookup) all return ``default`` and are NOT cached, so a
    freshly-configured credential becomes visible immediately.

    Parameters
    ----------
    vendor:
        ``integrations.external_id`` — e.g. ``"int-003"`` for Anthropic.
    field:
        ``credential_type`` (when kind="credential") or JSONB key
        inside ``integrations.config`` (when kind="config").
    kind:
        ``"credential"`` (default) or ``"config"``.
    ttl:
        Absolute Redis expiry in seconds. After this the cache entry
        is gone and a full lookup is forced. Default 30s.
    freshness_s:
        Trust-without-verify window in seconds. Past this we run a
        cheap version check against the DB before serving cached.
        Default 5s. Set to 0 to revalidate on every read; set to
        ``ttl`` to disable revalidation entirely (legacy behaviour).
    timeout_s:
        psycopg2 connect_timeout for both DB queries.
    default:
        Value returned when no live credential is available. Useful
        for migrating env-reads with a fallback to ``os.environ``:
            get_credential("int-003", default=os.getenv("ANTHROPIC_API_KEY"))
    """
    key = _cache_key(vendor, kind, field)
    r = _get_redis()

    # ── Try cache ─────────────────────────────────────────────────────────
    cached_value: Optional[str] = None
    cached_version: str = ""
    cached_age: float = 0.0
    if r is not None:
        try:
            blob = r.get(key)
        except Exception as exc:
            log.warning("credentials: redis GET failed (%s); falling through", exc)
            blob = None
        unpacked = _unpack_cache(blob) if blob is not None else None
        if unpacked is not None:
            cached_value, cached_version, cached_t = unpacked
            cached_age = max(0.0, time.time() - cached_t)
        elif blob is not None:
            # Legacy raw-string entry from before this refactor — drop it,
            # fall through to a full lookup that will recache as JSON.
            try:
                r.delete(key)
            except Exception:
                pass

    # ── Hot path: cache HIT inside freshness window ───────────────────────
    if cached_value is not None and cached_age <= max(0, freshness_s):
        return cached_value

    # ── Stale-but-cached: cheap version check ─────────────────────────────
    if cached_value is not None:
        live_version = _db_version_check(vendor, kind, field, timeout_s)
        if live_version is None:
            # Cannot confirm freshness (DB unreachable / row missing) —
            # serve the cached value but DO NOT extend TTL so the entry
            # expires naturally instead of getting pinned forever.
            return cached_value
        if live_version == cached_version and cached_version != "":
            # Still current — repack with fresh `t` and extend Redis TTL.
            if r is not None:
                try:
                    r.setex(key, max(1, int(ttl)),
                            _pack_cache(cached_value, cached_version))
                except Exception as exc:
                    log.warning(
                        "credentials: redis SETEX (revalidate) failed (%s)", exc,
                    )
            return cached_value
        # Version drift — fall through to full refetch.

    # ── Full DB lookup ────────────────────────────────────────────────────
    result = _db_lookup(vendor, kind, field, timeout_s)
    if result is None:
        # Couldn't fetch fresh value. If we have a cached value we already
        # returned it above (in the fail-soft branch). Otherwise → default.
        return default
    value, version = result
    if not value:
        return default

    # ── Cache successful read ─────────────────────────────────────────────
    if r is not None:
        try:
            r.setex(key, max(1, int(ttl)), _pack_cache(value, version))
        except Exception as exc:
            log.warning("credentials: redis SETEX failed (%s); skipping cache", exc)

    return value


def _env_to_triple(env_name: str) -> Optional[Tuple[str, str, str]]:
    """Resolve an env-var name to (vendor, kind, field) via ENV_EXPORT_MAP."""
    for ext_id, kind, key, name in ENV_EXPORT_MAP:
        if name == env_name:
            return ext_id, kind, key
    return None


def get_credential_by_env(
    env_name: str,
    ttl: int = DEFAULT_TTL_S,
    freshness_s: int = DEFAULT_FRESHNESS_S,
    timeout_s: float = 3.0,
    default: Optional[str] = None,
) -> Optional[str]:
    """Compatibility shim for the env-read migration.

    Looks up the (vendor, kind, field) triple bound to ``env_name`` in
    ``ENV_EXPORT_MAP`` and delegates to ``get_credential``.  Any env var
    not in the map (e.g. operator-only knobs like ``LOG_LEVEL``) is
    treated as a plain ``os.getenv`` so this is a safe drop-in
    replacement at every call site.

    Falls back to the live ``os.environ`` value when the DB lookup
    returns nothing — this preserves operator overrides and keeps
    local-dev with a hand-edited .env working.
    """
    triple = _env_to_triple(env_name)
    if triple is None:
        # Not a managed credential — return whatever env says.
        return os.environ.get(env_name, default if default is not None else "")
    vendor, kind, field = triple
    fallback = os.environ.get(env_name)
    if fallback is not None and fallback != "":
        # Operator-set value wins — same precedence rule as the old
        # hydrator's overwrite=False behaviour.
        effective_default = fallback
    else:
        effective_default = default if default is not None else ""
    return get_credential(
        vendor,
        field=field,
        kind=kind,
        ttl=ttl,
        freshness_s=freshness_s,
        timeout_s=timeout_s,
        default=effective_default,
    )


def invalidate_credential_cache(vendor: str) -> int:
    """DELETE every ``cred:{vendor}:*`` key in Redis.

    Called by the configure endpoint after a successful write so the
    very next request to any consumer reads the new value without
    waiting for TTL expiry. Best-effort — failure to invalidate is
    logged but not raised: the worst case is a TTL-window of stale
    reads, not a 500.

    Returns
    -------
    int
        Number of keys deleted (0 if Redis unavailable or no matches).
    """
    r = _get_redis()
    if r is None:
        return 0
    pattern = f"cred:{vendor}:*"
    deleted = 0
    try:
        # SCAN rather than KEYS so a future Redis with thousands of
        # cached creds doesn't block the event loop.  count=100 is
        # plenty: a single vendor never has more than ~5 fields.
        for key in r.scan_iter(match=pattern, count=100):
            try:
                deleted += int(r.delete(key) or 0)
            except Exception as exc:
                log.warning("credentials: DEL %s failed (%s)", key, exc)
    except Exception as exc:
        log.warning(
            "credentials: SCAN %s failed (%s); cache may serve stale "
            "values for up to TTL seconds",
            pattern, exc,
        )
        return 0
    if deleted:
        log.info("credentials: invalidated %d cache entries for vendor=%s",
                 deleted, vendor)
    return deleted


__all__ = [
    "get_credential",
    "get_credential_by_env",
    "invalidate_credential_cache",
    "reset_redis_client",
]
