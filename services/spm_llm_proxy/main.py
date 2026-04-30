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

import json
import logging
from typing import Any, AsyncIterator, Dict, Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse

from .router import resolve_llm_integration

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

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


def _ollama_to_openai_response(out: Dict[str, Any], model: str) -> Dict[str, Any]:
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


# ─── Anthropic native dispatch ─────────────────────────────────────────────
#
# /v1/messages takes ``system`` as a top-level field (not a role-system
# message), uses ``x-api-key`` + ``anthropic-version`` headers, and
# returns ``content: [{type:'text', text:...}]``. We translate both
# directions so the agent's OpenAI-compatible client stays unchanged.

def _split_anthropic_messages(messages):
    system_chunks = []
    out = []
    for m in (messages or []):
        role    = (m.get("role") or "user").lower()
        content = m.get("content", "")
        if role == "system":
            if content:
                system_chunks.append(str(content))
            continue
        if role not in ("user", "assistant"):
            role = "user"
        out.append({"role": role, "content": content})
    return "\n\n".join(system_chunks), out


def _anthropic_request_body(payload, cfg):
    system, msgs = _split_anthropic_messages(payload.get("messages") or [])
    # Operator's configured model (on the Anthropic integration) wins
    # over whatever the agent's SDK happened to default to. The agent
    # has no way of knowing which model the upstream supports — it
    # could send `llama3.1:8b` (the legacy SDK default) which Anthropic
    # would 404. Only honour ``payload["model"]`` if it looks like an
    # Anthropic model name (i.e. starts with ``claude``).
    cfg_model = cfg.get("model") or cfg.get("model_name")
    pl_model  = (payload.get("model") or "").strip()
    if pl_model.lower().startswith("claude"):
        chosen_model = pl_model
    else:
        chosen_model = cfg_model or "claude-sonnet-4-6"
    body = {
        "model":      chosen_model,
        "messages":   msgs,
        "max_tokens": int(payload.get("max_tokens") or 1024),
    }
    if system:
        body["system"] = system
    if "temperature" in payload:
        body["temperature"] = payload["temperature"]
    return body


def _anthropic_to_openai_response(out, model):
    blocks = out.get("content") or []
    text_parts = [b.get("text", "") for b in blocks
                   if isinstance(b, dict) and b.get("type") == "text"]
    text = "".join(text_parts)
    usage = out.get("usage") or {}
    return {
        "id":      out.get("id") or "chatcmpl-spm-1",
        "object":  "chat.completion",
        "model":   model,
        "choices": [{
            "index":         0,
            "message":       {"role": "assistant", "content": text},
            "finish_reason": out.get("stop_reason") or "stop",
        }],
        "usage": {
            "prompt_tokens":     int(usage.get("input_tokens",  0) or 0),
            "completion_tokens": int(usage.get("output_tokens", 0) or 0),
            "total_tokens":      int(usage.get("input_tokens",  0) or 0)
                                  + int(usage.get("output_tokens", 0) or 0),
        },
    }


def _emit_llm_event(*, agent_id, tenant_id, model, prompt_tokens, completion_tokens, ok, trace_id):
    """Phase 4.5 — fire-and-forget AgentLLMCallEvent. Best-effort.

    Called from both success and failure paths of /v1/chat/completions
    so the audit trail covers latency-relevant events even when the
    upstream errored. Token counts are 0 on failure paths (we didn't
    consume any).
    """
    try:
        from platform_shared.lineage_producer import emit_agent_event
        from platform_shared.lineage_events   import AgentLLMCallEvent
        evt = AgentLLMCallEvent(
            agent_id          = str(agent_id or ""),
            tenant_id         = str(tenant_id or ""),
            model             = str(model or ""),
            prompt_tokens     = int(prompt_tokens or 0),
            completion_tokens = int(completion_tokens or 0),
            trace_id          = str(trace_id or ""),
        ).to_dict()
        # Annotate ok/!ok in the payload so the consumer can colour
        # error rows differently even though the dataclass shape is fixed.
        evt["ok"] = bool(ok)
        emit_agent_event(
            session_id     = f"agent-{agent_id}-runtime",
            event_type     = "AgentLLMCall",
            payload        = evt,
            agent_id       = str(agent_id or ""),
            tenant_id      = str(tenant_id or ""),
            correlation_id = str(trace_id or "") or None,
            source         = "spm-llm-proxy",
        )
    except Exception:                                      # noqa: BLE001
        log.debug("llm-proxy: lineage emit failed", exc_info=True)


