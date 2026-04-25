"""spm-mcp — MCP server for the agent runtime control plane.

Hosts the platform-provided tools that customer agents can call. Phase 1
ships ``web_fetch`` (Tavily-backed); custom tools are V2.

Architecture
────────────
Two FastAPI apps mounted in one process:

  * ``GET /health``        — plain HTTP healthcheck for docker-compose
                             and the agent-runtime ConnectorType probe.
  * ``POST /mcp/...``      — the FastMCP server, gated by Bearer auth
                             against the ``agents.mcp_token`` column.

The MCP transport itself is HTTP per the official MCP spec; FastMCP
provides the JSON-RPC framing. We register tools via ``@mcp.tool()`` in
``tools/`` and import them here at module load.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import Depends, FastAPI, Header, HTTPException

from .auth import verify_mcp_token

log = logging.getLogger(__name__)

app = FastAPI(title="spm-mcp", version="0.1.0")


# ─── /health ────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> Dict[str, bool]:
    """Liveness probe used by docker-compose healthcheck and
    ``probe_agent_runtime``."""
    return {"ok": True}


# ─── Auth dependency ────────────────────────────────────────────────────────

async def auth_required(authorization: str = Header(...)) -> Dict[str, Any]:
    """Resolve the bearer token to an agent dict; 401 on miss.

    Used by every tool-call endpoint and by introspection routes that
    leak any per-agent context.
    """
    try:
        return await verify_mcp_token(authorization)
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))


# ─── MCP server (lazy import so the app boots without the SDK in tests) ────

try:                                            # pragma: no cover
    from mcp.server.fastmcp import FastMCP      # type: ignore
    mcp = FastMCP("spm-mcp")
    _MCP_AVAILABLE = True
except ImportError:                             # pragma: no cover
    # The mcp SDK isn't installed in the unit-test sandbox. Stub it out
    # so the rest of the module still imports cleanly. Tools that need
    # FastMCP will be no-ops in this environment.
    mcp = None
    _MCP_AVAILABLE = False
    log.warning("spm-mcp: mcp SDK not importable; running in HTTP-only mode")


# Tool registration is performed inside the tools package on import. The
# package itself is imported here so its @mcp.tool() decorators run at
# module load. No public surface beyond that.
if _MCP_AVAILABLE:                              # pragma: no cover
    from . import tools  # noqa: F401
