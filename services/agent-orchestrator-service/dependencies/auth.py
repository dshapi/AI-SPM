"""
dependencies/auth.py
─────────────────────
Backward-compatible shim — all symbols now live in platform_shared.rbac.
Import from here or from platform_shared.rbac; both work.
"""
from platform_shared.rbac import (  # noqa: F401  re-exported
    IdentityContext,
    get_current_identity,
)
