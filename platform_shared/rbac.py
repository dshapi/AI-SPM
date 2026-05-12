"""
platform_shared/rbac.py
────────────────────────
Centralised Role-Based Access Control engine for all AI-SPM services.

Permission matrix (19 permissions, 4 human roles)
──────────────────────────────────────────────────
  Permission           Viewer  Auditor  SecAnalyst  Admin
  ─────────────────── ─────── ──────── ─────────── ─────
  session.read           ✓       ✓         ✓          ⊞
  session.write          ·       ·         ✓          ⊞
  session.override       ·       ·         ✓          ⊞
  agent.invoke           ·       ✓         ✓          ⊞
  agent.read             ✓       ✓         ✓          ⊞
  agent.write            ·       ✓         ✓          ⊞
  agent.manage           ·       ✓         ✓          ⊞
  model.read             ✓       ✓         ✓          ⊞
  model.write            ·       ✓         ·          ⊞
  model.delete           ·       ✓         ·          ⊞
  integration.read       ✓       ✓         ✓          ⊞
  integration.write      ·       ·         ·          ⊞
  compliance.read        ✓       ✓         ✓          ⊞
  compliance.write       ·       ✓         ·          ⊞
  posture.read           ✓       ✓         ✓          ⊞
  posture.write          ·       ✓         ·          ⊞
  chat.invoke            ✓       ✓         ✓          ⊞
  audit.read             ✓       ✓         ✓          ⊞
  audit.write            ·       ✓         ·          ⊞

Admin (⊞) is a super-role that holds all permissions and cannot be
modified via the RBAC matrix UI.

Service-to-service calls use SPM_SERVICE_JWT which carries admin-equivalent
claims — they bypass the matrix intentionally and are secured at the network
layer by Istio. The matrix applies to human user JWTs only.

Keycloak role names use the spm: prefix; the engine accepts both prefixed
and plain forms (e.g. "spm:auditor" and "auditor" are equivalent).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Set

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)


# ─────────────────────────────────────────────────────────────────────────────
# IdentityContext  (canonical caller representation, one per request)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class IdentityContext:
    """
    Canonical representation of an authenticated caller.
    Created once per request by get_current_identity(); never mutated after.
    """

    user_id:    str
    tenant_id:  Optional[str]
    email:      Optional[str]
    roles:      List[str] = field(default_factory=list)
    groups:     List[str] = field(default_factory=list)
    env:        str        = ""
    raw_claims: dict       = field(default_factory=dict)

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

    def __repr__(self) -> str:
        return (
            f"IdentityContext(user_id={self.user_id!r}, "
            f"roles={self.roles}, groups={self.groups}, env={self.env!r})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Token decoder + identity builder  (shared across all services)
# ─────────────────────────────────────────────────────────────────────────────

def _decode_token(raw_token: str) -> dict:
    if not raw_token:
        return {}
    try:
        from platform_shared.keycloak_auth import decode_token
        audience = os.environ.get("JWT_AUDIENCE", "aispm-ui")
        issuer   = os.environ.get("JWT_ISSUER",   "http://keycloak.local:8180/realms/aispm")
        return decode_token(raw_token, audience=audience, issuer=issuer)
    except Exception as exc:
        logger.warning("auth: JWT decode failed: %s", exc)
        return {}


def _build_identity(claims: dict) -> IdentityContext:
    """Map raw JWT claims → IdentityContext.

    Role extraction precedence:
      1. Flat 'roles' array           — used by mock/service tokens
      2. Keycloak 'realm_access.roles'— used when fronted by Keycloak
      3. OAuth2 'scp' space-delimited — used by some IdPs
    """
    roles: List[str] = []
    if "roles" in claims:
        roles = [str(r) for r in claims["roles"]]
    elif "realm_access" in claims:
        roles = claims["realm_access"].get("roles", [])
    elif "scp" in claims:
        roles = str(claims["scp"]).split()

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


async def get_current_identity(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> IdentityContext:
    """FastAPI dependency: extract and validate the caller's identity.

    Raises:
      401 UNAUTHORIZED — Authorization header absent or token invalid.
      403 FORBIDDEN    — Account is suspended.
    """
    trace_id: str = getattr(request.state, "trace_id", "?")

    if credentials is None:
        logger.warning("auth: missing Bearer token trace=%s path=%s",
                       trace_id, request.url.path)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
            detail={
                "code":     "MISSING_TOKEN",
                "message":  "Authorization: Bearer <token> header is required.",
                "trace_id": trace_id,
            },
        )

    claims   = _decode_token(credentials.credentials)
    identity = _build_identity(claims)

    if not identity.user_id or identity.user_id == "anonymous":
        logger.warning("auth: rejecting anonymous/empty identity trace=%s path=%s",
                       trace_id, request.url.path)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
            detail={
                "code":     "INVALID_TOKEN",
                "message":  "Token is missing, expired, or failed signature validation.",
                "trace_id": trace_id,
            },
        )

    if identity.is_suspended():
        logger.warning("auth: suspended account user=%s trace=%s",
                       identity.user_id, trace_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code":     "ACCOUNT_SUSPENDED",
                "message":  "This account has been suspended.",
                "user_id":  identity.user_id,
                "trace_id": trace_id,
            },
        )

    request.state.identity = identity

    logger.info(
        "auth: OK user=%s roles=%s groups=%s env=%s trace=%s",
        identity.user_id, identity.roles, identity.groups,
        identity.env, trace_id,
    )
    return identity


# ─────────────────────────────────────────────────────────────────────────────
# Permissions
# ─────────────────────────────────────────────────────────────────────────────

class Permission(str, Enum):
    """All 19 platform permissions."""

    SESSION_READ        = "session.read"
    SESSION_WRITE       = "session.write"
    SESSION_OVERRIDE    = "session.override"

    AGENT_INVOKE        = "agent.invoke"
    AGENT_READ          = "agent.read"
    AGENT_WRITE         = "agent.write"
    AGENT_MANAGE        = "agent.manage"

    MODEL_READ          = "model.read"
    MODEL_WRITE         = "model.write"
    MODEL_DELETE        = "model.delete"

    INTEGRATION_READ    = "integration.read"
    INTEGRATION_WRITE   = "integration.write"

    COMPLIANCE_READ     = "compliance.read"
    COMPLIANCE_WRITE    = "compliance.write"

    POSTURE_READ        = "posture.read"
    POSTURE_WRITE       = "posture.write"

    CHAT_INVOKE         = "chat.invoke"

    AUDIT_READ          = "audit.read"
    AUDIT_WRITE         = "audit.write"

    def __str__(self) -> str:
        return self.value


# ─────────────────────────────────────────────────────────────────────────────
# Permission matrix
# ─────────────────────────────────────────────────────────────────────────────

# Viewer — all read permissions + chat.invoke
_VIEWER_PERMS: FrozenSet[Permission] = frozenset({
    Permission.SESSION_READ,
    Permission.AGENT_READ,
    Permission.MODEL_READ,
    Permission.INTEGRATION_READ,
    Permission.COMPLIANCE_READ,
    Permission.POSTURE_READ,
    Permission.CHAT_INVOKE,
    Permission.AUDIT_READ,
})

# Auditor — viewer perms + full agent/model/compliance/posture/audit write
_AUDITOR_PERMS: FrozenSet[Permission] = _VIEWER_PERMS | frozenset({
    Permission.AGENT_INVOKE,
    Permission.AGENT_WRITE,
    Permission.AGENT_MANAGE,
    Permission.MODEL_WRITE,
    Permission.MODEL_DELETE,
    Permission.COMPLIANCE_WRITE,
    Permission.POSTURE_WRITE,
    Permission.AUDIT_WRITE,
})

# Security Analyst — viewer perms + full session + agent invoke/write/manage
_SEC_ANALYST_PERMS: FrozenSet[Permission] = _VIEWER_PERMS | frozenset({
    Permission.SESSION_WRITE,
    Permission.SESSION_OVERRIDE,
    Permission.AGENT_INVOKE,
    Permission.AGENT_WRITE,
    Permission.AGENT_MANAGE,
})

_ROLE_PERMISSIONS: Dict[str, FrozenSet[Permission]] = {
    # Keycloak-prefixed names (canonical)
    "spm:viewer":           _VIEWER_PERMS,
    "spm:auditor":          _AUDITOR_PERMS,
    "spm:security-analyst": _SEC_ANALYST_PERMS,
    # Plain aliases (accepted from service tokens / legacy JWTs)
    "viewer":               _VIEWER_PERMS,
    "auditor":              _AUDITOR_PERMS,
    "security-analyst":     _SEC_ANALYST_PERMS,
    "security_analyst":     _SEC_ANALYST_PERMS,
    # Super-roles
    "admin":                frozenset(Permission),
    "spm:admin":            frozenset(Permission),
}

_ADMIN_ROLES: FrozenSet[str] = frozenset({"admin", "spm:admin"})


# ─────────────────────────────────────────────────────────────────────────────
# Core authorize() — pure function, no side-effects
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AuthzResult:
    granted:    bool
    permission: Permission
    user_id:    str
    reason:     str


def authorize(identity: IdentityContext, permission: Permission) -> AuthzResult:
    """Evaluate whether ``identity`` holds ``permission``."""

    if identity.role_set() & _ADMIN_ROLES:
        matched = next(iter(identity.role_set() & _ADMIN_ROLES))
        return AuthzResult(
            granted=True, permission=permission,
            user_id=identity.user_id,
            reason=f"Granted via admin role '{matched}'.",
        )

    effective: Set[Permission] = set()
    matched_roles: List[str] = []

    for role in identity.roles:
        role_perms = _ROLE_PERMISSIONS.get(role, frozenset())
        if role_perms:
            effective |= role_perms
            matched_roles.append(role)

    granted = permission in effective

    if granted:
        reason = f"Granted via roles={matched_roles}."
    else:
        reason = (
            f"Permission '{permission}' not granted. "
            f"Caller roles={identity.roles or ['(none)']}. "
            f"Effective permissions={sorted(p.value for p in effective) or ['(none)']}."
        )

    return AuthzResult(
        granted=granted, permission=permission,
        user_id=identity.user_id, reason=reason,
    )


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI dependency factory
# ─────────────────────────────────────────────────────────────────────────────
# WHY a factory returning a plain async function (not a callable class):
# FastAPI resolves annotation forward refs via call.__globals__. Plain
# functions carry __globals__; callable instances do not. With
# `from __future__ import annotations` all annotations are ForwardRefs, so
# using a callable class would cause PydanticUndefinedAnnotation at startup.
# ─────────────────────────────────────────────────────────────────────────────

def _make_rbac_dependency(permission: Permission):
    """Return a FastAPI async dependency that enforces ``permission``."""

    async def _check_permission(
        request: Request,
        identity: IdentityContext = Depends(get_current_identity),
    ) -> IdentityContext:
        trace_id: str = getattr(request.state, "trace_id", "?")
        result = authorize(identity, permission)

        logger.info(
            "rbac: user=%s permission=%s granted=%s trace=%s | %s",
            identity.user_id, permission.value,
            result.granted, trace_id, result.reason,
        )

        if not result.granted:
            qualifying_roles = [
                role for role, perms in _ROLE_PERMISSIONS.items()
                if permission in perms
            ]
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code":       "PERMISSION_DENIED",
                    "message":    f"You do not have the '{permission}' permission.",
                    "permission": permission.value,
                    "user_id":    identity.user_id,
                    "roles":      identity.roles,
                    "hint":       f"Roles that grant '{permission}': {qualifying_roles}.",
                    "trace_id":   trace_id,
                },
            )

        return identity

    _check_permission.__name__ = f"require_{permission.name.lower()}"
    return _check_permission


def require(permission: Permission):
    """Public alias for _make_rbac_dependency — use this in route files."""
    return _make_rbac_dependency(permission)


# ─────────────────────────────────────────────────────────────────────────────
# Pre-built dependency functions  (import directly in router files)
# ─────────────────────────────────────────────────────────────────────────────

require_session_read        = _make_rbac_dependency(Permission.SESSION_READ)
require_session_write       = _make_rbac_dependency(Permission.SESSION_WRITE)
require_session_override    = _make_rbac_dependency(Permission.SESSION_OVERRIDE)

require_agent_invoke        = _make_rbac_dependency(Permission.AGENT_INVOKE)
require_agent_read          = _make_rbac_dependency(Permission.AGENT_READ)
require_agent_write         = _make_rbac_dependency(Permission.AGENT_WRITE)
require_agent_manage        = _make_rbac_dependency(Permission.AGENT_MANAGE)

require_model_read          = _make_rbac_dependency(Permission.MODEL_READ)
require_model_write         = _make_rbac_dependency(Permission.MODEL_WRITE)
require_model_delete        = _make_rbac_dependency(Permission.MODEL_DELETE)

require_integration_read    = _make_rbac_dependency(Permission.INTEGRATION_READ)
require_integration_write   = _make_rbac_dependency(Permission.INTEGRATION_WRITE)

require_compliance_read     = _make_rbac_dependency(Permission.COMPLIANCE_READ)
require_compliance_write    = _make_rbac_dependency(Permission.COMPLIANCE_WRITE)

require_posture_read        = _make_rbac_dependency(Permission.POSTURE_READ)
require_posture_write       = _make_rbac_dependency(Permission.POSTURE_WRITE)

require_chat_invoke         = _make_rbac_dependency(Permission.CHAT_INVOKE)

require_audit_read          = _make_rbac_dependency(Permission.AUDIT_READ)
require_audit_write         = _make_rbac_dependency(Permission.AUDIT_WRITE)


# ─────────────────────────────────────────────────────────────────────────────
# Utility
# ─────────────────────────────────────────────────────────────────────────────

def effective_permissions(identity: IdentityContext) -> List[str]:
    """Return sorted list of permission strings the identity currently holds."""
    if identity.role_set() & _ADMIN_ROLES:
        return sorted(p.value for p in Permission)

    effective: Set[Permission] = set()
    for role in identity.roles:
        effective |= _ROLE_PERMISSIONS.get(role, frozenset())

    return sorted(p.value for p in effective)
