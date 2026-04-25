"""aispm.secrets — get_secret() against the controller endpoint."""
from __future__ import annotations

import httpx
import pytest

from aispm import secrets
from aispm.secrets import SecretNotFound, get_secret


@pytest.mark.asyncio
async def test_get_secret_returns_value(monkeypatch):
    captured = {}

    async def _fake_get(self, url, headers=None, **kw):
        captured.update({"url": url, "headers": dict(headers or {})})
        return httpx.Response(200, json={"value": "sk-test-1234"},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
    monkeypatch.setattr(secrets, "_AGENT_ID",       "ag-001")
    monkeypatch.setattr(secrets, "_MCP_TOKEN",      "tok")
    monkeypatch.setattr(secrets, "_CONTROLLER_URL", "http://spm-api:8092")

    val = await get_secret("MY_API_KEY")
    assert val == "sk-test-1234"
    assert captured["url"].endswith(
        "/agents/ag-001/secrets/MY_API_KEY"
    )
    assert captured["headers"]["Authorization"] == "Bearer tok"


@pytest.mark.asyncio
async def test_get_secret_404_raises_secret_not_found(monkeypatch):
    async def _fake_get(self, url, **kw):
        return httpx.Response(404, json={"detail": "missing"},
                              request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
    monkeypatch.setattr(secrets, "_AGENT_ID", "ag-001")

    with pytest.raises(SecretNotFound):
        await get_secret("NOT_THERE")


@pytest.mark.asyncio
async def test_get_secret_other_4xx_raises_status(monkeypatch):
    async def _fake_get(self, url, **kw):
        return httpx.Response(403, json={"detail": "forbidden"},
                              request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
    monkeypatch.setattr(secrets, "_AGENT_ID", "ag-001")

    with pytest.raises(httpx.HTTPStatusError):
        await get_secret("X")


@pytest.mark.asyncio
async def test_get_secret_empty_name_raises():
    with pytest.raises(ValueError, match="empty"):
        await get_secret("")


def test_secret_not_found_is_keyerror_subclass():
    """Customers can write `try: ... except KeyError: ...`."""
    assert issubclass(SecretNotFound, KeyError)
