"""Bearer authentication for spm-mcp.

Each customer agent's container is issued a per-agent ``mcp_token`` that
it presents on every tool call against this server. The auth path is:

    request → verify_mcp_token(authorization_header) → agent dict | 401

The lookup is shared with spm-llm-proxy via
``platform_shared.agent_tokens.resolve_agent_by_mcp_token`` so both
services answer the same question identically.

Failure modes
─────────────
- Empty / missing header     → ``PermissionError("missing token")``
- Token doesn't match any
  agents.mcp_token row       → ``PermissionError("Unknown mcp_token")``
- DB unreachable             → resolver returns ``None``; we 401 the
                               caller (fail-closed).

Callers (the FastAPI dependency in ``main.py``) wrap the
``PermissionError`` in an ``HTTPException(401, ...)``.
"""
from __future__ import annotations

from typing import Any, Dict

from platform_shared.agent_tokens import resolve_agent_by_mcp_token


async def verify_mcp_token(authorization: str) -> Dict[str, Any]:
    """Resolve a ``Bearer <token>`` header to an agent dict.

    Returns ``{"id": str, "tenant_id": str, "name": str}`` on hit. Both
    ``"Bearer foo"`` and bare ``"foo"`` are accepted so test clients and
    minor SDK quirks don't accidentally bypass auth on the wrong path.

    Raises ``PermissionError`` on any failure.
    """
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token:
        raise PermissionError("Missing mcp_token")
    agent = await resolve_agent_by_mcp_token(token)
    if agent is None:
        raise PermissionError("Unknown mcp_token")
    return agent
