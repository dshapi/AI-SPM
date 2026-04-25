"""ChatMessage / HistoryEntry / Completion dataclasses."""
from __future__ import annotations

from datetime import datetime, timezone

from aispm.types import ChatMessage, Completion, HistoryEntry


def test_chat_message_construct():
    m = ChatMessage(
        id="m1", session_id="s1", user_id="u1",
        text="hello", ts=datetime.now(timezone.utc),
    )
    assert m.text == "hello"
    assert m.session_id == "s1"


def test_history_entry_role_literal():
    h = HistoryEntry(role="agent", text="reply", ts=datetime.now(timezone.utc))
    assert h.role == "agent"
    assert h.text == "reply"


def test_completion_carries_usage_dict():
    c = Completion(text="hi", model="m",
                   usage={"prompt_tokens": 1, "completion_tokens": 2})
    assert c.text == "hi"
    assert c.usage["prompt_tokens"] == 1
    assert c.usage["completion_tokens"] == 2


def test_completion_usage_can_be_empty():
    c = Completion(text="", model="m", usage={})
    assert c.usage == {}
