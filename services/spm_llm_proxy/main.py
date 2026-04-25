"""spm-llm-proxy — OpenAI-compatible HTTP shim in front of the configured
AI Provider integration.

Deployed as one container per stack. Each customer agent is issued a
``llm_api_key`` (Phase 1 mints these at deploy time, Phase 2 will
encrypt at rest); the agent's HTTP client points at this proxy with
that bearer token. The proxy:

  1. Authenticates the caller against the ``agents.llm_api_key`` column
     so unknown / retired tokens get a clean 401.
  2. Resolves which upstream LLM integration backs the proxy via the
     agent-runtime ConnectorType's ``default_llm_integration_id`` field
     (set in Integrations → "AI-SPM Agent Runtime Control Plane (MCP)").
  3. Translates the OpenAI-shaped request to the upstream provider's
     native shape and forwards.

Phase 1 supports Ollama upstream out of the box (the default in
docker-compose); other providers route through the same code path
because the resolver returns base_url + creds keyed by the FieldSpec.

Phase 2 will add: streaming responses, request/response audit
emission to the lineage pipeline, per-tenant rate limits.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException

from .router import resolve_llm_integration

log = logging.getLogger(__name__)

app = FastAPI(title="spm-llm-proxy", version="0.1.0")


# ─── /health ────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    """Liveness probe — used by docker-compose healthcheck and the
    ``probe_agent_runtime`` connector probe."""
    return {"ok": True}


# ─── Auth dependency ────────────────────────────────────────────────────────

async def _auth_required(authorization: str = Header(...)) -> Dict[str, Any]:
    """Resolve the caller's bearer token against the agents table.

    Returns the agent dict ``{id, tenant_id, name}`` on hit; raises 401
    on miss. Header parsing is permissive — both ``Bearer foo`` and
    ``foo`` are accepted (some HTTP clients strip the prefix).
    """
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    from platform_shared.agent_tokens import resolve_agent_by_llm_token
    agent = await resolve_agent_by_llm_token(token)
    if agent is None:
        raise HTTPException(status_code=401, detail="Unknown llm_api_key")
    return agent


# ─── /v1/chat/completions ───────────────────────────────────────────────────

# Default upstream when the resolved integration's config lacks a base_url
# (e.g. an Ollama row that hasn't been edited). Matches the docker-compose
# Ollama service name.
_DEFAULT_OLLAMA_BASE = "http://ollama:11434"


def _ollama_request_body(payload: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Translate an OpenAI chat-completions request to Ollama's /api/chat."""
    return {
        "model":   payload.get("model") or cfg.get("model_name") or "llama3.1:8b",
        "messages": payload["messages"],
        "stream":  False,
    }


def _to_openai_response(out: Dict[str, Any], model: str) -> Dict[str, Any]:
    """Wrap an Ollama /api/chat response in the OpenAI chat-completion shape."""
    return {
        "id":      "chatcmpl-spm-1",
        "object":  "chat.completion",
        "model":   model,
        "choices": [{
            "index":         0,
            "message":       out.get("message") or {"role": "assistant", "content": ""},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens":     out.get("prompt_eval_count", 0),
            "completion_tokens": out.get("eval_count", 0),
            "total_tokens":      (out.get("prompt_eval_count", 0)
                                  + out.get("eval_count", 0)),
        },
    }


@app.post("/v1/chat/completions")
async def chat_completions(
    payload: Dict[str, Any],
    agent:   Dict[str, Any] = Depends(_auth_required),
):
    """Forward an OpenAI-shaped chat-completions request to the configured
    upstream LLM integration.

    Behaviour:
      - Resolves the upstream via ``resolve_llm_integration(tenant_id)``.
      - Phase 1 only knows how to forward to Ollama; other providers will
        succeed if their config carries a compatible /api/chat or
        /v1/chat/completions base, but are best-effort. Native dispatch
        per-provider is Phase 2.
      - Returns the upstream's reply re-wrapped in OpenAI shape so the
        agent's existing OpenAI-compatible client (e.g. langchain
        ChatOpenAI) keeps working.
    """
    if "messages" not in payload:
        raise HTTPException(status_code=400, detail="`messages` is required")

    try:
        cfg, _creds = await resolve_llm_integration(tenant_id=agent["tenant_id"])
    except RuntimeError as e:
        log.warning("llm-proxy: resolution failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e))

    base   = (cfg.get("base_url") or _DEFAULT_OLLAMA_BASE).rstrip("/")
    body   = _ollama_request_body(payload, cfg)
    upstream_url = f"{base}/api/chat"

    try:
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(upstream_url, json=body)
        r.raise_for_status()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Upstream LLM timed out")
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Upstream LLM error: {e}")

    return _to_openai_response(r.json(), body["model"])
