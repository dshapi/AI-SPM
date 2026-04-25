"""aispm.mcp — JSON-RPC POST + bearer auth + result parsing."""
from __future__ import annotations

import httpx
import pytest

from aispm import mcp
from aispm.mcp import MCPError


@pytest.mark.asyncio
async def test_call_passes_bearer_and_returns_result(monkeypatch):
    captured = {}

    async def _fake_post(self, url, json=None, headers=None, **kw):
        captured["url"]     = url
        captured["headers"] = dict(headers or {})
        captured["body"]    = json
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": 1,
            "result": {"results": [{"title": "x"}]},
        }, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    monkeypatch.setattr(mcp, "_MCP_URL",   "http://spm-mcp:8500/mcp")
    monkeypatch.setattr(mcp, "_MCP_TOKEN", "abc")

    out = await mcp.call("web_fetch", query="hi", max_results=3)

    assert out["results"][0]["title"] == "x"
    assert captured["url"] == "http://spm-mcp:8500/mcp"
    assert captured["headers"]["Authorization"] == "Bearer abc"
    # JSON-RPC 2.0 envelope shape
    assert captured["body"]["jsonrpc"] == "2.0"
    assert captured["body"]["method"]  == "tools/call"
    assert captured["body"]["params"]["name"] == "web_fetch"
    assert captured["body"]["params"]["arguments"] == {
        "query": "hi", "max_results": 3,
    }


@pytest.mark.asyncio
async def test_call_raises_mcp_error_on_error_payload(monkeypatch):
    async def _fake_post(self, url, **kw):
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": 1,
            "error": {"code": -32601, "message": "Method not found"},
        }, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    monkeypatch.setattr(mcp, "_MCP_URL",   "http://x:1/mcp")
    monkeypatch.setattr(mcp, "_MCP_TOKEN", "t")

    with pytest.raises(MCPError) as ei:
        await mcp.call("nope")
    assert ei.value.code == -32601
    assert "Method not found" in str(ei.value)


@pytest.mark.asyncio
async def test_call_raises_on_non_2xx(monkeypatch):
    async def _fake_post(self, url, **kw):
        return httpx.Response(401, json={"err": "bad token"},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    monkeypatch.setattr(mcp, "_MCP_URL",   "http://x:1/mcp")
    monkeypatch.setattr(mcp, "_MCP_TOKEN", "t")

    with pytest.raises(httpx.HTTPStatusError):
        await mcp.call("web_fetch", query="x")


@pytest.mark.asyncio
async def test_call_requires_env(monkeypatch):
    monkeypatch.setattr(mcp, "_MCP_URL", "")
    monkeypatch.setattr(mcp, "_MCP_TOKEN", "")
    with pytest.raises(RuntimeError, match="not set"):
        await mcp.call("web_fetch")
