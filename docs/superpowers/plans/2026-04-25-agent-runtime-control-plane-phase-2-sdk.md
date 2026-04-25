# Agent Runtime Control Plane — Phase 2: Agent SDK Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `aispm` Python package that customer-uploaded agents `import` to talk to the platform. The package wraps the four wires Phase 1 already exposes — Kafka chat I/O, the MCP tool server, the OpenAI-compat LLM proxy, and a controller HTTP endpoint for secrets — in a clean, type-safe API. Replace the Phase 1 stub `agent_runtime/Dockerfile` with the real image that pre-installs the SDK and runs the customer's `agent.py` against it.

**Architecture:** A new `agent_runtime/aispm/` package containing seven modules (`__init__`, `types`, `chat`, `mcp`, `llm`, `secrets`, `lifecycle`, `log`). Each module is one focused public surface; shared connection info is module-level constants populated from env vars at import time. The runtime container's entrypoint (`agent_runtime/loader.py`) imports `aispm`, then `exec()`s the customer's `/agent/agent.py`. No customer-facing config beyond what the spec §8 contract spells out.

**Tech Stack:** Python 3.12 inside the container; `kafka-python-ng` for Kafka, `httpx` for HTTP, `mcp` (the official Python SDK) for MCP framing, `pydantic` for typed payloads. Tests use the existing `pytest` setup; we mock all four wires the same way Phase 1 mocks Docker / Kafka.

**Reference spec:** `docs/superpowers/specs/2026-04-25-agent-runtime-control-plane-mcp-design.md` § 8 (Agent SDK contract).

**Reference Phase 1 plan:** `docs/superpowers/plans/2026-04-25-agent-runtime-control-plane-phase-1-backend.md`

---

## File Structure

### New files

```
agent_runtime/
  Dockerfile                                            # replaces Phase 1 stub
  loader.py                                             # entrypoint that runs customer agent.py
  aispm/
    __init__.py                                         # public re-exports + env-driven constants
    types.py                                            # ChatMessage, HistoryEntry, Completion
    chat.py                                             # Kafka in/out wrappers
    mcp.py                                              # HTTP MCP client
    llm.py                                              # OpenAI-compat client
    secrets.py                                          # get_secret()
    lifecycle.py                                        # ready(), signals
    log.py                                              # structured lineage emitter
  examples/
    hello_world.py                                      # ~10-line agent from spec §8
    langchain_research.py                               # ~20-line LangChain agent

tests/aispm/
  conftest.py                                           # shared aispm-test fixtures
  test_constants.py                                     # env → module-level constants
  test_types.py
  test_chat.py
  test_mcp.py
  test_llm.py
  test_secrets.py
  test_lifecycle.py
  test_log.py

tests/e2e/
  test_aispm_sdk_smoke.py                               # end-to-end against running stack
```

### Modified files

```
agent_runtime/Dockerfile                                # full image, replaces stub
services/spm_api/agent_routes.py                        # add /agents/{id}/secrets endpoint (Task 7)
services/spm_api/agent_controller.py                    # poll loader's /ready (replace 5s sleep)
```

---

## Task 1: aispm package skeleton + connection-info constants

**Files:**
- Create: `agent_runtime/aispm/__init__.py`
- Test: `tests/aispm/conftest.py` (new)
- Test: `tests/aispm/test_constants.py`

- [ ] **Step 1: Failing test for env-driven constants**

```python
# tests/aispm/test_constants.py
import importlib

def test_constants_populated_from_env(monkeypatch):
    monkeypatch.setenv("AGENT_ID",    "ag-001")
    monkeypatch.setenv("TENANT_ID",   "t1")
    monkeypatch.setenv("MCP_URL",     "http://spm-mcp:8500/mcp")
    monkeypatch.setenv("MCP_TOKEN",   "mcp-x")
    monkeypatch.setenv("LLM_BASE_URL","http://spm-llm-proxy:8500/v1")
    monkeypatch.setenv("LLM_API_KEY", "llm-x")

    import aispm
    importlib.reload(aispm)
    assert aispm.AGENT_ID     == "ag-001"
    assert aispm.TENANT_ID    == "t1"
    assert aispm.MCP_URL      == "http://spm-mcp:8500/mcp"
    assert aispm.MCP_TOKEN    == "mcp-x"
    assert aispm.LLM_BASE_URL == "http://spm-llm-proxy:8500/v1"
    assert aispm.LLM_API_KEY  == "llm-x"
```

- [ ] **Step 2: Implement skeleton**

