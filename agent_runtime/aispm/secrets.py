"""Per-agent secret retrieval — ``aispm.get_secret(name)``.

Customer agents NEVER have raw env-var secrets at hand; spec §6 forbids
plain-env config so the customer can't copy-paste their API keys into
``agent.py`` and accidentally leak them through logs / git.

Instead, secrets are configured in the agent's Configure → Custom env
vars section (encrypted at rest in ``integration_credentials``), and
the agent fetches them at use time:

    api_key = await aispm.get_secret("MY_API_KEY")

Authentication is bearer-token: the agent's ``MCP_TOKEN`` is presented
to spm-api which already knows how to resolve it back to an agent ID
(via ``platform_shared.agent_tokens.resolve_agent_by_mcp_token``).
"""
from __future__ import annotations

import logging

import httpx

from . import (
    AGENT_ID       as _AGENT_ID,
    CONTROLLER_URL as _CONTROLLER_URL,
    MCP_TOKEN      as _MCP_TOKEN,
)

log = logging.getLogger(__name__)

_TIMEOUT_S = 5.0


class SecretNotFound(KeyError):
    """Raised when *name* is not configured for this agent. Inherits
    from KeyError so customers can write
    ``try: ... except KeyError: ...`` if they prefer."""


async def get_secret(name: str) -> str:
    """Return the configured value for *name*.

    Raises ``SecretNotFound`` if the secret isn't set on this agent's
    Configure tab. Other failures (transport errors, auth failures)
    surface as ``httpx.HTTPError`` subclasses.

    The lookup is per-call; the controller can rotate secrets without
    restarting the agent.
    """
    # Argument check first — independent of env state, deterministic.
    if not name:
        raise ValueError("aispm.get_secret: empty secret name")
    if not _AGENT_ID:
        raise RuntimeError("aispm.get_secret: AGENT_ID env var not set")

    url = (f"{_CONTROLLER_URL}/api/spm/agents/{_AGENT_ID}"
           f"/secrets/{name}")
    headers = {"Authorization": f"Bearer {_MCP_TOKEN}"}
    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as c:
        r = await c.get(url, headers=headers)
    if r.status_code == 404:
        raise SecretNotFound(name)
    r.raise_for_status()
    return str(r.json().get("value", ""))
