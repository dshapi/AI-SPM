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


def _decode_secret(enc):
    """Inverse of services.spm_api.integrations_routes._encode_secret —
    inlined here so spm-llm-proxy's image doesn't need the spm_api code.

    The encoding is plain base64 of the UTF-8 plaintext; tests assert
    ``decode(encode(s)) == s`` on the spm_api side. Returns "" on any
    decode failure so a corrupt row produces a clean upstream-call
    error rather than crashing the proxy with a 500.
    """
    import base64
    if not enc:
        return ""
    try:
        return base64.b64decode(enc.encode("ascii")).decode("utf-8")
    except Exception:                                   # noqa: BLE001
        return ""


def _decode_creds_for(target_row) -> Dict[str, Any]:
    """Decode every configured credential on the target row, keyed by
    ``credential_type`` (== FieldSpec.key on the spm_api side).

    Previously this routed through ``connector_registry.get_connector``
    to filter to ``secret=True`` fields, but that import lives in the
    ``services.spm_api`` package, which isn't COPY'd into the
    spm-llm-proxy image — so the import raised ModuleNotFoundError
    mid-request and the whole call surfaced as 500. We don't actually
    need the FieldSpec metadata: every row in ``integration_credentials``
    is by definition a secret, and the caller (``_to_native_*``) only
    reads the keys it expects (``api_key``, etc.) — extras are
    harmless. Skipping the registry lookup makes spm-llm-proxy
    self-contained.
    """
    creds: Dict[str, Any] = {}
    for c in (getattr(target_row, "credentials", None) or []):
        if not getattr(c, "is_configured", False):
            continue
        key = getattr(c, "credential_type", None)
        if not key:
            continue
        creds[key] = _decode_secret(getattr(c, "value_enc", None))
    return creds


async def resolve_llm_integration(*, tenant_id: str = "t1"
                                   ) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    """Return ``(connector_type, config, credentials)`` for the upstream LLM.

    The ``connector_type`` (e.g. ``"anthropic"``, ``"ollama"``,
    ``"openai"``) tells the dispatcher in main.py which native API
    shape to translate to. Without it the proxy was blindly POSTing
    Ollama-shaped requests to whichever provider the operator picked,
    which only worked when they picked Ollama.

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

    connector_type = (getattr(target, "connector_type", "") or "").lower()
    return connector_type, dict(target.config or {}), _decode_creds_for(target)
