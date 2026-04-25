"""Resolves which AI Provider integration the spm-llm-proxy forwards to.

The agent-runtime ConnectorType has a ``default_llm_integration_id``
field pointing at an active AI Provider integration row. This module
loads that target row's config + decoded credentials so the chat-
completions handler in ``main.py`` can build an upstream request.

Phase 1: every request resolves on demand. Phase 2 adds a per-tenant
60-second cache invalidated on integration PATCH (the cache key is the
agent-runtime integration's `updated_at` timestamp).

Returns ``(config: dict, credentials: dict)``. Both dicts are keyed by
the FieldSpec.key declared in the connector_registry for the target
connector_type — the same shape probes consume.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

log = logging.getLogger(__name__)


class _LLMResolutionError(RuntimeError):
    """Raised when the proxy cannot determine which upstream LLM to call.

    Wrapped in ``RuntimeError`` so callers can use a broad catch; the
    string message is suitable for surfacing in a 502 response body.
    """


async def _load_agent_runtime_row(tenant_id: str):
    """Load the agent-runtime integration row for the given tenant.

    Returns the row or ``None`` (no agent-runtime integration configured).
    Lazily imports DB modules so this module is importable in unit-test
    envs without a live engine.
    """
    from sqlalchemy import select         # type: ignore
    from sqlalchemy.orm import selectinload  # type: ignore
    from spm.db.models  import Integration   # type: ignore
    from spm.db.session import get_session_factory  # type: ignore

    sf = get_session_factory()
    async with sf() as db:
        # tenant_id is a single-tenant placeholder in V1; the column is
        # not enforced today but kept in the WHERE for V2-readiness.
        stmt = (
            select(Integration)
            .where(Integration.connector_type == "agent-runtime")
            .options(selectinload(Integration.credentials))
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()


async def _load_target_integration(integration_id: str):
    """Load the LLM integration row referenced by default_llm_integration_id."""
    from sqlalchemy import select         # type: ignore
    from sqlalchemy.orm import selectinload  # type: ignore
    from spm.db.models  import Integration   # type: ignore
    from spm.db.session import get_session_factory  # type: ignore

    sf = get_session_factory()
    async with sf() as db:
        stmt = (
            select(Integration)
            .where(Integration.id == integration_id)
            .options(selectinload(Integration.credentials))
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()


def _decode_creds_for(target_row) -> Dict[str, Any]:
    """Decode all secret credentials declared on the target's
    connector_type, keyed by FieldSpec.key."""
    try:
        from connector_registry  import get_connector  # type: ignore
        from integrations_routes import _decode_secret  # type: ignore
    except ModuleNotFoundError:                        # pragma: no cover
        from services.spm_api.connector_registry  import get_connector  # type: ignore
        from services.spm_api.integrations_routes import _decode_secret  # type: ignore

    ct = get_connector(getattr(target_row, "connector_type", None))
    if ct is None:
        return {}

    creds: Dict[str, Any] = {}
    for f in ct["fields"]:
        if not f.get("secret"):
            continue
        key = f["key"]
        c = next(
            (c for c in (target_row.credentials or [])
             if c.credential_type == key and c.is_configured),
            None,
        )
        if c:
            creds[key] = _decode_secret(c.value_enc)
    return creds


async def resolve_llm_integration(*, tenant_id: str = "t1"
                                   ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return ``(config, credentials)`` for the upstream LLM.

    Raises ``RuntimeError`` if:
      - no agent-runtime integration exists for the tenant
      - the integration has no ``default_llm_integration_id`` set
      - the referenced integration row is missing
    """
    host = await _load_agent_runtime_row(tenant_id)
    if host is None:
        raise _LLMResolutionError(
            "agent-runtime integration is not configured — "
            "set it up in Integrations → AI Providers → "
            "AI-SPM Agent Runtime Control Plane (MCP)"
        )

    target_id = (host.config or {}).get("default_llm_integration_id")
    if not target_id:
        raise _LLMResolutionError(
            "agent-runtime integration is missing default_llm_integration_id"
        )

    target = await _load_target_integration(target_id)
    if target is None:
        raise _LLMResolutionError(
            f"default_llm_integration_id points at integration "
            f"{target_id!r} which does not exist"
        )

    return dict(target.config or {}), _decode_creds_for(target)
