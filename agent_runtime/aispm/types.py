"""Public dataclasses for the aispm SDK — spec § 8.

The full type signatures matter because:
  * V1 quickstart docs reference them
  * customer IDEs need them for autocomplete
  * downstream code in customer agents pattern-matches on the fields

All three are plain dataclasses (not Pydantic) so the SDK has zero
runtime cost beyond what stdlib provides. Validation happens at the
wire layer (chat.py / mcp.py / llm.py) where the upstream payload is
parsed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Literal


@dataclass
class ChatMessage:
    """A user → agent message pulled from the chat.in topic.

    ``id`` is the message UUID, ``session_id`` is the conversation
    partition key (so per-session ordering is preserved across
    consumer-group rebalances).

    ``trace_id`` lets the customer agent stitch its reply back into
    the platform's audit/lineage record. Pass it to
    ``aispm.chat.stream(session_id, trace_id=msg.trace_id)`` so the
    delta records on ``chat.out`` carry the same trace as the
    incoming user message. Defaults to "" for replays / fixtures
    that don't include a trace; in that case the writer falls back
    to ``session_id`` as the trace identifier.
    """
    id:         str
    session_id: str
    user_id:    str
    text:       str
    ts:         datetime
    trace_id:   str = ""


@dataclass
class HistoryEntry:
    """One turn from a chat session's persisted history.

    Returned by ``aispm.chat.history(session_id, limit=N)``. Distinct
    from ``ChatMessage`` because the role here is meaningful (user vs
    agent reply) where on the in-topic everything is user-originated.
    """
    role: Literal["user", "agent"]
    text: str
    ts:   datetime


@dataclass
class Completion:
    """The result of an LLM call via the spm-llm-proxy.

    ``usage`` is a dict (not its own dataclass) because providers
    return varying token-accounting shapes — Anthropic returns
    ``input_tokens`` / ``output_tokens``, OpenAI returns
    ``prompt_tokens`` / ``completion_tokens``. We pass it through
    unmodified so callers can inspect what their upstream returned.
    """
    text:  str
    model: str
    usage: Dict[str, Any]
