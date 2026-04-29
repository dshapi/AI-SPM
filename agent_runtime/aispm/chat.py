"""Kafka-backed chat I/O for customer agents.

Three public surfaces, all per spec § 8:

  * ``async for msg in aispm.chat.subscribe(): ...``  — async iterator
    over the agent's per-tenant ``chat.in`` topic. One ``ChatMessage``
    per user message, partition-keyed by ``session_id`` so per-session
    ordering is preserved across consumer-group rebalances.
  * ``await aispm.chat.reply(session_id, text)``      — produces one
    full agent reply to ``chat.out``. Phase 1.5 will add token-by-token
    streaming via ``aispm.chat.stream(session_id)``.
  * ``await aispm.chat.history(session_id, limit=10)``— reads the last
    *limit* turns of a session from spm-api (NOT from Kafka — that
    would force a topic seek; the persisted-history path lives in
    Postgres via the ``agent_chat_messages`` table).

All three rely on connection info from ``aispm/__init__.py`` populated
by the controller at container start. The Kafka clients (``aiokafka``)
are constructed lazily on first use so importing ``aispm.chat`` is
free.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from . import (
    AGENT_ID                as _AGENT_ID,
    CONTROLLER_URL          as _CONTROLLER_URL,
    KAFKA_BOOTSTRAP_SERVERS as _BOOTSTRAP,
    MCP_TOKEN               as _MCP_TOKEN,
    TENANT_ID               as _TENANT_ID,
)
from .types import ChatMessage, HistoryEntry

log = logging.getLogger(__name__)


def _raise_for_status_with_detail(r: httpx.Response) -> None:
    """Like ``r.raise_for_status()`` but appends the response body's
    ``detail`` so non-2xx responses from spm-api's chat-history endpoint
    surface a useful error. See the matching helper in ``aispm/llm.py``
    for the rationale.
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


def _topic_in() -> str:
    return f"cpm.{_TENANT_ID}.agents.{_AGENT_ID}.chat.in"


def _topic_out() -> str:
    return f"cpm.{_TENANT_ID}.agents.{_AGENT_ID}.chat.out"


# ─── subscribe() — async iterator over chat.in ─────────────────────────────

async def subscribe() -> AsyncIterator[ChatMessage]:
    """Yield one ``ChatMessage`` per user message arriving on the
    agent's ``chat.in`` topic.

    Backed by ``aiokafka.AIOKafkaConsumer`` with a per-agent
    ``group_id`` so multi-replica Phase 2.5 deployments can split the
    workload by partition. V1 runs one container per agent, so the
    group_id is just bookkeeping today.

    Important offset/race notes
    ───────────────────────────
    * ``auto_offset_reset='earliest'`` — for a fresh consumer group
      (every new agent's first deploy), aiokafka's default ``"latest"``
      causes any messages sent between ``aispm.ready()`` flipping
      ``runtime_state`` to ``running`` and the consumer fully
      registering with the broker to be silently dropped. ``earliest``
      makes the first poll see those messages too. After the first
      commit the value is moot — the group has a stored offset.

    * ``await consumer.start()`` blocks until the broker has assigned
      the agent its partition(s); only then can a published message
      reach the agent. Customer ``main()`` therefore needs to call
      ``ready()`` *after* the first ``async for`` iteration begins —
      see the example agents in ``Example agents/``.

    The consumer auto-commits offsets — at-least-once delivery is the
    contract; customer agents must be idempotent on retries.
    """
    from aiokafka import AIOKafkaConsumer  # type: ignore

    if not _BOOTSTRAP or not _AGENT_ID:
        raise RuntimeError(
            "aispm.chat.subscribe: KAFKA_BOOTSTRAP_SERVERS / AGENT_ID "
            "not set (agent was not spawned by the controller?)"
        )

    consumer = AIOKafkaConsumer(
        _topic_in(),
        bootstrap_servers=_BOOTSTRAP,
        group_id=f"agent-{_AGENT_ID}",
        enable_auto_commit=True,
        # See docstring — fresh deploys would otherwise silently drop
        # the first message a user sends right after the agent comes up.
        auto_offset_reset="earliest",
        value_deserializer=lambda b: json.loads(b.decode()),
    )
    await consumer.start()
    try:
        async for kafka_msg in consumer:
            v = kafka_msg.value or {}
            yield _to_chat_message(v)
    finally:
        await consumer.stop()


