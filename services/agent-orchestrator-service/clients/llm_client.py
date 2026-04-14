"""
clients/llm_client.py
──────────────────────
LLM API abstractions.

Production (Anthropic):  LLMClient       — requires ANTHROPIC_API_KEY
Docker Model Runner:     DockerModelClient — uses Docker's local OpenAI-compatible API
Testing/dev:             MockLLMClient   — returns canned responses, tracks calls

Streaming is returned as an async generator of text chunks.

Anthropic model string examples:
  claude-haiku-4-5-20251001   (fast, cheap)
  claude-sonnet-4-6            (balanced)
  claude-opus-4-6              (best quality)

Docker Model Runner:
  Base URL: http://localhost:12434/engines/v1  (default)
  Model:    ai/smollm2  (or any model pulled with `docker model pull`)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import AsyncIterator, List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Response model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class LLMResponse:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = "end_turn"


# ─────────────────────────────────────────────────────────────────────────────
# Real client
# ─────────────────────────────────────────────────────────────────────────────

class LLMClient:
    """
    Async Anthropic Claude client.

    Args:
        api_key:    Anthropic API key (required for real calls).
        model:      Claude model string.
        max_tokens: Maximum output tokens per completion.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-haiku-4-5-20251001",
        max_tokens: int = 2048,
    ):
        self.model = model
        self._max_tokens = max_tokens
        self._api_key = api_key
        self._client = None  # lazy-init — avoids import-time errors if package missing

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
            except ImportError:
                raise RuntimeError(
                    "anthropic package not installed. Run: pip install anthropic"
                )
        return self._client

    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        tools: Optional[List[dict]] = None,
    ) -> LLMResponse:
        """Send a single completion request."""
        client = self._get_client()
        messages = [{"role": "user", "content": prompt}]
        kwargs: dict = {
            "model": self.model,
            "max_tokens": self._max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        logger.debug("LLMClient.complete model=%s prompt_len=%d", self.model, len(prompt))
        response = await client.messages.create(**kwargs)
        text = "".join(
            block.text for block in response.content
            if hasattr(block, "text")
        )
        return LLMResponse(
            text=text,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            stop_reason=response.stop_reason or "end_turn",
        )

    async def stream(
        self,
        prompt: str,
        system: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """Stream text chunks as an async generator."""
        client = self._get_client()
        messages = [{"role": "user", "content": prompt}]
        kwargs: dict = {
            "model": self.model,
            "max_tokens": self._max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        async with client.messages.stream(**kwargs) as stream:
            async for chunk in stream.text_stream:
                yield chunk


# ─────────────────────────────────────────────────────────────────────────────
# Docker Model Runner client
# ─────────────────────────────────────────────────────────────────────────────

class DockerModelClient:
    """
    Async client for Docker Model Runner's OpenAI-compatible API.

    Docker Model Runner exposes a local endpoint that mirrors the OpenAI
    chat-completions API, so any model pulled with `docker model pull`
    can be called here without an API key.

    Args:
        model:    Model name as shown in `docker model list`
                  (e.g. "ai/smollm2", "ai/llama3.2", "ai/phi4-mini").
        base_url: Docker Model Runner API base URL.
                  Default: http://localhost:12434/engines/v1
        max_tokens: Maximum output tokens per completion.
    """

    DEFAULT_BASE_URL = "http://localhost:12434/engines/v1"

    def __init__(
        self,
        model: str = "ai/smollm2",
        base_url: str = DEFAULT_BASE_URL,
        max_tokens: int = 2048,
    ):
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._max_tokens = max_tokens
        self._client = None  # lazy-init

    def _get_client(self):
        if self._client is None:
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(
                    base_url=self._base_url,
                    api_key="docker",  # Docker Model Runner ignores the key value
                )
            except ImportError:
                raise RuntimeError(
                    "openai package not installed. Run: pip install openai"
                )
        return self._client

    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        tools: Optional[List[dict]] = None,
    ) -> LLMResponse:
        """Send a single chat-completion request to Docker Model Runner."""
        client = self._get_client()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        kwargs: dict = {
            "model": self.model,
            "max_tokens": self._max_tokens,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        logger.debug(
            "DockerModelClient.complete model=%s prompt_len=%d",
            self.model, len(prompt),
        )
        response = await client.chat.completions.create(**kwargs)
        text = response.choices[0].message.content or ""
        usage = response.usage
        return LLMResponse(
            text=text,
            model=response.model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            stop_reason=response.choices[0].finish_reason or "stop",
        )

    async def stream(
        self,
        prompt: str,
        system: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """Stream text chunks from Docker Model Runner as an async generator."""
        client = self._get_client()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        stream = await client.chat.completions.create(
            model=self.model,
            max_tokens=self._max_tokens,
            messages=messages,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta


# ─────────────────────────────────────────────────────────────────────────────
# Mock client (for tests and dev)
# ─────────────────────────────────────────────────────────────────────────────

class MockLLMClient:
    """
    In-memory mock — no HTTP calls, no API key required.
    Inject this in tests and local dev.
    """

    def __init__(self, response_text: str = "Mock LLM response."):
        self._response = response_text
        self.call_count = 0
        self.last_prompt: Optional[str] = None
        self.model = "mock-claude"

    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        tools: Optional[List[dict]] = None,
    ) -> LLMResponse:
        self.call_count += 1
        self.last_prompt = prompt
        return LLMResponse(
            text=self._response,
            model=self.model,
            input_tokens=len(prompt.split()),
            output_tokens=len(self._response.split()),
        )

    async def stream(self, prompt: str, system: Optional[str] = None) -> AsyncIterator[str]:
        for word in self._response.split():
            yield word + " "
