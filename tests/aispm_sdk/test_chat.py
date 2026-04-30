"""aispm.chat — Kafka subscribe/reply and the history() HTTP path.

The Kafka surface is mocked; we don't spin up a broker. The HTTP path
(history) hits a fake controller endpoint via httpx mock.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from aispm import chat
from aispm.types import ChatMessage, HistoryEntry


# ─── Topic naming ──────────────────────────────────────────────────────────

def test_topic_in_format(monkeypatch):
    monkeypatch.setattr(chat, "_TENANT_ID", "t1")
    monkeypatch.setattr(chat, "_AGENT_ID",  "ag-001")
    assert chat._topic_in()  == "cpm.t1.agents.ag-001.chat.in"
    assert chat._topic_out() == "cpm.t1.agents.ag-001.chat.out"


# ─── Wire payload → ChatMessage ────────────────────────────────────────────

class TestPayloadParser:
    def test_full_payload(self):
        ts = datetime.now(timezone.utc)
        m = chat._to_chat_message({
            "id": "m1", "session_id": "s1", "user_id": "u1",
            "text": "hi", "ts": ts.isoformat(),
        })
        assert isinstance(m, ChatMessage)
        assert m.id == "m1"
        assert m.text == "hi"
        # ts round-trips via fromisoformat
        assert m.ts.tzinfo is not None

    def test_missing_fields_defaults(self):
        m = chat._to_chat_message({})
        assert m.id == "" and m.session_id == "" and m.user_id == ""
        assert m.text == ""

    def test_bad_ts_falls_back_to_now(self):
        m = chat._to_chat_message({"ts": "not a date"})
        assert isinstance(m.ts, datetime)


# ─── ChatMessage — trace_id round-trip ─────────────────────────────────────

class TestPayloadParserTraceId:
    def test_trace_id_extracted_from_wire(self):
        m = chat._to_chat_message({
            "id": "m1", "session_id": "s1", "user_id": "u1",
            "text": "hi", "trace_id": "trace-abc-123",
        })
        assert m.trace_id == "trace-abc-123"

    def test_trace_id_defaults_to_empty(self):
        # Replays / fixtures that don't include trace_id should not
        # crash the parser. Default empty string lets the writer
        # fall back to session_id.
        m = chat._to_chat_message({"session_id": "s1"})
        assert m.trace_id == ""


# ─── reply() and stream() — wire shape on chat.out ─────────────────────────
#
# Both call paths converge on the same protocol:
#   delta records (one per chunk) followed by a `done` marker.
# Tests below capture every Kafka record and assert the shape.


def _mock_producer(monkeypatch):
    """Install a producer mock that captures every send + send_and_wait
    call. Returns the captured-records list."""
    sent: list[dict] = []

    producer = MagicMock()

    async def _send(topic, value=None, key=None):
        sent.append({"topic": topic, "value": value, "key": key,
                     "method": "send"})
    async def _send_and_wait(topic, value=None, key=None):
        sent.append({"topic": topic, "value": value, "key": key,
                     "method": "send_and_wait"})

    producer.send          = _send
    producer.send_and_wait = _send_and_wait

    async def _get(): return producer
    monkeypatch.setattr(chat, "_get_producer", _get)
    monkeypatch.setattr(chat, "_BOOTSTRAP", "kafka:9092")
    monkeypatch.setattr(chat, "_AGENT_ID",  "ag-001")
    monkeypatch.setattr(chat, "_TENANT_ID", "t1")
    return sent


class TestReply:
    @pytest.mark.asyncio
    async def test_reply_emits_delta_then_done(self, monkeypatch):
        """reply(text) wraps stream() — emits one delta + the done marker.

        Wire protocol on chat.out:
          1. {"type": "delta", "text": "hi user", "index": 0, ...}    via send
          2. {"type": "done",  "full_text": "hi user", ...}           via send_and_wait
        """
        sent = _mock_producer(monkeypatch)

        await chat.reply("session-42", "hi user")

        # All records on chat.out, partition-keyed by session.
        for r in sent:
            assert r["topic"] == "cpm.t1.agents.ag-001.chat.out"
            assert r["key"]   == b"session-42"

        # Two records total: one delta (send), one done (send_and_wait).
        assert len(sent) == 2

        delta, done = sent
        assert delta["method"]         == "send"
        assert delta["value"]["type"]  == "delta"
        assert delta["value"]["text"]  == "hi user"
        assert delta["value"]["index"] == 0
        assert delta["value"]["session_id"] == "session-42"

        assert done["method"]                 == "send_and_wait"
        assert done["value"]["type"]          == "done"
        assert done["value"]["full_text"]     == "hi user"
        assert done["value"]["finish_reason"] == "stop"
        assert done["value"]["session_id"]    == "session-42"

    @pytest.mark.asyncio
    async def test_reply_with_empty_text_only_emits_done(self, monkeypatch):
        """An empty reply should still close the SSE stream. _StreamWriter
        skips the delta but always emits the done marker on context exit."""
        sent = _mock_producer(monkeypatch)

        await chat.reply("session-42", "")

        assert len(sent) == 1
        assert sent[0]["value"]["type"]      == "done"
        assert sent[0]["value"]["full_text"] == ""

    @pytest.mark.asyncio
    async def test_reply_propagates_trace_id(self, monkeypatch):
        sent = _mock_producer(monkeypatch)

        await chat.reply("session-42", "hi", trace_id="trace-xyz")

        for r in sent:
            assert r["value"]["trace_id"] == "trace-xyz"


class TestStream:
    @pytest.mark.asyncio
    async def test_stream_emits_one_delta_per_write(self, monkeypatch):
        """The streaming writer is the canonical path for token-by-token
        agent output. Each write() produces one delta; the done marker
        fires automatically on context exit with the concatenated text."""
        sent = _mock_producer(monkeypatch)

        async with chat.stream("session-42", trace_id="t-1") as out:
            await out.write("Hello")
            await out.write(", ")
            await out.write("world")

        # 3 deltas + 1 done
        assert len(sent) == 4

        deltas = [r for r in sent if r["value"]["type"] == "delta"]
        done   = [r for r in sent if r["value"]["type"] == "done"][0]

        # Deltas in order, indices increment, all use send (no wait).
        assert [d["value"]["text"]  for d in deltas] == ["Hello", ", ", "world"]
        assert [d["value"]["index"] for d in deltas] == [0, 1, 2]
        assert all(d["method"] == "send" for d in deltas)

        # Done is the canonical record — flushed via send_and_wait, carries
        # the concatenated text and finish_reason.
        assert done["method"]                 == "send_and_wait"
        assert done["value"]["full_text"]     == "Hello, world"
        assert done["value"]["finish_reason"] == "stop"
        assert done["value"]["trace_id"]      == "t-1"

    @pytest.mark.asyncio
    async def test_stream_skips_empty_chunks(self, monkeypatch):
        """Some LLM proxies emit keepalive frames with delta.content="".
        The writer should silently drop those — no zero-length delta on
        the wire, otherwise the UI gets noisy."""
        sent = _mock_producer(monkeypatch)

        async with chat.stream("s1") as out:
            await out.write("ok")
            await out.write("")               # dropped
            await out.write("")               # dropped

        deltas = [r for r in sent if r["value"]["type"] == "delta"]
        assert len(deltas) == 1
        assert deltas[0]["value"]["text"] == "ok"

    @pytest.mark.asyncio
    async def test_stream_emits_done_on_exception(self, monkeypatch):
        """Mid-stream exceptions must NOT leave the SSE stream hanging.
        The writer's __aexit__ emits a done marker with finish_reason=error
        regardless of how the context exits."""
        sent = _mock_producer(monkeypatch)

        with pytest.raises(RuntimeError, match="boom"):
            async with chat.stream("s1") as out:
                await out.write("partial")
                raise RuntimeError("boom")

        # delta + done should still be there
        assert len(sent) == 2
        done = sent[-1]["value"]
        assert done["type"]          == "done"
        assert done["full_text"]     == "partial"
        assert done["finish_reason"] == "error"

    @pytest.mark.asyncio
    async def test_stream_falls_back_to_session_id_for_trace(
        self, monkeypatch
    ):
        """Customer agents that forget to plumb trace_id should still get
        a usable correlation id — falls back to session_id."""
        sent = _mock_producer(monkeypatch)

        async with chat.stream("session-only") as out:
            await out.write("x")

        for r in sent:
            assert r["value"]["trace_id"] == "session-only"


# ─── history() — HTTP to controller ────────────────────────────────────────

class TestHistory:
    @pytest.mark.asyncio
    async def test_history_returns_entries(self, monkeypatch):
        ts = datetime.now(timezone.utc).isoformat()
        async def _fake_get(self, url, params=None, headers=None, **kw):
            return httpx.Response(200, json=[
                {"role": "user",  "text": "hi",  "ts": ts},
                {"role": "agent", "text": "yo",  "ts": ts},
            ], request=httpx.Request("GET", url))
        monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
        monkeypatch.setattr(chat, "_AGENT_ID",       "ag-001")
        monkeypatch.setattr(chat, "_MCP_TOKEN",      "tok")
        monkeypatch.setattr(chat, "_CONTROLLER_URL", "http://spm-api:8092")

        out = await chat.history("session-1", limit=2)
        assert len(out) == 2
        assert all(isinstance(h, HistoryEntry) for h in out)
        assert out[0].role == "user"
        assert out[1].role == "agent"
