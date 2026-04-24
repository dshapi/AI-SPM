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

import logging
import os
from typing import Optional, Tuple

from .integration_config import (
    ENV_EXPORT_MAP,
    _decode_secret,
    _resolve_db_url,
)

log = logging.getLogger("platform_shared.credentials")

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
    host = os.getenv("REDIS_HOST", "redis")
    port = int(os.getenv("REDIS_PORT", "6379") or "6379")
    password = os.getenv("REDIS_PASSWORD") or None
    try:
        client = redis_lib.Redis(
            host=host,
            port=port,
            password=password,
            decode_responses=True,
            socket_timeout=1.0,
            socket_connect_timeout=1.0,
        )
        # Cheap liveness probe so first real request doesn't take the
        # full timeout when Redis is unreachable.
        client.ping()
    except Exception as exc:
        log.warning(
            "credentials: redis at %s:%s unreachable (%s); cache disabled",
            host, port, exc,
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
) -> Optional[str]:
    """Pull one (kind, field) value for one integration external_id.

    Returns None if anything goes wrong or the value is blank / unconfigured.
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
                    SELECT COALESCE(config, '{}'::jsonb) -> %s AS v
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
                if isinstance(v, str):
                    return v
                return str(v)
            elif kind == "credential":
                cur.execute(
                    """
                    SELECT c.value_enc, c.is_configured
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
                return _decode_secret(row["value_enc"]) or None
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
# Public API
# ─────────────────────────────────────────────────────────────────────────────
def get_credential(
    vendor: str,
    field: str = "api_key",
    kind: str = "credential",
    ttl: int = 30,
    timeout_s: float = 3.0,
    default: Optional[str] = None,
) -> Optional[str]:
    """Return the live value for ``(vendor, kind, field)`` or ``default``.

    Lookup order: Redis cache → spm-db. Successful reads are cached
    with the supplied TTL. Misses (blank value / missing row / DB or
    Redis errors) all return ``default`` and are NOT cached, so a
    freshly-configured credential becomes visible to the next caller
    immediately even without explicit invalidation.

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
        Cache TTL in seconds. 30s by default — small enough that key
        rotations propagate quickly, large enough to absorb burst
        traffic without hammering Postgres.
    timeout_s:
        psycopg2 connect_timeout for the fallback DB query.
    default:
        Value returned when no live credential is available. Useful
        for migrating env-reads with a fallback to ``os.environ``:
            get_credential("int-003", default=os.getenv("ANTHROPIC_API_KEY"))
    """
    key = _cache_key(vendor, kind, field)

    # ── Try cache ─────────────────────────────────────────────────────────
    r = _get_redis()
    if r is not None:
        try:
            cached = r.get(key)
        except Exception as exc:
            log.warning("credentials: redis GET failed (%s); falling through", exc)
            cached = None
        if cached is not None:
            return cached

    # ── Fall back to DB ───────────────────────────────────────────────────
    value = _db_lookup(vendor, kind, field, timeout_s)
    if value is None or value == "":
        return default

    # ── Cache successful read ─────────────────────────────────────────────
    if r is not None:
        try:
            r.setex(key, max(1, int(ttl)), value)
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
    ttl: int = 30,
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
