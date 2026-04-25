"""Tests for spm-llm-proxy's POST /v1/chat/completions surface (Task 7)."""
from __future__ import annotations

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from services.spm_llm_proxy import main as proxy_main
from services.spm_llm_proxy.main import app


# ─── Helpers ───────────────────────────────────────────────────────────────

async def _ok_resolve(tenant_id: str = "t1"):
    """Stub resolver — returns (connector_type, config, creds) pointing at
    Ollama (native, no /v1 suffix). Phase-4 update: the resolver now returns
    a 3-tuple including the upstream's connector_type so main.py can
    branch into provider-native dispatch (anthropic / ollama-openai-compat
    / ollama-native)."""
    return (
        "ollama",
        {"base_url": "http://ollama-test:11434", "model_name": "llama3.1:8b"},
        {},  # ollama needs no creds
    )


@pytest.fixture
def authed_client(monkeypatch):
    """TestClient with the auth dependency overridden to always succeed
    (returns a stub agent dict). Tests that exercise the auth layer use
    a different fixture that doesn't override."""
    async def _ok_auth(authorization: str = ""):
        return {"id": "ag-001", "tenant_id": "t1", "name": "stub"}

    app.dependency_overrides[proxy_main._auth_required] = _ok_auth
    yield TestClient(app)
    app.dependency_overrides.clear()


# ─── 1. Auth — 401 paths ───────────────────────────────────────────────────

class TestAuth:
    def test_no_authorization_header_is_401(self, monkeypatch):
        # Real auth path; no header → FastAPI's missing-Header → 422 or 401.
        # The proxy explicitly raises 401 when the header is missing-empty.
        async def _none(token: str):
            return None
        monkeypatch.setattr("platform_shared.agent_tokens."
                             "resolve_agent_by_llm_token", _none)

        # Monkey-patch the auth dep override away (use real path).
        app.dependency_overrides.pop(proxy_main._auth_required, None)
        c = TestClient(app)
        r = c.post("/v1/chat/completions",
                    json={"messages":[{"role":"user","content":"hi"}]})
        # FastAPI's `Header(...)` raises 422 when missing — that's still a
        # rejection. Either is acceptable.
        assert r.status_code in (401, 422), r.text

    def test_unknown_token_is_401(self, monkeypatch):
        async def _none(token: str):
            return None
        monkeypatch.setattr("platform_shared.agent_tokens."
                             "resolve_agent_by_llm_token", _none)

        app.dependency_overrides.pop(proxy_main._auth_required, None)
        c = TestClient(app)
        r = c.post("/v1/chat/completions",
                    headers={"Authorization": "Bearer nope"},
                    json={"messages":[{"role":"user","content":"hi"}]})
        assert r.status_code == 401, r.text


# ─── 2. Forwarding behaviour ───────────────────────────────────────────────

class TestForwarding:
    def test_messages_required(self, authed_client):
        r = authed_client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer any"},
            json={"model": "x"},  # no messages
        )
        assert r.status_code == 400, r.text

    def test_forwards_to_resolved_base_url(self, authed_client, monkeypatch):
        captured: Dict[str, Any] = {}

        async def _fake_post(self, url, json=None, **kw):
            captured["url"]  = url
            captured["body"] = json
            return httpx.Response(
                200,
                json={
                    "message": {"role": "assistant", "content": "hi back"},
                    "prompt_eval_count": 5, "eval_count": 7,
                },
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
        monkeypatch.setattr(proxy_main, "resolve_llm_integration", _ok_resolve)

        r = authed_client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer any"},
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert r.status_code == 200, r.text

        assert captured["url"].startswith("http://ollama-test:11434")
        assert captured["url"].endswith("/api/chat")
        assert captured["body"]["messages"][0]["content"] == "hi"
        # Defaults to the resolved model if the request didn't pin one.
        assert captured["body"]["model"] == "llama3.1:8b"

    def test_response_wrapped_in_openai_shape(self, authed_client, monkeypatch):
        async def _fake_post(self, url, json=None, **kw):
            return httpx.Response(
                200,
                json={
                    "message": {"role": "assistant", "content": "the answer"},
                    "prompt_eval_count": 12, "eval_count": 8,
                },
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
        monkeypatch.setattr(proxy_main, "resolve_llm_integration", _ok_resolve)

        r = authed_client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer any"},
            json={"messages": [{"role": "user", "content": "?"}],
                  "model": "custom-model"},
        )
        body = r.json()
        assert body["object"]  == "chat.completion"
        assert body["model"]   == "custom-model"
        assert body["choices"][0]["message"]["content"] == "the answer"
        assert body["choices"][0]["finish_reason"] == "stop"
        assert body["usage"]["prompt_tokens"]     == 12
        assert body["usage"]["completion_tokens"] == 8
        assert body["usage"]["total_tokens"]      == 20

    def test_upstream_timeout_is_504(self, authed_client, monkeypatch):
        async def _timeout(self, url, json=None, **kw):
            raise httpx.TimeoutException("slow")
        monkeypatch.setattr(httpx.AsyncClient, "post", _timeout)
        monkeypatch.setattr(proxy_main, "resolve_llm_integration", _ok_resolve)

        r = authed_client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer any"},
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert r.status_code == 504, r.text

    def test_resolver_failure_is_502(self, authed_client, monkeypatch):
        async def _bad_resolve(*, tenant_id: str = "t1"):
            raise RuntimeError("agent-runtime not configured")
        monkeypatch.setattr(proxy_main, "resolve_llm_integration", _bad_resolve)

        r = authed_client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer any"},
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert r.status_code == 502, r.text
        assert "agent-runtime" in r.json()["detail"]