```python
# agent_runtime/aispm/__init__.py
"""aispm — agent-side SDK for the AI-SPM agent runtime control plane.

Customer agents import this to talk to the four wires the platform
exposes:

    aispm.chat.subscribe() / reply() / history()  — user-facing chat (Kafka)
    aispm.mcp.call("web_fetch", ...)              — platform tools (HTTP MCP)
    aispm.llm.complete(messages=...)              — LLM proxy (OpenAI-compat)
    aispm.get_secret("MY_KEY")                    — per-agent secrets (HTTP)
    aispm.ready()                                  — lifecycle handshake
    aispm.log("step", trace=...)                  — structured lineage

Connection info is read from env vars at import time. The controller
(spm-api) injects these when it spawns the container — see Phase 1
spawn_agent_container() for the canonical list. Customers must NOT
override these.
"""
from __future__ import annotations
import os

# ─── Connection info (env-injected) ────────────────────────────────────────
AGENT_ID      = os.environ.get("AGENT_ID",      "")
TENANT_ID     = os.environ.get("TENANT_ID",     "t1")
MCP_URL       = os.environ.get("MCP_URL",       "")
MCP_TOKEN     = os.environ.get("MCP_TOKEN",     "")
LLM_BASE_URL  = os.environ.get("LLM_BASE_URL",  "")
LLM_API_KEY   = os.environ.get("LLM_API_KEY",   "")
KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "")

# spm-api base — used by secrets.get_secret() and lifecycle.ready().
# Defaults to the in-compose hostname; tests override.
CONTROLLER_URL = os.environ.get("CONTROLLER_URL", "http://spm-api:8092")

# ─── Public surface (lazy imports avoid pulling kafka/httpx until used) ─
from . import chat, mcp, llm, lifecycle, log, types  # noqa: E402, F401
from .secrets   import get_secret                    # noqa: E402, F401
from .lifecycle import ready                         # noqa: E402, F401

__all__ = [
    "AGENT_ID", "TENANT_ID",
    "MCP_URL", "MCP_TOKEN",
    "LLM_BASE_URL", "LLM_API_KEY",
    "KAFKA_BOOTSTRAP_SERVERS",
    "CONTROLLER_URL",
    "chat", "mcp", "llm", "lifecycle", "log", "types",
    "get_secret", "ready",
]
```

- [ ] **Step 3: Run, pass; commit**

```
pytest tests/aispm/test_constants.py -v
git commit -m "feat(aispm): package skeleton + env-driven connection constants"
```

---

## Task 2: aispm.types — dataclasses

Spec §8 names three dataclasses. Pin the field types so customer IDEs autocomplete.

- [ ] **Step 1: Failing tests**

```python
# tests/aispm/test_types.py
from datetime import datetime, timezone
from aispm.types import ChatMessage, HistoryEntry, Completion

def test_chat_message_round_trip():
    m = ChatMessage(id="m1", session_id="s1", user_id="u1",
                    text="hi", ts=datetime.now(timezone.utc))
    assert m.text == "hi"

def test_completion_usage_is_dict():
    c = Completion(text="hi", model="x",
                   usage={"prompt_tokens": 1, "completion_tokens": 2})
    assert c.usage["prompt_tokens"] == 1
```

- [ ] **Step 2: Implement** per spec §8.

```python
# agent_runtime/aispm/types.py
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Literal

@dataclass
class ChatMessage:
    id:          str
    session_id:  str
    user_id:     str
    text:        str
    ts:          datetime

@dataclass
class HistoryEntry:
    role: Literal["user", "agent"]
    text: str
    ts:   datetime

@dataclass
class Completion:
    text:  str
    model: str
    usage: Dict[str, int]
```

- [ ] **Step 3: commit**

```
git commit -m "feat(aispm): types — ChatMessage, HistoryEntry, Completion"
```

---

## Task 3: aispm.lifecycle — ready() + signals

Replaces Phase 1's hardcoded 5-second sleep with a real handshake. The
loader sits up an HTTP server on `localhost:8600/ready`; the controller
polls it.

- [ ] **Step 1: Failing test** — ready() must POST to controller within timeout.

```python
# tests/aispm/test_lifecycle.py
import pytest, httpx
from aispm import lifecycle

@pytest.mark.asyncio
async def test_ready_posts_to_controller(monkeypatch):
    captured = {}
    async def _fake_post(self, url, json=None, **kw):
        captured["url"] = url
        return httpx.Response(204, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    monkeypatch.setattr(lifecycle, "_AGENT_ID", "ag-001")
    monkeypatch.setattr(lifecycle, "_CONTROLLER_URL", "http://spm-api:8092")

    await lifecycle.ready()
    assert "/agents/ag-001/ready" in captured["url"]
```

