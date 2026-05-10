"""
Security primitives — JWT validation (RS256), rate limiting, role enforcement.
"""
from __future__ import annotations
import time
import redis as redis_lib
import jwt
from fastapi import HTTPException, Request
from platform_shared.config import get_settings

_redis_client: redis_lib.Redis | None = None


def _get_redis() -> redis_lib.Redis:
    """Lazily-cached Redis client used by the rate limiter.

    Body delegates to platform_shared.redis.get_redis_client() so this
    code path uses Sentinel-aware master discovery when REDIS_SENTINEL_HOSTS
    is set (HA prod) and falls back to direct REDIS_HOST:REDIS_PORT
    otherwise (single-node dev). Replaces the previous direct
    `redis_lib.Redis(host=...)` construction that pinned every caller
    to the haproxy-based redis-master Service.
    """
    global _redis_client
    if _redis_client is None:
        from platform_shared.redis import get_redis_client
        _redis_client = get_redis_client(decode_responses=True)
    return _redis_client


# ─────────────────────────────────────────────────────────────────────────────
# Token extraction
# ─────────────────────────────────────────────────────────────────────────────

def extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    parts = authorization.split(maxsplit=1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authorization header must be 'Bearer <token>'")
    return parts[1].strip()


# ─────────────────────────────────────────────────────────────────────────────
# JWT validation
# ─────────────────────────────────────────────────────────────────────────────

def validate_jwt_token(token: str) -> dict:
    """
    Validate an RS256 JWT issued by Keycloak.
    Returns decoded claims dict on success.
    Raises HTTP 401 on any validation failure.

    Implementation: delegates to platform_shared.keycloak_auth.decode_token
    which fetches Keycloak's JWKS (rotating set of RSA public keys) and
    verifies signature, audience, issuer, and expiry. The previous
    implementation used a STATIC local public key file (/keys/public.pem)
    that didn't match Keycloak's signing key, so every Keycloak-issued
    token failed signature verification with 401.

    Audience and issuer are read from JWT_AUDIENCE / JWT_ISSUER env vars
    (set in the platform-env ConfigMap), with the same defaults as the
    rest of the platform.
    """
    import os
    from platform_shared.keycloak_auth import decode_token

    audience = os.environ.get("JWT_AUDIENCE", "aispm-ui")
    issuer   = os.environ.get("JWT_ISSUER")
    if not issuer:
        # Last-resort fallback if env var is unset — match agent-orchestrator
        # default so the misconfiguration mode is uniform across services.
        issuer = "http://keycloak.local:8180/realms/aispm"

    try:
        return decode_token(token, audience=audience, issuer=issuer)
    except Exception as exc:
        # decode_token raises a single Exception type (jose.JWTError or its
        # subclasses, plus network failures from JWKS fetch). Collapse them
        # all into a 401 with the upstream message — operationally clearer
        # than guessing whether it was signature/aud/iss/exp/network.
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Role / scope enforcement
# ─────────────────────────────────────────────────────────────────────────────

def require_admin_role(claims: dict) -> None:
    """Raise HTTP 403 if caller does not hold the spm:admin or admin role.

    Reads roles from BOTH locations because Keycloak issues realm roles
    under `realm_access.roles` (nested), while older self-issued tokens
    flatten them onto `roles` at the top level. Checking both keeps this
    helper compatible with both issuance shapes.
    """
    roles = list(claims.get("roles") or [])
    roles += list(claims.get("realm_access", {}).get("roles") or [])
    if "spm:admin" not in roles and "admin" not in roles:
        raise HTTPException(
            status_code=403,
            detail="Operation requires spm:admin role",
        )


def require_scope(claims: dict, scope: str) -> None:
    """Raise HTTP 403 if caller does not hold the required scope."""
    scopes = claims.get("scopes", [])
    if scope not in scopes:
        raise HTTPException(
            status_code=403,
            detail=f"Operation requires scope: {scope}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Rate limiting
# ─────────────────────────────────────────────────────────────────────────────

def check_rate_limit(tenant_id: str, user_id: str) -> None:
    """
    Sliding-window token bucket: {rate_limit_rpm} requests per 60s per user.
    Uses Redis sorted set keyed by timestamp. Thread-safe via MULTI/EXEC pipeline.
    Raises HTTP 429 if limit exceeded.
    """
    s = get_settings()
    r = _get_redis()
    key = f"rl:{tenant_id}:{user_id}"
    now = time.time()
    window_start = now - 60.0

    pipe = r.pipeline()
    pipe.zremrangebyscore(key, "-inf", window_start)
    pipe.zcard(key)
    pipe.execute()

    count = r.zcard(key)
    if count >= s.rate_limit_rpm:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Max {s.rate_limit_rpm} requests/minute.",
            headers={"Retry-After": "60"},
        )
    # Add current request with unique member to handle same-second bursts
    member = f"{now:.6f}"
    r.zadd(key, {member: now})
    r.expire(key, 120)


def get_rate_limit_status(tenant_id: str, user_id: str) -> dict:
    """Return current rate limit counters for a user (for debugging/monitoring)."""
    s = get_settings()
    r = _get_redis()
    key = f"rl:{tenant_id}:{user_id}"
    now = time.time()
    r.zremrangebyscore(key, "-inf", now - 60.0)
    count = r.zcard(key)
    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "requests_in_window": count,
        "limit": s.rate_limit_rpm,
        "remaining": max(0, s.rate_limit_rpm - count),
    }
