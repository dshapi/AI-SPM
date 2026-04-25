"""Phase 2 SDK end-to-end smoke test.

Boots against the full docker-compose stack (``./start.sh``). Skipped
unless the stack is up. Coverage:

  1. Upload the spec § 8 hello-world agent with deploy_after=true.
  2. Wait for the row's ``runtime_state`` to flip to ``running`` —
     that proves the SDK's ``aispm.ready()`` handshake reached the
     controller and the new POST /agents/{id}/ready route handled it.
  3. Produce a synthetic user message to the agent's chat.in topic
     using a raw aiokafka client (we DON'T use the prompt-guard
     pipeline here — that's Phase 4's e2e test).
  4. Consume the agent's reply from chat.out within a generous
     timeout. Reply must be non-empty.
  5. Cleanup: DELETE the agent (stops container, deletes topics,
     drops the row).

We tolerate a longer end-to-end timeout than the unit tests because
the customer agent boots LangChain / Ollama on first message — cold
start can be 10–20s on a laptop.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import pytest
import requests

API           = "http://localhost:8092/api/spm"
TOKEN_URL     = "http://localhost:8092/api/dev-token"
KAFKA_BOOTSTRAP = "localhost:19092"  # docker-compose's external listener


def _stack_up() -> bool:
    try:
        return requests.get("http://localhost:8092/health", timeout=2
                              ).status_code == 200
    except requests.RequestException:
        return False


pytestmark = pytest.mark.skipif(
    not _stack_up(),
    reason="docker-compose stack not running on :8092",
)


# ─── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def admin_token() -> str:
    return requests.get(TOKEN_URL, timeout=5).json()["token"]


@pytest.fixture
def headers(admin_token: str) -> dict:
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def hello_agent_path() -> pathlib.Path:
    return (pathlib.Path(__file__).parent.parent.parent
            / "agent_runtime" / "examples" / "hello_world.py")


# ─── Helpers ───────────────────────────────────────────────────────────────

def _upload_and_deploy(headers: dict, code_path: pathlib.Path) -> str:
    """Upload the agent with deploy_after=true; return its id."""
    name = f"sdk-smoke-{uuid.uuid4().hex[:6]}"
    with code_path.open("rb") as f:
        r = requests.post(
            f"{API}/agents",
            headers=headers,
            data={
                "name": name, "version": "1.0",
                "agent_type": "custom", "owner": "sdk-smoke",
                "deploy_after": "true",
            },
            files={"code": ("agent.py", f, "text/x-python")},
            timeout=60,
        )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _wait_for_state(headers, agent_id, target, *, timeout_s=45):
    started = time.monotonic()
    last = None
    while time.monotonic() - started < timeout_s:
        r = requests.get(f"{API}/agents/{agent_id}", headers=headers, timeout=5)
        if r.status_code == 200:
            last = r.json().get("runtime_state")
            if last == target:
                return
        time.sleep(0.5)
    raise AssertionError(
        f"agent {agent_id} did not reach state={target!r} in "
        f"{timeout_s}s (last={last!r})"
    )


async def _send_user_message(tenant_id: str, agent_id: str,
                                session_id: str, text: str) -> None:
    """Push one fake user message onto chat.in."""
    from aiokafka import AIOKafkaProducer
    p = AIOKafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        value_serializer=lambda v: json.dumps(v).encode(),
    )
    await p.start()
    try:
        await p.send_and_wait(
            f"cpm.{tenant_id}.agents.{agent_id}.chat.in",
            value={
                "id":         str(uuid.uuid4()),
                "session_id": session_id,
                "user_id":    "smoke-test",
                "text":       text,
                "ts":         datetime.now(timezone.utc).isoformat(),
            },
            key=session_id.encode(),
        )
    finally:
        await p.stop()


async def _wait_for_reply(tenant_id: str, agent_id: str,
                            session_id: str, *, timeout_s=30) -> Optional[dict]:
    from aiokafka import AIOKafkaConsumer
    c = AIOKafkaConsumer(
        f"cpm.{tenant_id}.agents.{agent_id}.chat.out",
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=f"smoke-{uuid.uuid4().hex[:6]}",
        auto_offset_reset="earliest",
        value_deserializer=lambda b: json.loads(b.decode()),
    )
    await c.start()
    try:
        deadline = asyncio.get_event_loop().time() + timeout_s
        while asyncio.get_event_loop().time() < deadline:
            r = await asyncio.wait_for(c.getone(), timeout=2)
            if (r.value or {}).get("session_id") == session_id:
                return r.value
    except asyncio.TimeoutError:
        return None
    finally:
        await c.stop()
    return None


# ─── The test ──────────────────────────────────────────────────────────────

class TestHelloWorldSDKSmoke:
    def test_upload_deploy_chat_cleanup(self, headers, hello_agent_path):
        agent_id = _upload_and_deploy(headers, hello_agent_path)
        try:
            # 2. SDK's ready() handshake fires → state goes running.
            _wait_for_state(headers, agent_id, "running", timeout_s=45)

            # 3 + 4. Produce a user message; expect a reply.
            session_id = str(uuid.uuid4())
            asyncio.run(_send_user_message("t1", agent_id,
                                            session_id, "hello"))
            reply = asyncio.run(_wait_for_reply("t1", agent_id,
                                                  session_id, timeout_s=60))
            assert reply is not None, "no reply from agent on chat.out"
            assert reply.get("text"), "reply was empty"
        finally:
            # 5. Always cleanup so re-runs don't leak agents.
            requests.delete(f"{API}/agents/{agent_id}",
                             headers=headers, timeout=20)
