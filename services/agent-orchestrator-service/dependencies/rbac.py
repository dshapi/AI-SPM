"""
dependencies/rbac.py
─────────────────────
Role-Based Access Control engine.

Concepts
────────
  Permission  — a (action, resource) pair, e.g. ("invoke", "agent").
  Role        — a named collection of permissions, e.g. "agent_operator".
  Group       — a named team that grants supplementary permissions
                orthogonal to roles, e.g. "security".

Permission matrix
─────────────────
  Permission string   Meaning
  ─────────────────── ──────────────────────────────────────────────────
  agent.invoke        Create a new agent session (POST /sessions)
  session.read        Read session records and event history (GET /sessions/*)
  session.write       Modify session state (reserved for future use)
  session.override    Force-block or unblock a session regardless of policy

Role → permissions
──────────────────
  Role                Permissions granted
  ─────────────────── ──────────────────────────────────────────────────
  agent_operator      agent.invoke  session.read
  security_analyst    session.read  session.override
  viewer              session.read
  admin / spm:admin   ALL permissions

Group → supplementary permissions
──────────────────────────────────
  Group               Additional permissions
  ─────────────────── ──────────────────────────────────────────────────
  security            session.override  (on top of whatever the role grants)

authorize() algorithm
─────────────────────
  1. Admin shortcut  — any admin role → always granted.
  2. Collect perms from all roles the caller holds.
  3. Add supplementary perms from all groups the caller belongs to.
  4. Check whether the requested permission is in the union.
  5. Return (granted: bool, reason: str).
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Set

from fastapi import Depends, HTTPException, Request, status

from dependencies.auth import IdentityContext, get_current_identity

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Permissions
# ─────────────────────────────────────────────────────────────────────────────

class Permission(str, Enum):
    """All permissions recognised by this service."""

    AGENT_INVOKE      = "agent.invoke"
    SESSION_READ      = "session.read"
    SESSION_WRITE     = "session.write"
    SESSION_OVERRIDE  = "session.override"

    def __str__(self) -> str:          # makes f-strings cleaner
        return self.value


# ─────────────────────────────────────────────────────────────────────────────
# Permission matrix
# ─────────────────────────────────────────────────────────────────────────────

# Role → frozenset of permissions
_ROLE_PERMISSIONS: Dict[str, FrozenSet[Permission]] = {
    "agent_operator": frozenset({
        Permission.AGENT_INVOKE,
        Permission.SESSION_READ,
    }),
    "security_analyst": frozenset({
        Permission.SESSION_READ,
        Permission.SESSION_OVERRIDE,
    }),
    "viewer": frozenset({
        Permission.SESSION_READ,
    }),
    # Super-roles — assigned programmatically in the role claim
    "admin":     frozenset(Permission),   # all permissions
    "spm:admin": frozenset(Permission),
}

# Group → supplementary permissions (added on top of role grants)
_GROUP_PERMISSIONS: Dict[str, FrozenSet[Permission]] = {
    "security": frozenset({
        Permission.SESSION_OVERRIDE,
    }),
    "ops": frozenset({
        Permission.SESSION_READ,
        Permission.AGENT_INVOKE,
    }),
}

# Admin role names — bypass full matrix check
_ADMIN_ROLES: FrozenSet[str] = frozenset({"admin", "spm:admin"})


# ─────────────────────────────────────────────────────────────────────────────
# Core authorize() function
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AuthzResult:
    granted:    bool
    permission: Permission
    user_id:    str
    reason:     str              # human-readable explanation (for logs + errors)


def authorize(
    identity: IdentityContext,
    permission: Permission,
) -> AuthzResult:
    """
    Evaluate whether ``identity`` holds ``permission``.

    Args:
        identity:   The caller's IdentityContext (from get_current_identity).
        permission: The Permission being requested.

    Returns:
        AuthzResult with granted=True/False and a human-readable reason.

    This function is pure (no side-effects) so it is trivially unit-testable.
    """

    # ── 1. Admin shortcut ────────────────────────────────────────────────
    if identity.role_set() & _ADMIN_ROLES:
        matched_admin = next(iter(identity.role_set() & _ADMIN_ROLES))
        return AuthzResult(
            granted=True,
            permission=permission,
            user_id=identity.user_id,
            reason=f"Granted via admin role '{matched_admin}'.",
        )

    # ── 2. Collect permissions from all roles ────────────────────────────
    effective: Set[Permission] = set()
    matched_roles = []

    for role in identity.roles:
        role_perms = _ROLE_PERMISSIONS.get(role, frozenset())
        if role_perms:
            effective |= role_perms
            matched_roles.append(role)

    # ── 3. Add supplementary group permissions ───────────────────────────
    matched_groups = []
    for group in identity.groups:
        group_perms = _GROUP_PERMISSIONS.get(group, frozenset())
        if group_perms:
            effective |= group_perms
            matched_groups.append(group)

    # ── 4. Decision ──────────────────────────────────────────────────────
    granted = permission in effective

    if granted:
        source_parts = []
        if matched_roles:
            source_parts.append(f"roles={matched_roles}")
        if matched_groups:
            source_parts.append(f"groups={matched_groups}")
        reason = f"Granted via {' + '.join(source_parts)}."
    else:
        all_roles   = identity.roles  or ["(none)"]
        all_groups  = identity.groups or ["(none)"]
        reason = (
            f"Permission '{permission}' not granted. "
            f"Caller roles={all_roles}, groups={all_groups}. "
            f"Effective permissions={sorted(p.value for p in effective) or ['(none)']}."
        )

    return AuthzResult(
        granted=granted,
        permission=permission,
        user_id=identity.user_id,
        reason=reason,
    )


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI dependency factory
# ─────────────────────────────────────────────────────────────────────────────
#
# WHY a factory function instead of a callable class:
#
#   FastAPI resolves type-annotation forward refs via:
#       globalns = getattr(call, "__globals__", {})
#
#   Plain functions carry __globals__ (their defining module's namespace).
#   Callable class *instances* do not have __globals__, so FastAPI falls
#   back to an empty dict.  With `from __future__ import annotations`,
#   all annotations become strings (ForwardRef), so `Request` can't be
#   resolved → PydanticUndefinedAnnotation at startup.
#
#   Returning a plain async function from a factory guarantees __globals__
#   is set to this module's namespace (where Request IS imported).
# ─────────────────────────────────────────────────────────────────────────────

def _make_rbac_dependency(permission: Permission):
    """
    Returns a FastAPI async dependency function that enforces ``permission``.

    On success → returns the caller's IdentityContext (route can use it).
    On denial  → raises HTTP 403 with a structured, actionable error body.

    Usage:
        @router.post("")
        async def create_session(
            identity: IdentityContext = Depends(require_agent_invoke),
            ...
        ):
    """

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
                    "groups":     identity.groups,
                    "hint": (
                        f"Roles that grant '{permission}': {qualifying_roles}. "
                        f"Groups that grant it: "
                        f"{[g for g, ps in _GROUP_PERMISSIONS.items() if permission in ps]}."
                    ),
                    "trace_id":   trace_id,
                },
            )

        return identity

    # Give each dependency a unique __name__ for FastAPI's OpenAPI introspection
    _check_permission.__name__ = f"require_{permission.name.lower()}"
    return _check_permission


# ─────────────────────────────────────────────────────────────────────────────
# Pre-built dependency functions  (import these directly in routers)
# ─────────────────────────────────────────────────────────────────────────────

require_agent_invoke     = _make_rbac_dependency(Permission.AGENT_INVOKE)
require_session_read     = _make_rbac_dependency(Permission.SESSION_READ)
require_session_write    = _make_rbac_dependency(Permission.SESSION_WRITE)
require_session_override = _make_rbac_dependency(Permission.SESSION_OVERRIDE)


# ─────────────────────────────────────────────────────────────────────────────
# Utility: describe current permissions for a user (used by /me endpoint)
# ─────────────────────────────────────────────────────────────────────────────

def effective_permissions(identity: IdentityContext) -> List[str]:
    """Return sorted list of permission strings the identity currently holds."""
    if identity.role_set() & _ADMIN_ROLES:
        return sorted(p.value for p in Permission)

    effective: Set[Permission] = set()
    for role in identity.roles:
        effective |= _ROLE_PERMISSIONS.get(role, frozenset())
    for group in identity.groups:
        effective |= _GROUP_PERMISSIONS.get(group, frozenset())

    return sorted(p.value for p in effective)
