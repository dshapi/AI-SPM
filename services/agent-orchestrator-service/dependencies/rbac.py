"""
dependencies/rbac.py
─────────────────────
Backward-compatible shim — all symbols now live in platform_shared.rbac.
Import from here or from platform_shared.rbac; both work.
"""
from platform_shared.rbac import (  # noqa: F401  re-exported
    Permission,
    AuthzResult,
    IdentityContext,
    get_current_identity,
    authorize,
    require,
    effective_permissions,
    require_session_read,
    require_session_write,
    require_session_override,
    require_agent_invoke,
    require_agent_read,
    require_agent_write,
    require_agent_manage,
    require_model_read,
    require_model_write,
    require_model_delete,
    require_integration_read,
    require_integration_write,
    require_compliance_read,
    require_compliance_write,
    require_posture_read,
    require_posture_write,
    require_chat_invoke,
    require_audit_read,
    require_audit_write,
)
