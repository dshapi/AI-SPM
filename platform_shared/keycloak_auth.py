"""
Shared Keycloak JWKS-backed JWT validator.

Usage:
    from platform_shared.keycloak_auth import decode_token

    claims = decode_token(raw_token,
                          audience=settings.JWT_AUDIENCE,
                          issuer=settings.JWT_ISSUER)
"""
from __future__ import annotations

import os
import time
import threading
from typing import Dict

import requests
from jose import jwt, JWTError

# JWKS are cached for 5 minutes. After Keycloak restarts (e.g. during
# bootstrap), the new signing keys are picked up within one TTL window
# without requiring a pod restart.
_JWKS_TTL = 300  # seconds
_jwks_cache: Dict | None = None
_jwks_fetched_at: float = 0.0
_jwks_lock = threading.Lock()


def _jwks_url() -> str:
    base = os.environ.get("KEYCLOAK_JWKS_URL", "").rstrip("/")
    if base:
        return base
    kc = os.environ.get("KEYCLOAK_URL", "http://keycloak.local:8180").rstrip("/")
    realm = os.environ.get("KEYCLOAK_REALM", "aispm")
    return f"{kc}/realms/{realm}/protocol/openid-connect/certs"


def _fetch_jwks() -> Dict:
    global _jwks_cache, _jwks_fetched_at
    now = time.monotonic()
    # Fast path: cache is fresh — no lock needed (reading two globals is
    # effectively atomic on CPython's GIL, and a stale read just causes
    # one extra fetch which is harmless).
    if _jwks_cache is not None and (now - _jwks_fetched_at) < _JWKS_TTL:
        return _jwks_cache
    with _jwks_lock:
        # Re-check inside the lock in case another thread already refreshed.
        now = time.monotonic()
        if _jwks_cache is not None and (now - _jwks_fetched_at) < _JWKS_TTL:
            return _jwks_cache
        url = _jwks_url()
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        _jwks_cache = resp.json()
        _jwks_fetched_at = now
    return _jwks_cache


def _invalidate_jwks_cache() -> None:
    """Force the next decode_token call to re-fetch JWKS. Useful in tests."""
    global _jwks_cache, _jwks_fetched_at
    with _jwks_lock:
        _jwks_cache = None
        _jwks_fetched_at = 0.0


def decode_token(raw_token: str, *, audience: str, issuer: str) -> Dict:
    """
    Validate `raw_token` against Keycloak's JWKS endpoint.

    - Verifies RS256 signature using JWKS
    - Enforces `aud` == audience
    - Enforces `iss` == issuer
    - Enforces `exp` not expired
    - alg=none tokens are rejected
    - On signature failure, invalidates the JWKS cache and retries once
      (handles Keycloak key rotation without a pod restart)

    Returns claims dict with extra top-level `roles` list from `realm_access.roles`.
    Raises jose.JWTError (or subclass) on any validation failure.
    """
    jwks = _fetch_jwks()
    try:
        claims = jwt.decode(
            raw_token,
            jwks,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
            options={"verify_exp": True, "verify_aud": True, "verify_iss": True},
        )
    except JWTError:
        # Signature mismatch can mean Keycloak rotated its keys since the
        # last cache fill. Invalidate and retry once with fresh JWKS.
        _invalidate_jwks_cache()
        jwks = _fetch_jwks()
        claims = jwt.decode(
            raw_token,
            jwks,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
            options={"verify_exp": True, "verify_aud": True, "verify_iss": True},
        )
    realm_roles = claims.get("realm_access", {}).get("roles", [])
    claims["roles"] = realm_roles
    return claims
