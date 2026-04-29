"""aispm.llm — OpenAI-compat client over the proxy."""
from __future__ import annotations

import httpx
import pytest

from aispm import llm
from aispm.types import Completion


@pytest.mark.asyncio
async def test_complete_forwards_request(monkeypatch):
    captured = {}

    async def _fake_post(self, url, json=None, headers=None, **kw):
        captured.update({"url": url, "headers": dict(headers or {}),
                         "body": json})
        return httpx.Response(200, json={
            "model": "llama3.1:8b",
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": "yo"},
                         "finish_reason": "stop"}],
            "usage":  {"prompt_tokens": 10, "completion_tokens": 3,
                       "total_tokens": 13},
        }, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    monkeypatch.setattr(llm, "_BASE_URL", "http://spm-llm-proxy:8500/v1")
    monkeypatch.setattr(llm, "_API_KEY",  "llm-x")

    out = await llm.complete(messages=[{"role": "user", "content": "hi"}])

    assert isinstance(out, Completion)
    assert out.text  == "yo"
    assert out.model == "llama3.1:8b"
    assert out.usage["prompt_tokens"]     == 10
    assert out.usage["completion_tokens"] == 3

    assert captured["headers"]["Authorization"] == "Bearer llm-x"
    assert captured["body"]["messages"]    == [{"role": "user", "content": "hi"}]
    assert captured["body"]["max_tokens"]  == 2048
    assert captured["body"]["temperature"] == 0.7


@pytest.mark.asyncio
async def test_complete_pins_model_when_passed(monkeypatch):
    captured = {}
    async def _fake_post(self, url, json=None, **kw):
        captured["body"] = json
        return httpx.Response(200, json={
            "model": "claude-sonnet",
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": "ok"},
                         "finish_reason": "stop"}],
            "usage":  {"prompt_tokens": 0, "completion_tokens": 0},
        }, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    monkeypatch.setattr(llm, "_BASE_URL", "http://x")
    monkeypatch.setattr(llm, "_API_KEY", "k")

    await llm.complete(messages=[{"role": "user", "content": "hi"}],
                        model="claude-sonnet")
    assert captured["body"]["model"] == "claude-sonnet"


@pytest.mark.asyncio
async def test_complete_raises_on_4xx(monkeypatch):
    async def _fake_post(self, url, **kw):
        return httpx.Response(401, json={"detail": "bad key"},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    monkeypatch.setattr(llm, "_BASE_URL", "http://x")
    monkeypatch.setattr(llm, "_API_KEY",  "k")

    with pytest.raises(httpx.HTTPStatusError):
        await llm.complete(messages=[{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_complete_502_surfaces_proxy_detail(monkeypatch):
    """Regression — when the proxy 502s, the agent's ``f"{e}"`` must
    include the response body's ``detail`` so the customer sees *why*
    the upstream failed (e.g. "Anthropic upstream is missing api_key").
    Without this, all the chat agent ever surfaces is the bare status
    line and the operator has no thread to pull on."""
    async def _fake_post(self, url, **kw):
        return httpx.Response(
            502,
            json={"detail": "Anthropic upstream is missing api_key — "
                            "configure it on the Anthropic integration"},
            request=httpx.Request("POST", url),
        )
    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    monkeypatch.setattr(llm, "_BASE_URL", "http://x")
    monkeypatch.setattr(llm, "_API_KEY",  "k")

    with pytest.raises(httpx.HTTPStatusError) as ei:
        await llm.complete(messages=[{"role": "user", "content": "hi"}])

    msg = str(ei.value)
    # Status line still present (back-compat).
    assert "502" in msg
    # And — the new bit — the proxy's detail is in the str().
    assert "Anthropic upstream is missing api_key" in msg


@pytest.mark.asyncio
async def test_complete_requires_env(monkeypatch):
    monkeypatch.setattr(llm, "_BASE_URL", "")
    monkeypatch.setattr(llm, "_API_KEY",  "")
    with pytest.raises(RuntimeError, match="not set"):
        await llm.complete(messages=[{"role": "user", "content": "hi"}])