- [ ] **Step 2: Implement**

```python
# agent_runtime/aispm/lifecycle.py
import asyncio, httpx, signal
from . import AGENT_ID as _AGENT_ID, CONTROLLER_URL as _CONTROLLER_URL

_READY_TIMEOUT_S = 5.0

async def ready() -> None:
    """Notify the controller this agent is initialised and ready to
    consume chat messages. Idempotent — calling multiple times is safe."""
    url = f"{_CONTROLLER_URL}/api/spm/agents/{_AGENT_ID}/ready"
    async with httpx.AsyncClient(timeout=_READY_TIMEOUT_S) as c:
        await c.post(url)

def install_signal_handlers(stop_callback) -> None:
    """SIGTERM / SIGINT → stop_callback(). Used by the loader to drain
    in-flight messages cleanly inside Docker's 10s grace window."""
    loop = asyncio.get_event_loop()
    for s in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(s, stop_callback)
```

- [ ] **Step 3: Add `POST /api/spm/agents/{id}/ready` to spm-api `agent_routes.py`** — flips `runtime_state` to `running` and updates `last_seen_at`.

- [ ] **Step 4: Modify `agent_controller.deploy_agent`** — replace `await asyncio.sleep(5)` with a 30-second poll loop that watches for the SDK's POST.

```python
# excerpt — agent_controller.py
async def _wait_for_ready(db, agent_id, *, timeout_s: int = 30):
    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        a = await _get_async(db, Agent, agent_id)
        if a and a.runtime_state == "running":
            return
        await asyncio.sleep(0.5)
    raise TimeoutError(f"agent {agent_id} did not signal ready in {timeout_s}s")
```

- [ ] **Step 5: Run, commit.**

---

## Task 4: aispm.mcp — HTTP MCP client

- [ ] **Step 1: Failing test**

```python
# tests/aispm/test_mcp.py
import pytest, httpx
from aispm import mcp

@pytest.mark.asyncio
async def test_call_passes_bearer_and_returns_payload(monkeypatch):
    captured = {}
    async def _fake_post(self, url, json=None, headers=None, **kw):
        captured["url"]     = url
        captured["headers"] = dict(headers or {})
        captured["body"]    = json
        return httpx.Response(200, json={"results":[{"title":"x"}]},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    monkeypatch.setattr(mcp, "_MCP_URL",   "http://spm-mcp:8500/mcp")
    monkeypatch.setattr(mcp, "_MCP_TOKEN", "abc")

    out = await mcp.call("web_fetch", query="hi", max_results=3)
    assert out["results"][0]["title"] == "x"
    assert captured["headers"]["Authorization"] == "Bearer abc"
    assert captured["body"]["params"]["query"]  == "hi"
```

- [ ] **Step 2: Implement** — JSON-RPC 2.0 framing per MCP spec.

```python
# agent_runtime/aispm/mcp.py
import httpx
from . import MCP_URL as _MCP_URL, MCP_TOKEN as _MCP_TOKEN

_TIMEOUT_S = 30

async def call(tool: str, **kwargs) -> dict:
    """Invoke an MCP tool by name. Bearer-authenticated. Raises on
    transport / non-2xx errors so caller code surfaces them; tool
    errors come back inside the result dict."""
    body = {"jsonrpc":"2.0","id":1,"method":"tools/call",
            "params":{"name": tool, "arguments": kwargs}}
    headers = {"Authorization": f"Bearer {_MCP_TOKEN}"}
    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as c:
        r = await c.post(_MCP_URL, json=body, headers=headers)
    r.raise_for_status()
    out = r.json()
    if "error" in out:
        raise RuntimeError(f"MCP error: {out['error']}")
    return out.get("result", {})
```

- [ ] **Step 3: Commit.**

---

## Task 5: aispm.llm — OpenAI-compat client

- [ ] **Step 1: Failing test** — covers POST + returned `Completion` shape.

```python
@pytest.mark.asyncio
async def test_complete_forwards_to_proxy(monkeypatch):
    captured = {}
    async def _fake_post(self, url, json=None, headers=None, **kw):
        captured.update({"url": url, "headers": dict(headers or {}), "body": json})
        return httpx.Response(200, json={
            "model":"llama3.1:8b",
            "choices":[{"message":{"role":"assistant","content":"yo"},
                         "finish_reason":"stop"}],
            "usage":{"prompt_tokens":10,"completion_tokens":3,"total_tokens":13},
        }, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    monkeypatch.setattr(llm, "_BASE_URL", "http://spm-llm-proxy:8500/v1")
    monkeypatch.setattr(llm, "_API_KEY",  "llm-x")

    out = await llm.complete(messages=[{"role":"user","content":"hi"}])
    assert out.text  == "yo"
    assert out.model == "llama3.1:8b"
    assert out.usage["prompt_tokens"] == 10
```

