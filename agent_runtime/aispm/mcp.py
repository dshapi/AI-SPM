"""Thin MCP client used by ``aispm.mcp.call("tool_name", **kwargs)``.

Speaks JSON-RPC 2.0 over HTTP per the MCP spec. Bearer-authenticated
with the per-agent ``MCP_TOKEN`` injected at container start.

Why not the official ``mcp`` Python SDK?
────────────────────────────────────────
The official SDK is great for stdio / SSE transports but its HTTP
client surface is heavier than we need — full session management,
capability negotiation, etc. Our agents make one-shot tool calls; a
plain JSON-RPC POST is faster, easier to reason about, and removes
a dependency. If/when V2 ships custom MCP tools that need the full
SDK (resource subscriptions, prompt templates), this module gets
swapped for a thin wrapper around it without changing the public
``call()`` surface.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

import httpx

from . import MCP_TOKEN as _MCP_TOKEN, MCP_URL as _MCP_URL

log = logging.getLogger(__name__)

# spm-mcp's tool calls are short — Tavily round-trip is a few seconds at
# most; we cap at 30 to surface stalls instead of hanging the agent.
_TIMEOUT_S = 30


def _raise_for_status_with_detail(r: httpx.Response) -> None:
    """Like ``r.raise_for_status()`` but appends the response body's
    ``detail`` so non-2xx responses from spm-mcp surface a useful error.
    See the matching helper in ``aispm/llm.py`` for the rationale.
    """
    if r.status_code < 400:
        return
    detail = ""
    try:
        body = r.json()
    except Exception:                                          # noqa: BLE001
        body = None
    if isinstance(body, dict):
        d = body.get("detail") or body.get("error") or body.get("message")
        if isinstance(d, dict):
            detail = str(d.get("message") or d)
        elif d:
            detail = str(d)
    if not detail:
        detail = (r.text or "").strip()[:500]
    kind = "Client" if r.status_code < 500 else "Server"
    base = f"{kind} error '{r.status_code} {r.reason_phrase}' for url '{r.url}'"
    msg = f"{base}\n  → {detail}" if detail else base
    raise httpx.HTTPStatusError(msg, request=r.request, response=r)


class MCPError(RuntimeError):
    """Raised when the MCP server returns an ``error`` field instead of
    a ``result``. The error code + message from the server are
    preserved on the ``code`` and ``args[0]`` attributes."""

    def __init__(self, code: int, message: str, *, data: Any = None):
        super().__init__(message)
        self.code = code
        self.data = data


async def call(tool: str, **kwargs) -> Dict[str, Any]:
    """Invoke an MCP tool by name and return its result dict.

    Parameters
    ──────────
    tool : str
        The tool's registered name, e.g. ``"web_fetch"``.
    **kwargs
        Tool arguments, passed through unmodified as the JSON-RPC
        ``params.arguments`` map. Each tool documents its own
        parameter schema (see ``services/spm_mcp/tools/`` server-side).

    Returns
    ───────
    dict
        The ``result`` field of the JSON-RPC response. Tool-specific
        shape — for ``web_fetch`` it's ``{"results": [...]}``.

    Raises
    ──────
    MCPError
        The server returned a JSON-RPC ``error`` object — usually
        because the tool doesn't exist or its arguments validation
        failed.
    httpx.HTTPStatusError
        Non-2xx HTTP response from the MCP server itself (auth /
        infra failures, distinct from per-tool errors).
    """
    if not _MCP_URL or not _MCP_TOKEN:
        raise RuntimeError(
            "aispm.mcp.call: MCP_URL / MCP_TOKEN env vars are not set "
            "(agent was not spawned by the controller?)"
        )

    body = {
        "jsonrpc": "2.0",
        "id":      1,
        "method":  "tools/call",
        "params":  {"name": tool, "arguments": dict(kwargs)},
    }
    headers = {"Authorization": f"Bearer {_MCP_TOKEN}"}

    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as c:
        r = await c.post(_MCP_URL, json=body, headers=headers)
    _raise_for_status_with_detail(r)

    payload = r.json()
    err = payload.get("error")
    if err:
        raise MCPError(
            code=int(err.get("code", -1)),
            message=str(err.get("message", "MCP error")),
            data=err.get("data"),
        )
    return payload.get("result") or {}
