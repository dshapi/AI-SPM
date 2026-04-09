# tests/clients/test_llm_client.py
import pytest
from clients.llm_client import LLMClient, LLMResponse, MockLLMClient

@pytest.mark.asyncio
async def test_mock_client_returns_response():
    client = MockLLMClient(response_text="Hello, world!")
    resp = await client.complete("Say hello")
    assert resp.text == "Hello, world!"
    assert resp.model is not None
    assert resp.input_tokens > 0
    assert resp.output_tokens > 0

@pytest.mark.asyncio
async def test_mock_client_tracks_calls():
    client = MockLLMClient(response_text="test")
    await client.complete("prompt 1")
    await client.complete("prompt 2")
    assert client.call_count == 2

def test_llm_client_instantiates_without_package():
    # Must not raise — lazy import means package absence is OK until actual call
    client = LLMClient(api_key="fake-key", model="claude-haiku-4-5-20251001")
    assert client.model == "claude-haiku-4-5-20251001"

@pytest.mark.asyncio
async def test_mock_client_honours_system_prompt():
    client = MockLLMClient(response_text="ok")
    resp = await client.complete("prompt", system="You are helpful")
    assert resp.text == "ok"

@pytest.mark.asyncio
async def test_mock_client_last_prompt_tracked():
    client = MockLLMClient(response_text="response")
    await client.complete("my test prompt")
    assert client.last_prompt == "my test prompt"

@pytest.mark.asyncio
async def test_mock_client_stream():
    client = MockLLMClient(response_text="hello world")
    chunks = []
    async for chunk in client.stream("prompt"):
        chunks.append(chunk)
    assert len(chunks) > 0
    assert "".join(chunks).strip() == "hello world"

def test_llm_response_dataclass():
    resp = LLMResponse(text="hi", model="claude", input_tokens=5, output_tokens=3)
    assert resp.text == "hi"
    assert resp.stop_reason == "end_turn"  # default
