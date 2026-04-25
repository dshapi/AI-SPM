"""Bearer-token → agent lookup helpers.

The agent-runtime control plane mints two distinct tokens for every
deployed customer agent:

  * ``mcp_token``    — presented by the agent's container to ``spm-mcp``
                       on every tool call. Validates that the caller is
                       a known, currently-deployed agent.
  * ``llm_api_key``  — presented to ``spm-llm-proxy`` on every LLM call.
                       Same trust model: prove you're a known agent so
                       the proxy can pick the right tenant's LLM and
                       record per-agent usage.

Both tokens are stored as plaintext on the ``agents`` row in V1 (the
row is admin-only and never returned in API responses); V2 will encrypt
at rest using the same Fernet key already used for
``integration_credentials``.

This module is the single source of truth for token-resolution so both
``services/spm_mcp/auth.py`` and ``services/spm_llm_proxy/main.py`` can
import the same helper instead of each implementing its own SQL.

Returned shape
──────────────
On hit:

    {
        "id":        "<uuid str>",
        "tenant_id": "<tenant id>",
        "name":      "<display name>",
    }

On miss: ``None``.

Failure semantics
─────────────────
Both helpers swallow DB / network errors and return ``None`` so the
calling auth middleware can answer 401 cleanly. Exceptions are logged
at WARN; never raised.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


async def _lookup_by_token(column_name: str, token: str) -> Optional[Dict[str, Any]]:
    """Look up an Agent row by a token-bearing column name.

    ``column_name`` is one of ``"mcp_token"`` / ``"llm_api_key"``. We
    take it as a string (not a column object) so this module stays free
    of import-time SQLAlchemy bindings — keeping the import surface
    cheap for short-lived lookup requests.
    """
    if not token:
        return None

    # Lazy imports — keep the module importable in test envs that don't
    # have a DB engine configured (e.g. unit tests that monkeypatch
    # this module).
    try:
        from sqlalchemy import select  # type: ignore
        from spm.db.models  import Agent          # type: ignore
        from spm.db.session import get_session_factory  # type: ignore
    except ModuleNotFoundError:                  # pragma: no cover
        log.warning("agent_tokens: db modules not importable; returning None")
        return None

    column = getattr(Agent, column_name, None)
    if column is None:
        log.warning("agent_tokens: Agent has no column %r", column_name)
        return None

    try:
        sf = get_session_factory()
        async with sf() as db:
            result = await db.execute(select(Agent).where(column == token))
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return {
                "id":        str(row.id),
                "tenant_id": row.tenant_id,
                "name":      row.name,
            }
    except Exception as e:                       # noqa: BLE001
        # DB unreachable, schema mismatch, etc. — fail closed.
        log.warning("agent_tokens: lookup failed for column=%s: %s",
                    column_name, e)
        return None


async def resolve_agent_by_mcp_token(token: str) -> Optional[Dict[str, Any]]:
    """Return ``{id, tenant_id, name}`` for the agent whose ``mcp_token``
    equals *token*, or ``None`` if no such agent exists."""
    return await _lookup_by_token("mcp_token", token)


async def resolve_agent_by_llm_token(token: str) -> Optional[Dict[str, Any]]:
    """Return ``{id, tenant_id, name}`` for the agent whose ``llm_api_key``
    equals *token*, or ``None`` if no such agent exists."""
    return await _lookup_by_token("llm_api_key", token)
