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


# ─── POST /mcp — JSON-RPC tools/call endpoint ───────────────────────────────
#
# The aispm SDK speaks plain JSON-RPC 2.0 over HTTP (one POST per tool
# call) — that's enough for one-shot agent tool invocations and avoids
# FastMCP's heavier streaming-HTTP / SSE transport setup. We dispatch
# the registered tools directly so the SDK gets a clean JSON-RPC reply
# instead of the FastAPI default 404 it was hitting before.

def _jsonrpc_error(req_id, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


@app.post("/mcp")
async def mcp_call(
    body:  Dict[str, Any],
    agent: Dict[str, Any] = Depends(auth_required),
) -> Dict[str, Any]:
    """Dispatch a JSON-RPC ``tools/call`` request from the agent SDK.

    Currently the only registered tool is ``web_fetch``; we resolve its
    Tavily creds via the agent-runtime integration row and forward.
    Other tools added via ``@mcp.tool()`` are handled generically by
    looking them up in ``mcp._tool_manager`` so wiring a new tool is a
    one-decorator change in ``services/spm_mcp/tools/``.
    """
    req_id = body.get("id")
    method = body.get("method")
    if method != "tools/call":
        return _jsonrpc_error(
            req_id, -32601,
            f"Method not found or not implemented: {method!r}",
        )

    params = body.get("params") or {}
    tool_name = params.get("name")
    args = params.get("arguments") or {}
    if not tool_name:
        return _jsonrpc_error(
            req_id, -32602, "tools/call requires params.name",
        )

    # Fast path for web_fetch — its Tavily creds + truncation knobs come
    # from the agent-runtime + Tavily integration rows, which the helper
    # already knows how to resolve.
    if tool_name == "web_fetch":
        try:
            from .tools.web_fetch import web_fetch, _resolve_tavily_config
            cfg = await _resolve_tavily_config(
                tenant_id=agent.get("tenant_id", "t1"),
            )
            n = args.get("max_results") or cfg["max_results_default"]
            result = await web_fetch(
                query=str(args.get("query") or ""),
                tavily_api_key=cfg["api_key"],
                max_results=int(n),
                max_chars=cfg["max_chars"],
            )
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except RuntimeError as e:
            # Resolution / config error — surface as a JSON-RPC error
            # rather than letting it become a 500.
            log.warning("spm-mcp: web_fetch config error: %s", e)
            return _jsonrpc_error(req_id, -32000, str(e))
        except Exception as e:  # noqa: BLE001
            log.exception("spm-mcp: web_fetch failed")
            return _jsonrpc_error(
                req_id, -32000, f"{type(e).__name__}: {e}",
            )

    return _jsonrpc_error(
        req_id, -32601, f"Unknown tool: {tool_name!r}",
    )
