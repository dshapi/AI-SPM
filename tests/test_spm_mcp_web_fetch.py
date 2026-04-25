"""Tests for the web_fetch MCP tool — Task 9."""
from __future__ import annotations

import httpx
import pytest

from services.spm_mcp.tools.web_fetch import web_fetch


# ─── Pure web_fetch helper ─────────────────────────────────────────────────

class TestWebFetch:
    @pytest.mark.asyncio
    async def test_returns_results(self, monkeypatch):
        captured = {}

        async def _fake_post(self, url, json=None, **kw):
            captured["url"]  = url
            captured["body"] = json
            return httpx.Response(200, json={
                "results": [
                    {"title": "MCP",
                     "url":   "https://modelcontextprotocol.io",
                     "content": "Model Context Protocol is..."}
                ]
            }, request=httpx.Request("POST", url))
        monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

        out = await web_fetch(
            query="what is mcp",
            tavily_api_key="tvly-test",
            max_results=5,
            max_chars=4000,
        )
        assert out["results"][0]["title"] == "MCP"
        assert out["results"][0]["url"]   == "https://modelcontextprotocol.io"
        assert "MCP" in captured["url"] or "tavily" in captured["url"].lower()
        assert captured["body"]["query"]   == "what is mcp"
        assert captured["body"]["api_key"] == "tvly-test"

    @pytest.mark.asyncio
    async def test_truncates_long_content(self, monkeypatch):
        async def _fake_post(self, url, json=None, **kw):
            return httpx.Response(200, json={
                "results": [{"title": "x", "url": "u",
                             "content": "a" * 10000}]
            }, request=httpx.Request("POST", url))
        monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

        out = await web_fetch(query="x", tavily_api_key="t",
                              max_results=1, max_chars=100)
        assert len(out["results"][0]["content"]) == 100

    @pytest.mark.asyncio
    async def test_caps_at_max_results(self, monkeypatch):
        async def _fake_post(self, url, json=None, **kw):
            # Return 10 results; we asked for 3 — output should have 3.
            return httpx.Response(200, json={
                "results": [{"title": f"r{i}", "url": f"u{i}", "content": ""}
                            for i in range(10)]
            }, request=httpx.Request("POST", url))
        monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

        out = await web_fetch(query="x", tavily_api_key="t",
                              max_results=3, max_chars=10)
        assert len(out["results"]) == 3

    @pytest.mark.asyncio
    async def test_handles_empty_results_field(self, monkeypatch):
        async def _fake_post(self, url, json=None, **kw):
            return httpx.Response(200, json={},
                                  request=httpx.Request("POST", url))
        monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

        out = await web_fetch(query="x", tavily_api_key="t",
                              max_results=5, max_chars=10)
        assert out == {"results": []}

    @pytest.mark.asyncio
    async def test_raises_on_non_2xx(self, monkeypatch):
        async def _fake_post(self, url, json=None, **kw):
            return httpx.Response(403, json={"err": "bad key"},
                                  request=httpx.Request("POST", url))
        monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

        with pytest.raises(httpx.HTTPStatusError):
            await web_fetch(query="x", tavily_api_key="bad",
                            max_results=1, max_chars=10)
