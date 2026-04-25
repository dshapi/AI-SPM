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


# ─── reply() — calls producer.send_and_wait with right payload ─────────────

class TestReply:
    @pytest.mark.asyncio
    async def test_reply_partition_keyed_by_session(self, monkeypatch):
        captured = {}

        producer = MagicMock()
        async def _send(topic, value=None, key=None):
            captured["topic"] = topic
            captured["value"] = value
            captured["key"]   = key
        producer.send_and_wait = _send

        async def _get(): return producer
        monkeypatch.setattr(chat, "_get_producer", _get)
        monkeypatch.setattr(chat, "_BOOTSTRAP", "kafka:9092")
        monkeypatch.setattr(chat, "_AGENT_ID",  "ag-001")
        monkeypatch.setattr(chat, "_TENANT_ID", "t1")

        await chat.reply("session-42", "hi user")

        assert captured["topic"] == "cpm.t1.agents.ag-001.chat.out"
        assert captured["value"]["text"]       == "hi user"
        assert captured["value"]["session_id"] == "session-42"
        assert captured["key"]                 == b"session-42"


# ─── stream() — V1.5 stub raises on write ──────────────────────────────────

class TestStreamStub:
    @pytest.mark.asyncio
    async def test_stream_writer_raises_not_implemented(self):
        async with chat.stream("s1") as out:
            with pytest.raises(NotImplementedError, match="V1.5"):
                await out.write("token")


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
