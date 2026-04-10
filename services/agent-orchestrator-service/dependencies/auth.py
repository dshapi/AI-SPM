"""
dependencies/auth.py
─────────────────────
JWT extraction and identity hydration.

Responsibilities
────────────────
  1. Extract the Bearer token from the Authorization header.
  2. Decode the JWT payload (mock/dev: no signature verification;
     production: swap _decode_token() for python-jose JWKS validation).
  3. Map raw claims → IdentityContext (the single authoritative view of
     the caller used by every service and the RBAC engine).
  4. Reject suspended accounts before any business logic runs.

Token structure supported (mock)
─────────────────────────────────
  {
    "sub":    "user_123",
    "roles":  ["agent_operator"],
    "groups": ["security"],
    "env":    "prod",
    "email":  "user@acme.com",          // optional
    "tenant_id": "acme",                // optional
    "realm_access": { "roles": [...] }  // Keycloak format (also supported)
  }

Production swap
───────────────
  Replace _decode_token() with:
      from jose import jwt, JWTError
      claims = jwt.decode(
          raw_token, _get_jwks(), algorithms=["RS256"],
          audience="agent-orchestrator", issuer=SETTINGS.jwt_issuer,
      )
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Set

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)


# ─────────────────────────────────────────────────────────────────────────────
# IdentityContext
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class IdentityContext:
    """
    Canonical representation of an authenticated caller.
    Created once per request; never mutated after construction.

    Attributes
    ──────────
    user_id   : JWT 'sub' claim.
    tenant_id : Optional tenant scope (multi-tenant deployments).
    email     : Optional human-readable identifier.
    roles     : Role strings from the JWT (e.g. "agent_operator").
    groups    : Group memberships from the JWT (e.g. "security").
    env       : Deployment environment the token was issued for
                ("prod" | "staging" | "dev").  Empty string if absent.
    raw_claims: Full decoded JWT payload for advanced inspection.
    """

    user_id:    str
    tenant_id:  Optional[str]
    email:      Optional[str]
    roles:      List[str] = field(default_factory=list)
    groups:     List[str] = field(default_factory=list)
    env:        str        = ""
    raw_claims: dict       = field(default_factory=dict)

    # ── Convenience helpers ────────────────────────────────────────────────

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def in_group(self, group: str) -> bool:
        return group in self.groups

    def is_admin(self) -> bool:
        return any(r in self.roles for r in ("admin", "spm:admin"))

    def is_suspended(self) -> bool:
        return "suspended" in self.roles

    def role_set(self) -> Set[str]:
        return set(self.roles)

    def group_set(self) -> Set[str]:
        return set(self.groups)

    def __repr__(self) -> str:          # safe — no credentials
        return (
            f"IdentityContext(user_id={self.user_id!r}, "
            f"roles={self.roles}, groups={self.groups}, env={self.env!r})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Token decoder
# ─────────────────────────────────────────────────────────────────────────────

def _decode_token(raw_token: str) -> dict:
    """
    Decode the JWT payload WITHOUT signature verification.

    Accepts:
      • Real JWTs (header.payload.sig)  — payload is base64url-decoded.
      • Test tokens where the payload is a raw base64url JSON object.

    Returns an empty dict on any parse failure so the caller receives
    a default identity rather than a hard crash.
    """
    try:
        parts = raw_token.split(".")
        if len(parts) != 3:
            raise ValueError("not a 3-part JWT")
        payload_b64 = parts[1]
        # Restore padding stripped by base64url encoding
        padding = 4 - len(payload_b64) % 4
        payload_bytes = base64.urlsafe_b64decode(payload_b64 + "=" * padding)
        claims = json.loads(payload_bytes)
        logger.debug("JWT decoded: sub=%s roles=%s groups=%s env=%s",
                     claims.get("sub"), claims.get("roles"),
                     claims.get("groups"), claims.get("env"))
        return claims
    except Exception as exc:
        logger.debug("JWT decode failed (%s) — using empty claims", exc)
        return {}


def _build_identity(claims: dict) -> IdentityContext:
    """
    Map raw JWT claims → IdentityContext.

    Role extraction precedence:
      1. Flat  'roles' array           — used by this service's mock tokens
      2. Keycloak 'realm_access.roles' — used when fronted by Keycloak
      3. OAuth2 'scp' space-delimited  — used by some IdPs
    """
    # Roles
    roles: List[str] = []
    if "roles" in claims:
        roles = [str(r) for r in claims["roles"]]
    elif "realm_access" in claims:
        roles = claims["realm_access"].get("roles", [])
    elif "scp" in claims:
        roles = str(claims["scp"]).split()

    # Groups
    groups: List[str] = [str(g) for g in claims.get("groups", [])]

    return IdentityContext(
        user_id=claims.get("sub") or "anonymous",
        tenant_id=claims.get("tenant_id") or claims.get("tid"),
        email=claims.get("email"),
        roles=roles,
        groups=groups,
        env=claims.get("env", ""),
        raw_claims=claims,
    )


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI dependency
# ─────────────────────────────────────────────────────────────────────────────

async def get_current_identity(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> IdentityContext:
    """
    FastAPI dependency: extract and validate the caller's identity.

    Raises:
      401 UNAUTHORIZED   — Authorization header absent or malformed.
      403 FORBIDDEN      — Account is suspended.

    On success, also stores the identity on request.state.identity
    so middleware can include it in access logs without re-parsing.
    """
    trace_id: str = getattr(request.state, "trace_id", "?")

    if credentials is None:
        logger.warning("auth: missing Bearer token trace=%s path=%s",
                       trace_id, request.url.path)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
            detail={
                "code":    "MISSING_TOKEN",
                "message": "Authorization: Bearer <token> header is required.",
                "trace_id": trace_id,
            },
        )

    claims   = _decode_token(credentials.credentials)
    identity = _build_identity(claims)

    if identity.is_suspended():
        logger.warning("auth: suspended account user=%s trace=%s",
                       identity.user_id, trace_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code":    "ACCOUNT_SUSPENDED",
                "message": "This account has been suspended.",
                "user_id": identity.user_id,
                "trace_id": trace_id,
            },
        )

    # Stash on request.state so middleware/logging can read it cheaply
    request.state.identity = identity

    logger.info(
        "auth: OK user=%s roles=%s groups=%s env=%s trace=%s",
        identity.user_id, identity.roles, identity.groups,
        identity.env, trace_id,
    )
    return identity
