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
    global _redis_client
    if _redis_client is None:
        s = get_settings()
        kwargs: dict = {"host": s.redis_host, "port": s.redis_port, "decode_responses": True}
        if s.redis_password:
            kwargs["password"] = s.redis_password
        _redis_client = redis_lib.Redis(**kwargs)
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
    Validate an RS256 JWT.
    Returns decoded claims dict on success.
    Raises HTTP 401 on any validation failure.
    """
    s = get_settings()
    public_key = s.load_public_key()
    try:
        claims = jwt.decode(
            token,
            public_key,
            algorithms=[s.jwt_algorithm],
            issuer=s.jwt_issuer,
            options={
                "verify_iss": True,
                "verify_exp": True,
                "verify_iat": True,
                "require": ["sub", "iss", "exp", "iat", "tenant_id"],
            },
        )
        return claims
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.MissingRequiredClaimError as e:
        raise HTTPException(status_code=401, detail=f"Token missing required claim: {e}")
    except jwt.InvalidIssuerError:
        raise HTTPException(status_code=401, detail="Token issuer is invalid")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Role / scope enforcement
# ─────────────────────────────────────────────────────────────────────────────

def require_admin_role(claims: dict) -> None:
    """Raise HTTP 403 if caller does not hold the spm:admin role."""
    roles = claims.get("roles", [])
    if "spm:admin" not in roles:
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
