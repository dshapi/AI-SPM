"""Convenience wrapper around spm-llm-proxy's OpenAI-compatible API.

Most LangChain / OpenAI-SDK users will hit the proxy directly via
``ChatOpenAI(base_url=aispm.LLM_BASE_URL, api_key=aispm.LLM_API_KEY)``
since the proxy speaks the OpenAI shape. This wrapper exists for the
"no-framework" path — agents that just want one-line LLM calls
without pulling in a heavy SDK.

The proxy translates to the configured upstream (Ollama by default)
and re-wraps the response in OpenAI shape, so this client only ever
needs to speak OpenAI.
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from . import LLM_API_KEY as _API_KEY, LLM_BASE_URL as _BASE_URL
from .types import Completion

log = logging.getLogger(__name__)

# LLM calls can be slow on cold-start models; 120s matches the proxy's
# upstream timeout so we surface the same error as the proxy returns.
_TIMEOUT_S = 120

# No SDK-side default model. The customer can pin one explicitly via
# ``aispm.llm.complete(..., model="...")``, but if they don't we leave
# the field empty and let spm-llm-proxy fill it from the configured
# upstream integration's ``model`` field (e.g. ``claude-sonnet-4-6``
# on Anthropic, ``llama3.1:8b`` on Ollama). Pinning a value here is
# wrong: the SDK can't know which provider the operator picked.
_DEFAULT_MODEL = ""


def _raise_for_status_with_detail(r: httpx.Response) -> None:
    """Like ``r.raise_for_status()`` but appends the response body's
    ``detail`` (FastAPI's HTTPException shape) so the caller's
    ``str(e)`` actually says *why* the proxy errored.

    Without this, the customer agent's ``f"(agent error: {e})"``
    surfaces only ``Server error '502 Bad Gateway' for url '...'``,
    throwing away the proxy's hard-won diagnostic
    (e.g. "Anthropic upstream is missing api_key — configure it on
    the Anthropic integration"). The default httpx message format is
    preserved so any code that pattern-matches on it still works;
    detail is appended on a new line.
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


async def complete(
    messages: List[Dict[str, str]],
    *,
    model:       Optional[str] = None,
    max_tokens:  int  = 2048,
    temperature: float = 0.7,
) -> Completion:
    """One-shot OpenAI chat-completion call via the platform proxy.

    Parameters
    ──────────
    messages : list of {"role": "system|user|assistant", "content": str}
        The OpenAI message list. No automatic system-prompt injection —
        agents control the full prompt.
    model : str, optional
        Pin a specific upstream model. Defaults to the proxy's
        configured default.
    max_tokens, temperature
        OpenAI's standard knobs. Forwarded as-is.

    Returns
    ───────
    Completion
        ``text`` is the assistant's content; ``model`` is whichever
        the upstream actually used; ``usage`` is the token-accounting
        dict from the upstream (shape varies by provider).

    Raises
    ──────
    httpx.HTTPStatusError on non-2xx — surfaces the proxy's 401 (bad
    LLM_API_KEY), 502 (upstream unavailable), 504 (upstream timeout).
    """
    if not _BASE_URL or not _API_KEY:
        raise RuntimeError(
            "aispm.llm.complete: LLM_BASE_URL / LLM_API_KEY env vars "
            "are not set (agent was not spawned by the controller?)"
        )

    body: Dict[str, Any] = {
        "messages":    list(messages),
        "max_tokens":  max_tokens,
        "temperature": temperature,
    }
    # Only include `model` when the caller actually picked one. Empty
    # string ⇒ proxy fills in the upstream integration's configured
    # model. Anything truthy is forwarded verbatim.
    chosen = (model or _DEFAULT_MODEL).strip()
    if chosen:
        body["model"] = chosen
    headers = {"Authorization": f"Bearer {_API_KEY}"}

    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as c:
        r = await c.post(f"{_BASE_URL}/chat/completions",
                          json=body, headers=headers)
    _raise_for_status_with_detail(r)

    data = r.json()
    return Completion(
        text=  data["choices"][0]["message"]["content"],
        # Prefer whatever the upstream actually echoed; fall back to
        # the model we asked for, or the empty string when neither
        # the SDK nor the caller pinned one.
        model= data.get("model") or body.get("model", ""),
        usage= dict(data.get("usage") or {}),
    )


async def stream(
    messages: List[Dict[str, str]],
    *,
    model:       Optional[str] = None,
    max_tokens:  int  = 2048,
    temperature: float = 0.7,
) -> AsyncIterator[str]:
    """Streaming OpenAI chat-completion call via the platform proxy.

    Same shape as ``complete()`` but yields each delta_text as it
    arrives from the upstream model, rather than buffering until the
    full reply is ready. Use this in chat agents to get sub-second
    time-to-first-token.

    Parameters
    ──────────
    messages, model, max_tokens, temperature
        Same as ``complete()``.

    Yields
    ──────
    str
        Each ``choices[0].delta.content`` chunk from the OpenAI-compat
        stream, in arrival order. The empty string is filtered out
        (some providers send keepalive frames with no content).

    Raises
    ──────
    httpx.HTTPStatusError on non-2xx — surfaces the proxy's 401 (bad
    LLM_API_KEY), 502 (upstream unavailable), 504 (upstream timeout).

    Implementation note
    ───────────────────
    Hand-rolled SSE parsing — no extra dependency on httpx-sse. The
    proxy emits standard OpenAI streaming format:

        data: {"choices":[{"delta":{"content":"Hello"}, ...}]}\\n\\n
        data: {"choices":[{"delta":{"content":" world"}, ...}]}\\n\\n
        data: [DONE]\\n\\n

    We line-buffer with httpx.aiter_lines(), strip the ``data: ``
    prefix, sentinel out on ``[DONE]``, and json.loads the remainder.
    Malformed lines (e.g. a comment ``: keepalive``) are silently
    skipped — the proxy occasionally emits these.
    """
    if not _BASE_URL or not _API_KEY:
        raise RuntimeError(
            "aispm.llm.stream: LLM_BASE_URL / LLM_API_KEY env vars "
            "are not set (agent was not spawned by the controller?)"
        )

    body: Dict[str, Any] = {
        "messages":    list(messages),
        "max_tokens":  max_tokens,
        "temperature": temperature,
        "stream":      True,
    }
    chosen = (model or _DEFAULT_MODEL).strip()
    if chosen:
        body["model"] = chosen
    headers = {
        "Authorization": f"Bearer {_API_KEY}",
        "Accept":        "text/event-stream",
    }

    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as c:
        async with c.stream("POST",
                            f"{_BASE_URL}/chat/completions",
                            json=body, headers=headers) as r:
            # On 4xx/5xx the body holds the proxy's diagnostic; we have
            # to read it before raising so the detail surfaces. httpx's
            # streaming context defers body load, hence the explicit
            # aread() below.
            if r.status_code >= 400:
                await r.aread()
                _raise_for_status_with_detail(r)
                return                                          # unreachable

            async for line in r.aiter_lines():
                if not line:                                    # keepalive
                    continue
                if line.startswith(":"):                        # SSE comment
                    continue
                if not line.startswith("data:"):
                    log.debug("stream: unexpected non-data line=%r", line)
                    continue

                payload = line[len("data:"):].strip()
                if payload == "[DONE]":
                    return
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    log.debug("stream: malformed json line=%r", payload)
                    continue

                # OpenAI-compat shape: choices[0].delta.content
                # Defensive: some providers omit choices on the first
                # frame (sending only the role), or send a delta with
                # no content. We yield only non-empty content strings.
                try:
                    choice = obj["choices"][0]
                except (KeyError, IndexError):
                    continue
                delta = choice.get("delta") or {}
                text  = delta.get("content")
                if text:
                    yield text
