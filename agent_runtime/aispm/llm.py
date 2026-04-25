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

import logging
from typing import Any, Dict, List, Optional

import httpx

from . import LLM_API_KEY as _API_KEY, LLM_BASE_URL as _BASE_URL
from .types import Completion

log = logging.getLogger(__name__)

# LLM calls can be slow on cold-start models; 120s matches the proxy's
# upstream timeout so we surface the same error as the proxy returns.
_TIMEOUT_S = 120

# Default model name when the customer doesn't pin one. Matches
# spm-mcp's ``default_model_name`` default. Operators override per
# agent via the Configure tab.
_DEFAULT_MODEL = "llama3.1:8b"


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
        "model":       model or _DEFAULT_MODEL,
        "messages":    list(messages),
        "max_tokens":  max_tokens,
        "temperature": temperature,
    }
    headers = {"Authorization": f"Bearer {_API_KEY}"}

    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as c:
        r = await c.post(f"{_BASE_URL}/chat/completions",
                          json=body, headers=headers)
    r.raise_for_status()

    data = r.json()
    return Completion(
        text=  data["choices"][0]["message"]["content"],
        model= data.get("model", body["model"]),
        usage= dict(data.get("usage") or {}),
    )