def _to_chat_message(v: Dict[str, Any]) -> ChatMessage:
    """Parse a wire payload into the public dataclass.

    Tolerant of missing fields — the platform's pipeline injects all
    of these but tests / replays may not, so we default sensibly
    rather than crashing the agent's loop on malformed input.
    """
    ts_raw = v.get("ts")
    if isinstance(ts_raw, str):
        try:
            ts = datetime.fromisoformat(ts_raw)
        except ValueError:
            ts = datetime.now(timezone.utc)
    elif isinstance(ts_raw, datetime):
        ts = ts_raw
    else:
        ts = datetime.now(timezone.utc)

    return ChatMessage(
        id=         str(v.get("id", "")),
        session_id= str(v.get("session_id", "")),
        user_id=    str(v.get("user_id", "")),
        text=       str(v.get("text", "")),
        ts=         ts,
    )


# ─── reply() — produce one full reply to chat.out ──────────────────────────

# A single producer is reused across reply() calls — Kafka producers
# are expensive to create. ``_producer_lock`` guards init under high
# concurrency so we don't double-construct.

_producer = None
_producer_lock = asyncio.Lock()


async def _get_producer():
    global _producer
    if _producer is not None:
        return _producer
    async with _producer_lock:
        if _producer is not None:                # double-check under lock
            return _producer
        from aiokafka import AIOKafkaProducer    # type: ignore
        p = AIOKafkaProducer(
            bootstrap_servers=_BOOTSTRAP,
            value_serializer=lambda v: json.dumps(v).encode(),
        )
        await p.start()
        _producer = p
        return _producer


async def reply(session_id: str, text: str) -> None:
    """Send one complete agent reply to the given session.

    Per spec § 8 V1 only supports full-message replies; ``stream()``
    arrives in V1.5 once the backend wires per-token SSE through.

    Partition key is ``session_id`` so all messages for one
    conversation land on the same partition — preserving order.
    """
    if not _BOOTSTRAP or not _AGENT_ID:
        raise RuntimeError(
            "aispm.chat.reply: KAFKA_BOOTSTRAP_SERVERS / AGENT_ID "
            "not set (agent was not spawned by the controller?)"
        )

    producer = await _get_producer()
    payload = {
        "session_id": session_id,
        "text":       text,
        "ts":         datetime.now(timezone.utc).isoformat(),
    }
    await producer.send_and_wait(
        _topic_out(),
        value=payload,
        key=session_id.encode(),
    )


# ─── stream() — V1.5 placeholder ───────────────────────────────────────────

class _StreamWriterStub:
    """Returned by ``stream()`` in V1; raises on first ``write()`` so
    customers using the SDK contract before V1.5 lands fail loudly
    instead of silently dropping tokens."""

    async def write(self, _chunk: str) -> None:
        raise NotImplementedError(
            "aispm.chat.stream() is V1.5 — the backend SSE wiring "
            "isn't ready yet. Use aispm.chat.reply() for now."
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def stream(session_id: str) -> "_StreamWriterStub":
    """Stub for spec § 8 token-by-token streaming. Surface kept stable
    so customer code doesn't break when V1.5 lands."""
    return _StreamWriterStub()


# ─── history() — last N turns of a session ─────────────────────────────────

async def history(session_id: str, limit: int = 10) -> List[HistoryEntry]:
    """Fetch the last *limit* persisted messages for a session.

    Reads from spm-api's ``GET /api/spm/agents/{id}/sessions/{sid}/messages``
    endpoint (added in Phase 2 Task 6). Authenticated with the agent's
    ``MCP_TOKEN`` — the controller treats the bearer as proof-of-agent
    and scopes the query to that agent's own sessions.
    """
    if not _AGENT_ID:
        raise RuntimeError("aispm.chat.history: AGENT_ID env var not set")

    # No ``/api/spm`` — direct call to spm-api; that prefix is only
    # added by the front-end proxy.
    url = (f"{_CONTROLLER_URL}/agents/{_AGENT_ID}"
           f"/sessions/{session_id}/messages")
    headers = {"Authorization": f"Bearer {_MCP_TOKEN}"}
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(url, params={"limit": limit}, headers=headers)
    _raise_for_status_with_detail(r)

    rows = r.json()
    out: List[HistoryEntry] = []
    for row in rows:
        ts_raw = row.get("ts")
        ts = (datetime.fromisoformat(ts_raw)
              if isinstance(ts_raw, str) else datetime.now(timezone.utc))
        out.append(HistoryEntry(
            role=row.get("role", "user"),
            text=row.get("text", ""),
            ts=ts,
        ))
    return out
