"""
Shared Keycloak JWKS-backed JWT validator.

Usage:
    from platform_shared.keycloak_auth import decode_token

    claims = decode_token(raw_token,
                          audience=settings.JWT_AUDIENCE,
                          issuer=settings.JWT_ISSUER)
"""
from __future__ import annotations

import functools
import os
from typing import Dict

import requests
from jose import jwt, JWTError


def _jwks_url() -> str:
    base = os.environ.get("KEYCLOAK_JWKS_URL", "").rstrip("/")
    if base:
        return base
    kc = os.environ.get("KEYCLOAK_URL", "http://keycloak.local:8180").rstrip("/")
    realm = os.environ.get("KEYCLOAK_REALM", "aispm")
    return f"{kc}/realms/{realm}/protocol/openid-connect/certs"


@functools.lru_cache(maxsize=1)
def _fetch_jwks() -> Dict:
    url = _jwks_url()
    resp = requests.get(url, timeout=5)
    resp.raise_for_status()
    return resp.json()


def decode_token(raw_token: str, *, audience: str, issuer: str) -> Dict:
    """
    Validate `raw_token` against Keycloak's JWKS endpoint.

    - Verifies RS256 signature using JWKS
    - Enforces `aud` == audience
    - Enforces `iss` == issuer
    - Enforces `exp` not expired
    - alg=none tokens are rejected

    Returns claims dict with extra top-level `roles` list from `realm_access.roles`.
    Raises jose.JWTError (or subclass) on any validation failure.
    """
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