- [ ] **Step 2: Implement.**

```python
# agent_runtime/aispm/llm.py
import httpx
from .types import Completion
from . import LLM_BASE_URL as _BASE_URL, LLM_API_KEY as _API_KEY

_TIMEOUT_S = 120

async def complete(messages, *, model=None,
                    max_tokens=2048, temperature=0.7) -> Completion:
    body = {"messages": messages,
            "model": model or "llama3.1:8b",
            "max_tokens": max_tokens, "temperature": temperature}
    headers = {"Authorization": f"Bearer {_API_KEY}"}
    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as c:
        r = await c.post(f"{_BASE_URL}/chat/completions",
                          json=body, headers=headers)
    r.raise_for_status()
    data = r.json()
    text = data["choices"][0]["message"]["content"]
    return Completion(text=text, model=data["model"],
                      usage=data.get("usage", {}))
```

- [ ] **Step 3: Commit.**

---

## Task 6: aispm.chat — Kafka in/out

The biggest module. `subscribe()` is an async iterator that consumes
the agent's `chat.in` topic; `reply()` produces to `chat.out`;
`history()` calls a Phase 2 spm-api endpoint.

- [ ] **Step 1: Failing test for subscribe()** — uses an in-memory mock
  KafkaConsumer.

- [ ] **Step 2: Implement** — wraps `aiokafka.AIOKafkaConsumer` /
  `AIOKafkaProducer`. Topics resolved via the helper imported from
  `platform_shared.topics.agent_topics_for` (which already lives in
  the SDK image as part of the runtime).

```python
# agent_runtime/aispm/chat.py
import json
from datetime import datetime, timezone
from typing import AsyncIterator
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from .types import ChatMessage, HistoryEntry
from . import (
    AGENT_ID as _AGENT_ID, TENANT_ID as _TENANT_ID,
    KAFKA_BOOTSTRAP_SERVERS as _BOOTSTRAP,
)

def _topics():
    return (f"cpm.{_TENANT_ID}.agents.{_AGENT_ID}.chat.in",
            f"cpm.{_TENANT_ID}.agents.{_AGENT_ID}.chat.out")

async def subscribe() -> AsyncIterator[ChatMessage]:
    in_topic, _ = _topics()
    consumer = AIOKafkaConsumer(
        in_topic,
        bootstrap_servers=_BOOTSTRAP,
        group_id=f"agent-{_AGENT_ID}",
        enable_auto_commit=True,
        value_deserializer=lambda b: json.loads(b.decode()),
    )
    await consumer.start()
    try:
        async for msg in consumer:
            v = msg.value
            yield ChatMessage(
                id=v["id"], session_id=v["session_id"],
                user_id=v["user_id"], text=v["text"],
                ts=datetime.fromisoformat(v["ts"]),
            )
    finally:
        await consumer.stop()

_producer = None

async def reply(session_id: str, text: str) -> None:
    global _producer
    if _producer is None:
        _producer = AIOKafkaProducer(bootstrap_servers=_BOOTSTRAP,
                                      value_serializer=lambda v: json.dumps(v).encode())
        await _producer.start()
    _, out_topic = _topics()
    await _producer.send_and_wait(
        out_topic,
        {"session_id": session_id, "text": text,
         "ts": datetime.now(timezone.utc).isoformat()},
        key=session_id.encode(),
    )

# history() lives in the spm-api endpoint added in Task 7's parallel work.
```

- [ ] **Step 3: Add `GET /api/spm/agents/{id}/sessions/{sid}/messages?limit=10`** to spm-api.

- [ ] **Step 4: Tests + commit.**

---

## Task 7: aispm.secrets — get_secret() + spm-api endpoint

- [ ] **Step 1: Add `GET /api/spm/agents/{id}/secrets/{name}` route** to `agent_routes.py` — looks up `agents.config.env_vars[name]` (per-agent encrypted via `integration_credentials`). Returns `{"value": str}`.

- [ ] **Step 2: Failing test for get_secret().**

- [ ] **Step 3: Implement client.**

