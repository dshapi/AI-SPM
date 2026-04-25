"""aispm.lifecycle — ready() handshake."""
from __future__ import annotations

import httpx
import pytest

from aispm import lifecycle


@pytest.mark.asyncio
async def test_ready_posts_to_controller(monkeypatch):
    captured = {}

    async def _fake_post(self, url, **kw):
        captured["url"] = url
        return httpx.Response(204, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    monkeypatch.setattr(lifecycle, "_AGENT_ID",       "ag-001")
    monkeypatch.setattr(lifecycle, "_CONTROLLER_URL", "http://spm-api:8092")

    await lifecycle.ready()
    assert captured["url"].endswith("/agents/ag-001/ready")


@pytest.mark.asyncio
async def test_ready_swallows_http_errors(monkeypatch):
    async def _fail(self, url, **kw):
        raise httpx.ConnectError("nope", request=None)
    monkeypatch.setattr(httpx.AsyncClient, "post", _fail)
    monkeypatch.setattr(lifecycle, "_AGENT_ID",       "ag-001")
    monkeypatch.setattr(lifecycle, "_CONTROLLER_URL", "http://x:1")

    # Must NOT raise — the controller's poll loop will surface the
    # eventual timeout with a clearer message.
    await lifecycle.ready()


@pytest.mark.asyncio
async def test_ready_noop_when_agent_id_unset(monkeypatch):
    monkeypatch.setattr(lifecycle, "_AGENT_ID", "")
    # Should not even attempt the HTTP call.
    called = {"n": 0}
    async def _post(self, url, **kw):
        called["n"] += 1
        return httpx.Response(204, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.AsyncClient, "post", _post)

    await lifecycle.ready()
    assert called["n"] == 0