async def _stream_openai_compat(
    *,
    url:          str,
    body:         Dict[str, Any],
    agent_id:     Optional[str],
    tenant_id:    Optional[str],
    chosen_model: str,
    trace_id:     str,
) -> AsyncIterator[bytes]:
    """Stream from an OpenAI-compatible upstream (Ollama, vLLM, etc.) and
    yield raw SSE bytes back to the caller.

    The upstream emits the canonical
    ``data: {choices[0].delta.content}\\n\\n`` frames + a terminal
    ``data: [DONE]\\n\\n``; we forward each line verbatim with the
    SSE record separator restored (``aiter_lines`` strips trailing
    newlines).

    Side effect: opportunistically parses each frame to accumulate
    usage stats + completion text so we can emit one
    ``llm.completed`` lineage event when the stream finishes.
    """
    completion_text:    str = ""
    prompt_tokens:      int = 0
    completion_tokens:  int = 0
    ok:                 bool = True
    error_detail:       Optional[str] = None

    try:
        async with httpx.AsyncClient(timeout=120) as c:
            async with c.stream("POST", url, json=body) as r:
                if r.status_code != 200:
                    # Read the (now-buffered) error body and surface a
                    # single SSE error frame so the client doesn't hang.
                    await r.aread()
                    err_text = (r.text or "").strip()[:400]
                    log.warning(
                        "llm-proxy: ollama stream returned %d: %s",
                        r.status_code, err_text,
                    )
                    ok = False
                    error_detail = (
                        f"Upstream LLM (ollama) returned "
                        f"{r.status_code}: {err_text}"
                    )
                    err_envelope = {
                        "error": {
                            "message": error_detail,
                            "type":    "upstream_error",
                            "code":    r.status_code,
                        }
                    }
                    yield (f"data: {json.dumps(err_envelope)}\n\n").encode()
                    yield b"data: [DONE]\n\n"
                    return

                async for line in r.aiter_lines():
                    if not line:
                        continue
                    # Forward verbatim — the upstream already speaks
                    # the OpenAI SSE shape our SDK expects.
                    yield (line + "\n\n").encode()

                    # Bookkeeping for the audit event. Best-effort —
                    # malformed frames just don't contribute.
                    if not line.startswith("data:"):
                        continue
                    payload_str = line[len("data:"):].strip()
                    if payload_str == "[DONE]":
                        break
                    try:
                        obj = json.loads(payload_str)
                    except json.JSONDecodeError:
                        continue
                    usage = obj.get("usage") or {}
                    if usage:
                        prompt_tokens     = usage.get("prompt_tokens",
                                                       prompt_tokens)
                        completion_tokens = usage.get("completion_tokens",
                                                       completion_tokens)
                    choices = obj.get("choices") or []
                    if choices:
                        delta = choices[0].get("delta") or {}
                        content = delta.get("content")
                        if content:
                            completion_text += content
    except httpx.HTTPError as exc:
        ok = False
        error_detail = f"transport error: {exc!s}"
        log.warning("llm-proxy: stream transport error: %s", exc)
        yield (
            f"data: {json.dumps({'error': {'message': error_detail}})}\n\n"
        ).encode()
        yield b"data: [DONE]\n\n"

    # Emit the lineage event once on stream completion (success OR
    # failure) so the audit log records one row per chat turn.
    _emit_llm_event(
        agent_id=agent_id, tenant_id=tenant_id, model=chosen_model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens or len(completion_text.split()),
        ok=ok, trace_id=trace_id,
    )