```python
# agent_runtime/aispm/secrets.py
import httpx
from . import (AGENT_ID as _AGENT_ID, MCP_TOKEN as _TOKEN,
               CONTROLLER_URL as _BASE)

async def get_secret(name: str) -> str:
    url = f"{_BASE}/api/spm/agents/{_AGENT_ID}/secrets/{name}"
    async with httpx.AsyncClient(timeout=5) as c:
        r = await c.get(url, headers={"Authorization": f"Bearer {_TOKEN}"})
    r.raise_for_status()
    return r.json()["value"]
```

- [ ] **Step 4: Commit.**

---

## Task 8: aispm.log — structured lineage emitter

```python
# agent_runtime/aispm/log.py
import json, sys
from . import AGENT_ID as _AGENT_ID, TENANT_ID as _TENANT_ID

def log(message: str, *, trace: str | None = None, **fields) -> None:
    """Emit one JSON line to stdout. spm-api's log shipper picks it up
    via docker logs and republishes as an AgentLog lineage event."""
    rec = {"agent_id": _AGENT_ID, "tenant_id": _TENANT_ID,
           "msg": message, "trace": trace, **fields}
    print(json.dumps(rec, default=str), file=sys.stdout, flush=True)
```

Tests cover field merging + redaction (no `MCP_TOKEN` / `LLM_API_KEY`
ever in output — assert via grep).

---

## Task 9: agent_runtime/Dockerfile — real image + loader

Replace the Phase 1 stub. The loader imports `aispm` first (so its
module-level constants populate from env), then `exec()`s
`/agent/agent.py`.

```dockerfile
FROM python:3.12-slim
WORKDIR /agent

COPY agent_runtime/aispm/    /agent/aispm/
COPY agent_runtime/loader.py /agent/loader.py

RUN pip install --no-cache-dir \
    aiokafka==0.11.* httpx==0.27.* \
    pydantic==2.* mcp==1.*

# Customer's agent.py is bind-mounted onto /agent/agent.py at runtime.
CMD ["python", "/agent/loader.py"]
```

```python
# agent_runtime/loader.py
"""Phase 2 entrypoint — imports aispm so connection constants populate
from env, then executes the customer's /agent/agent.py."""
import importlib.util, sys

import aispm  # noqa: F401  — populates module-level constants

spec = importlib.util.spec_from_file_location("agent", "/agent/agent.py")
mod  = importlib.util.module_from_spec(spec)
sys.modules["agent"] = mod
spec.loader.exec_module(mod)
```

Build it:

```
docker build -f agent_runtime/Dockerfile -t aispm-agent-runtime:latest .
```

---

## Task 10: end-to-end smoke

`tests/e2e/test_aispm_sdk_smoke.py` — uploads the spec §8 hello-world
example, deploys it, sends a chat message, asserts a reply lands on
`chat.out` within 30s. Uses the real stack via `./start.sh`.

```python
# fixture: spec §8 bare-minimum agent
HELLO = """
import aispm, asyncio

async def main():
    await aispm.ready()
    async for msg in aispm.chat.subscribe():
        ctx = await aispm.mcp.call("web_fetch", query=msg.text)
        resp = await aispm.llm.complete(messages=[
            {"role":"system","content":"Answer using the context."},
            {"role":"user","content": f"{msg.text}\\n\\nContext: {ctx}"},
        ])
        await aispm.chat.reply(msg.session_id, resp.text)

asyncio.run(main())
"""
```

Coverage:
1. `POST /api/spm/agents` with HELLO + `deploy_after=true`.
2. Wait for `runtime_state == "running"` (proves `aispm.ready()` worked).
3. Produce a fake user message to `cpm.t1.agents.{id}.chat.in`.
4. Consume `cpm.t1.agents.{id}.chat.out`, assert non-empty reply.
5. Cleanup: `DELETE /api/spm/agents/{id}`.

---

## Phase 2 Done Criteria

- [ ] `pip install -e agent_runtime/` makes `aispm` importable.
- [ ] All `tests/aispm/*.py` tests pass.
- [ ] `docker build -f agent_runtime/Dockerfile` produces an image.
- [ ] `tests/e2e/test_aispm_sdk_smoke.py` passes against the real stack.
- [ ] No regressions in any Phase 1 test.
- [ ] Operator quickstart doc updated with the SDK section.

---

## Out of scope (deferred to V1.5 / V2)

- `aispm.chat.stream()` — token-by-token streaming. Stub only; backend wiring is V1.5.
- `aispm.log` shipping — Phase 2 prints to stdout; the lineage shipper that picks it up and emits `AgentLog` events lives in Phase 4.
- Customer-defined MCP tools — registry on the agent side; Phase 1 only ships `web_fetch`.
- Per-agent secret rotation flow — manual today (PATCH the integration); automation is V2.
