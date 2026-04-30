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
        # Optional on the wire — spm-api emits it but tests/replays may
        # not. Defaults to "" so the writer falls back to session_id.
        trace_id=   str(v.get("trace_id", "")),
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


# ─── reply() / stream() — emit one agent reply to chat.out ─────────────────
#
# Wire protocol on cpm.{tenant}.agents.{agent_id}.chat.out:
#
#   {"type": "delta", "session_id": "...", "trace_id": "...",
#    "text":  "<chunk>", "index": N}
#   …
#   {"type": "done",  "session_id": "...", "trace_id": "...",
#    "full_text": "<concatenated reply>",
#    "finish_reason": "stop" | "error"}
#
# spm-api consumes both and forwards each `delta` as one SSE token to
# the UI; on `done` it persists the assistant turn in agent_chat_messages
# and closes the SSE stream. There is no fall-back to a single-record
# legacy shape — the SDK and the consumer ship together.


class _StreamWriter:
    """Async context manager that emits delta records as the agent
    produces them and a final ``done`` marker on exit.

    Usage
    ─────
    The canonical streaming pattern is::

        async with aispm.chat.stream(msg.session_id,
                                     trace_id=msg.trace_id) as s:
            async for chunk in aispm.llm.stream(messages):
                await s.write(chunk)

    Single-shot replies (no LLM streaming, just produce one full reply)
    use the ``reply()`` helper below, which wraps this writer.

    Why a context manager
    ─────────────────────
    The ``done`` marker is mandatory — without it spm-api's SSE
    consumer can't tell when the stream is finished and the chat
    request hangs in the UI. By emitting the ``done`` from
    ``__aexit__`` we guarantee delivery on every code path (normal
    return, exception, cancellation), with ``finish_reason`` set
    accordingly so the UI can render an error state if the agent
    crashed mid-stream.
    """

    __slots__ = (
        "_session_id", "_trace_id", "_buf", "_idx", "_producer",
    )

    def __init__(self, session_id: str, trace_id: str) -> None:
        self._session_id = session_id
        # Fall back to session_id when the customer didn't propagate
        # the trace from the inbound ChatMessage. Better than nothing
        # for downstream lineage; the dedicated trace_id is preferred.
        self._trace_id   = trace_id or session_id
        self._buf:        List[str] = []
        self._idx        = 0
        self._producer   = None  # set in __aenter__

    async def __aenter__(self) -> "_StreamWriter":
        self._producer = await _get_producer()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        # Always emit the `done` marker, even on exception, so the SSE
        # consumer in spm-api closes the stream and the UI doesn't
        # spin forever. The send_and_wait() also flushes any pending
        # delta sends queued via send() during write() calls.
        full_text = "".join(self._buf)
        finish    = "stop" if exc is None else "error"
        try:
            await self._producer.send_and_wait(
                _topic_out(),
                value={
                    "type":          "done",
                    "session_id":    self._session_id,
                    "trace_id":      self._trace_id,
                    "full_text":     full_text,
                    "finish_reason": finish,
                    "ts":            datetime.now(timezone.utc).isoformat(),
                },
                key=self._session_id.encode(),
            )
        except Exception as send_exc:                            # noqa: BLE001
            log.warning(
                "aispm.chat: failed to emit done marker session=%s err=%s",
                self._session_id, send_exc,
            )
        # Don't suppress the original exception — let it propagate so
        # the agent's main loop sees a real error.
        return False

    async def write(self, chunk: str) -> None:
        """Emit one delta. Empty strings are silently dropped (some LLM
        proxies emit keepalive frames with no content).

        Uses ``producer.send`` (not ``send_and_wait``) so each delta
        doesn't pay a round-trip — aiokafka batches under the hood and
        the trailing ``send_and_wait`` in ``__aexit__`` flushes
        everything in one go.
        """
        if not chunk:
            return
        await self._producer.send(
            _topic_out(),
            value={
                "type":       "delta",
                "session_id": self._session_id,
                "trace_id":   self._trace_id,
                "text":       chunk,
                "index":      self._idx,
                "ts":         datetime.now(timezone.utc).isoformat(),
            },
            key=self._session_id.encode(),
        )
        self._buf.append(chunk)
        self._idx += 1


def stream(session_id: str, *, trace_id: str = "") -> _StreamWriter:
    """Open a streaming reply context for the given session.

    Returns a ``_StreamWriter`` you can use with ``async with`` —
    each ``await s.write(chunk)`` produces one ``delta`` record, and
    the ``done`` marker is emitted automatically when the context
    exits. ``trace_id`` plumbs the platform's correlation id through
    so the audit/lineage layers stitch the conversation together;
    falls back to ``session_id`` if not provided.
    """
    if not _BOOTSTRAP or not _AGENT_ID:
        raise RuntimeError(
            "aispm.chat.stream: KAFKA_BOOTSTRAP_SERVERS / AGENT_ID "
            "not set (agent was not spawned by the controller?)"
        )
    return _StreamWriter(session_id, trace_id=trace_id)


async def reply(
    session_id: str,
    text:       str,
    *,
    trace_id:   str = "",
) -> None:
    """Send one complete agent reply to the given session.

    Convenience wrapper around ``stream()`` for agents that don't
    stream from the LLM. Emits the entire ``text`` as a single delta
    followed by the mandatory ``done`` marker, so the wire protocol
    on chat.out is identical regardless of whether the agent
    streamed or buffered.

    Partition key is ``session_id`` so every record for a
    conversation lands on the same partition — preserving order.
    """
    async with stream(session_id, trace_id=trace_id) as s:
        if text:
            await s.write(text)


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
