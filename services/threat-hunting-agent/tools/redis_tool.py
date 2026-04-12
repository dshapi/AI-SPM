"""
tools/redis_tool.py
────────────────────
LangChain-compatible tools for querying Redis threat-hunting data.

Key namespaces (from freeze_controller and memory_service):
  freeze:{user_id}          → user freeze flag
  freeze:{tenant}:tenant    → tenant freeze flag
  freeze:session:{sid}      → session freeze flag
  mem:{namespace}:{tenant}:{user}:{key} → memory entries (pattern scan)

A shared Redis client is injected at startup via set_redis_client().
In tests the client is replaced with a fake.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_redis_client: Optional[Any] = None


def set_redis_client(client: Any) -> None:
    """Inject a Redis client (called once at service startup)."""
    global _redis_client
    _redis_client = client


def _get_redis() -> Any:
    if _redis_client is None:
        raise RuntimeError("Redis client not initialised — call set_redis_client() first")
    return _redis_client


# ---------------------------------------------------------------------------
# Tool: get_freeze_state
# ---------------------------------------------------------------------------

def get_freeze_state(
    scope: str,
    target: str,
) -> str:
    """
    Check whether a user, tenant, or session is currently frozen.

    Args:
        scope: One of 'user', 'tenant', or 'session'.
        target: The user ID, tenant ID, or session ID to check.

    Returns:
        JSON with keys: frozen (bool), ttl_seconds (int or -1 if no expiry / -2 if not set).
    """
    r = _get_redis()
    try:
        if scope == "tenant":
            key = f"freeze:{target}:tenant"
        elif scope == "session":
            key = f"freeze:session:{target}"
        else:  # user
            key = f"freeze:{target}"

        val = r.get(key)
        ttl = r.ttl(key) if val is not None else -2
        frozen = val == b"true" or val == "true"
        return json.dumps({"scope": scope, "target": target, "frozen": frozen, "ttl_seconds": ttl})
    except Exception as exc:
        logger.exception("get_freeze_state failed: %s", exc)
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# Tool: scan_session_memory
# ---------------------------------------------------------------------------

def scan_session_memory(
    tenant_id: str,
    user_id: str,
    namespace: str = "session",
    max_keys: int = 50,
) -> str:
    """
    Scan Redis for memory entries belonging to a specific user/tenant.

    Args:
        tenant_id: Tenant to scope the scan.
        user_id: User whose memory to inspect.
        namespace: Memory namespace — 'session', 'longterm', or 'system'.
        max_keys: Maximum number of keys to return (default 50).

    Returns:
        JSON with keys: keys (list of key names), count (int).
    """
    r = _get_redis()
    try:
        pattern = f"mem:{namespace}:{tenant_id}:{user_id}:*"
        keys = []
        for key in r.scan_iter(pattern, count=100):
            keys.append(key.decode() if isinstance(key, bytes) else key)
            if len(keys) >= max_keys:
                break
        return json.dumps({"namespace": namespace, "tenant_id": tenant_id,
                           "user_id": user_id, "keys": keys, "count": len(keys)})
    except Exception as exc:
        logger.exception("scan_session_memory failed: %s", exc)
        return json.dumps({"error": str(exc)})
