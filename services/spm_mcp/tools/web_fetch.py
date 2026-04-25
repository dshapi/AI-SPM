"""``web_fetch`` MCP tool — Tavily-backed web search.

Phase 1's only platform-provided tool. Customer agents call it via
``aispm.mcp.call("web_fetch", query="...", max_results=5)`` (the SDK
client lives in ``agent_runtime/aispm/mcp.py`` — Phase 2).

Resolution
──────────
The Tavily API key is NOT baked in. At call time we look up the active
agent-runtime integration row, read its ``tavily_integration_id`` field,
load that integration's credentials, and invoke Tavily with the right
key. This means rotating the Tavily key is a no-restart change for all
agents.

Output truncation
─────────────────
Tavily can return very large content blobs. We truncate each result's
``content`` to ``tavily_max_chars`` (configurable per agent-runtime
integration; default 4000) so a single tool call can't blow up the
agent's LLM context window.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx

log = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"


# ─── Pure helper: callable directly from tests ─────────────────────────────

async def web_fetch(
    query: str, *,
    tavily_api_key: str,
    max_results: int = 5,
    max_chars:   int = 4000,
) -> Dict[str, Any]:
    """Search the web via Tavily and return up to ``max_results`` results.

    Each result is truncated to ``max_chars`` characters so the payload
    stays bounded regardless of the upstream blob size.

    Returns ``{"results": [{"title": str, "url": str, "content": str}, ...]}``.
    Raises on transport / non-2xx errors so the FastMCP layer can convert
    them to MCP error responses with the right framing.
    """
    body = {
        "api_key":         tavily_api_key,
        "query":           query,
        "max_results":     max_results,
        "include_answer":  False,
        "include_images":  False,
    }
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(TAVILY_URL, json=body)
    r.raise_for_status()

    data = r.json()
    results = []
    for item in (data.get("results") or [])[:max_results]:
        results.append({
            "title":   item.get("title", ""),
            "url":     item.get("url", ""),
            "content": (item.get("content", "") or "")[:max_chars],
        })
    return {"results": results}


# ─── Per-call config + creds resolution ────────────────────────────────────

async def _resolve_tavily_config(tenant_id: str = "t1") -> Dict[str, Any]:
    """Return ``{"api_key": str, "max_chars": int, "max_results_default": int}``.

    Read at every tool invocation so config changes apply without a
    restart. The lookup is cheap because the agent-runtime row is small.
    """
    from sqlalchemy import select         # type: ignore
    from sqlalchemy.orm import selectinload  # type: ignore
    from spm.db.models  import Integration   # type: ignore
    from spm.db.session import get_session_factory  # type: ignore
    try:
        from integrations_routes import _decode_secret  # type: ignore
    except ModuleNotFoundError:
        from services.spm_api.integrations_routes import _decode_secret  # type: ignore

    sf = get_session_factory()
    async with sf() as db:
        # 1. Find the agent-runtime integration row.
        host_stmt = (
            select(Integration)
            .where(Integration.connector_type == "agent-runtime")
        )
        host = (await db.execute(host_stmt)).scalar_one_or_none()
        if host is None:
            raise RuntimeError(
                "agent-runtime integration is not configured — "
                "cannot resolve Tavily API key"
            )

        cfg = host.config or {}
        tavily_id = cfg.get("tavily_integration_id")
        if not tavily_id:
            raise RuntimeError(
                "agent-runtime is missing tavily_integration_id"
            )

        # 2. Load the referenced Tavily integration to fetch the api_key.
        target_stmt = (
            select(Integration)
            .where(Integration.id == tavily_id)
            .options(selectinload(Integration.credentials))
        )
        target = (await db.execute(target_stmt)).scalar_one_or_none()
        if target is None:
            raise RuntimeError(
                f"tavily_integration_id points at {tavily_id!r} which does not exist"
            )

        api_key_cred = next(
            (c for c in (target.credentials or [])
             if c.credential_type == "api_key" and c.is_configured),
            None,
        )
        if api_key_cred is None:
            raise RuntimeError(
                f"Tavily integration {tavily_id!r} has no api_key configured"
            )

        return {
            "api_key":              _decode_secret(api_key_cred.value_enc),
            "max_chars":            int(cfg.get("tavily_max_chars",   4000)),
            "max_results_default": int(cfg.get("tavily_max_results", 5)),
        }


# ─── FastMCP registration ──────────────────────────────────────────────────

def register(mcp) -> None:
    """Register the ``web_fetch`` tool against a FastMCP instance.

    Called once at module-load by ``services.spm_mcp.tools.__init__``.
    Kept as a function (not a top-level decorator) so the registration
    is opt-in and unit tests that don't mount the MCP server skip it.
    """

    @mcp.tool()
    async def web_fetch_mcp(query: str,
                             max_results: Optional[int] = None) -> Dict[str, Any]:
        """Search the web via Tavily.

        Use this when the agent needs up-to-date facts the LLM can't
        answer from its training data. Returns up to ``max_results``
        results (default from operator-configured agent-runtime), each
        with a title, URL, and a content snippet truncated to the
        configured limit.
        """
        cfg = await _resolve_tavily_config()
        n = max_results if max_results is not None else cfg["max_results_default"]
        return await web_fetch(
            query=query,
            tavily_api_key=cfg["api_key"],
            max_results=n,
            max_chars=cfg["max_chars"],
        )