@app.post("/v1/chat/completions")
async def chat_completions(
    payload: Dict[str, Any],
    agent:   Dict[str, Any] = Depends(_auth_required),
):
    """Forward an OpenAI-shaped chat-completions request to the configured
    upstream LLM integration. Provider-native dispatch — branches on the
    upstream integration's ``connector_type`` and translates request +
    response shape so the agent's OpenAI-compatible client stays
    untouched regardless of which provider the operator picked.
    """
    if "messages" not in payload:
        raise HTTPException(status_code=400, detail="`messages` is required")

    agent_id  = agent.get("id")
    tenant_id = agent.get("tenant_id")
    trace_id  = payload.get("trace_id") or ""

    try:
        connector_type, cfg, creds = await resolve_llm_integration(
            tenant_id=agent["tenant_id"],
        )
    except RuntimeError as e:
        log.warning("llm-proxy: resolution failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e))

    log.info(
        "llm-proxy: dispatching connector_type=%r model_cfg=%r base_url=%r "
        "creds_keys=%r",
        connector_type,
        cfg.get("model") or cfg.get("model_name"),
        cfg.get("base_url"),
        sorted(list(creds.keys())),
    )

    try:
        if connector_type == "anthropic":
            base    = (cfg.get("base_url") or "https://api.anthropic.com").rstrip("/")
            api_key = creds.get("api_key", "")
            if not api_key:
                log.warning(
                    "llm-proxy: anthropic api_key missing or empty — "
                    "creds keys present: %s",
                    sorted(list(creds.keys())),
                )
                raise HTTPException(
                    status_code=502,
                    detail="Anthropic upstream is missing api_key — "
                            "configure it on the Anthropic integration",
                )
            body = _anthropic_request_body(payload, cfg)
            log.info("llm-proxy: anthropic POST %s/v1/messages model=%s "
                     "msgs=%d sys_chars=%d",
                     base, body.get("model"),
                     len(body.get("messages") or []),
                     len(body.get("system") or ""))
            async with httpx.AsyncClient(timeout=120) as c:
                r = await c.post(
                    f"{base}/v1/messages",
                    json=body,
                    headers={
                        "x-api-key":         api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type":      "application/json",
                    },
                )
            if r.status_code != 200:
                log.warning(
                    "llm-proxy: anthropic returned %d: %s",
                    r.status_code, r.text[:600],
                )
                raise HTTPException(
                    status_code=502,
                    detail=f"Anthropic upstream error {r.status_code}: "
                            f"{r.text[:400]}",
                )
            wrapped = _anthropic_to_openai_response(r.json(), body["model"])
            _emit_llm_event(
                agent_id=agent_id, tenant_id=tenant_id,
                model=body["model"],
                prompt_tokens=wrapped.get("usage", {}).get("prompt_tokens", 0),
                completion_tokens=wrapped.get("usage", {}).get("completion_tokens", 0),
                ok=True, trace_id=trace_id,
            )
            return wrapped

        # Default / legacy path — Ollama-style upstream.
        # Ollama exposes two transports off its port:
        #   1. Native:       POST /api/chat            (request body is
        #                    Ollama-specific, response is Ollama-specific)
        #   2. OpenAI-compat: POST /v1/chat/completions (forward as-is)
        # Operators commonly set base_url to either ``http://host:11434``
        # or ``http://host:11434/v1`` depending on which mode they want.
        # We branch on the trailing ``/v1`` so both work — the user
        # doesn't have to know that the proxy translates differently
        # for one vs. the other.
        base = (cfg.get("base_url") or _DEFAULT_OLLAMA_BASE).rstrip("/")
        # Ollama can serve any pulled model — let the caller pin
        # whichever one they want via payload.model. Fall back to the
        # operator's configured cfg model only when the caller didn't
        # specify one.
        cfg_model = cfg.get("model") or cfg.get("model_name")
        pl_model  = (payload.get("model") or "").strip()
        chosen_model = (pl_model or cfg_model or "llama3.1:8b")

        if base.endswith("/v1"):
            # OpenAI-compatible mode — forward verbatim.
            url  = f"{base}/chat/completions"
            stream_requested = bool(payload.get("stream"))
            body = {
                "model":       chosen_model,
                "messages":    payload.get("messages") or [],
                # We honour the caller's stream flag; the proxy used to
                # hardcode False, which buffered the upstream and broke
                # the agent-runtime SDK's aispm.llm.stream() path.
                "stream":      stream_requested,
            }
            if "temperature" in payload:
                body["temperature"] = payload["temperature"]
            if "max_tokens" in payload:
                body["max_tokens"] = payload["max_tokens"]
            log.info("llm-proxy: ollama (openai-compat) POST %s model=%s "
                     "stream=%s",
                     url, chosen_model, stream_requested)

            if stream_requested:
                # Stream upstream → forward SSE bytes verbatim. Ollama's
                # OpenAI-compat endpoint already emits the standard
                # `data: {choices[0].delta.content}\n\n` shape, so we
                # don't have to translate. We also accumulate the
                # delta text for the audit-event emission at the end.
                return StreamingResponse(
                    _stream_openai_compat(
                        url=url, body=body,
                        agent_id=agent_id, tenant_id=tenant_id,
                        chosen_model=chosen_model, trace_id=trace_id,
                    ),
                    media_type="text/event-stream",
                )

            async with httpx.AsyncClient(timeout=120) as c:
                r = await c.post(url, json=body)
            if r.status_code != 200:
                log.warning(
                    "llm-proxy: ollama openai-compat returned %d: %s",
                    r.status_code, r.text[:600],
                )
                raise HTTPException(
                    status_code=502,
                    detail=f"Upstream LLM (ollama) returned "
                            f"{r.status_code}: {r.text[:400]}",
                )
            # Already OpenAI shape — pass through.
            wrapped = r.json()
            _emit_llm_event(
                agent_id=agent_id, tenant_id=tenant_id, model=chosen_model,
                prompt_tokens=wrapped.get("usage", {}).get("prompt_tokens", 0),
                completion_tokens=wrapped.get("usage", {}).get("completion_tokens", 0),
                ok=True, trace_id=trace_id,
            )
            return wrapped

        # Native Ollama path.
        url  = f"{base}/api/chat"
        body = _ollama_request_body(payload, cfg)
        body["model"] = chosen_model        # operator wins over legacy SDK
        log.info("llm-proxy: ollama (native) POST %s model=%s",
                 url, chosen_model)
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(url, json=body)
        if r.status_code != 200:
            log.warning(
                "llm-proxy: ollama native returned %d: %s",
                r.status_code, r.text[:600],
            )
            raise HTTPException(
                status_code=502,
                detail=f"Upstream LLM ({connector_type or 'ollama'}) "
                        f"returned {r.status_code}: {r.text[:400]}",
            )
        wrapped = _ollama_to_openai_response(r.json(), body["model"])
        _emit_llm_event(
            agent_id=agent_id, tenant_id=tenant_id, model=body["model"],
            prompt_tokens=wrapped.get("usage", {}).get("prompt_tokens", 0),
            completion_tokens=wrapped.get("usage", {}).get("completion_tokens", 0),
            ok=True, trace_id=trace_id,
        )
        return wrapped

    except httpx.TimeoutException:
        _emit_llm_event(agent_id=agent_id, tenant_id=tenant_id, model="",
                        prompt_tokens=0, completion_tokens=0,
                        ok=False, trace_id=trace_id)
        raise HTTPException(status_code=504, detail="Upstream LLM timed out")
    except HTTPException:
        # _emit_llm_event already happened on the explicit-error paths
        # (anthropic-returned-non-200 / ollama-returned-non-200) — but
        # a fresh HTTPException raised here without emit means we hit
        # the api_key-missing branch. Emit ok=False once and re-raise.
        _emit_llm_event(agent_id=agent_id, tenant_id=tenant_id, model="",
                        prompt_tokens=0, completion_tokens=0,
                        ok=False, trace_id=trace_id)
        raise
    except Exception as e:                                # noqa: BLE001
        # Surface anything else as a clean 502 with the message; better
        # than a bare 500 the agent gets as "Server error '500 Internal
        # Server Error'" with nothing to act on.
        log.exception("llm-proxy: unexpected upstream error")
        _emit_llm_event(agent_id=agent_id, tenant_id=tenant_id, model="",
                        prompt_tokens=0, completion_tokens=0,
                        ok=False, trace_id=trace_id)
        raise HTTPException(
            status_code=502,
            detail=f"llm-proxy upstream error: {type(e).__name__}: {e}",
        )
