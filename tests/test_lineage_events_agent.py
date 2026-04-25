"""Tests for the agent-runtime-control-plane lineage event dataclasses."""
from datetime import datetime, timezone

from platform_shared.lineage_events import (
    AgentChatMessageEvent,
    AgentDeployedEvent,
    AgentLLMCallEvent,
    AgentStartedEvent,
    AgentStoppedEvent,
    AgentToolCallEvent,
)


def _is_iso8601_utc(s: str) -> bool:
    """Best-effort ISO-8601 parse so we don't pin to a specific dateutil
    implementation."""
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return False
    return dt.tzinfo is not None


# ─── AgentDeployed ─────────────────────────────────────────────────────────

def test_agent_deployed_has_required_fields():
    evt = AgentDeployedEvent(
        agent_id="ag-001", tenant_id="t1",
        version="1.0", actor="dany",
    )
    payload = evt.to_dict()
    assert payload["event_type"] == "AgentDeployed"
    assert payload["agent_id"]   == "ag-001"
    assert payload["tenant_id"]  == "t1"
    assert payload["version"]    == "1.0"
    assert payload["actor"]      == "dany"
    assert "ts" in payload
    assert _is_iso8601_utc(payload["ts"])


def test_agent_deployed_ts_defaults_to_now_utc():
    before = datetime.now(timezone.utc)
    evt    = AgentDeployedEvent(agent_id="x", tenant_id="t1",
                                 version="1", actor="a")
    after  = datetime.now(timezone.utc)
    assert before <= evt.ts <= after


# ─── AgentStarted / AgentStopped ───────────────────────────────────────────

def test_agent_started_payload():
    p = AgentStartedEvent(agent_id="x", tenant_id="t1", actor="a").to_dict()
    assert p["event_type"] == "AgentStarted"
    assert {"agent_id", "tenant_id", "actor", "ts"} <= set(p)


def test_agent_stopped_payload_includes_reason():
    p = AgentStoppedEvent(agent_id="x", tenant_id="t1",
                           reason="user_stop", actor="a").to_dict()
    assert p["event_type"] == "AgentStopped"
    assert p["reason"]     == "user_stop"


# ─── AgentChatMessage ──────────────────────────────────────────────────────

def test_agent_chat_message_payload():
    p = AgentChatMessageEvent(
        agent_id="x", tenant_id="t1", session_id="s1",
        user_id="dany", role="user", text="hello",
        trace_id="trc-1",
    ).to_dict()
    assert p["event_type"] == "AgentChatMessage"
    assert p["session_id"] == "s1"
    assert p["role"]       == "user"
    assert p["text"]       == "hello"
    assert p["trace_id"]   == "trc-1"


# ─── AgentToolCall ─────────────────────────────────────────────────────────

def test_agent_tool_call_payload_preserves_args():
    args = {"query": "what is mcp", "max_results": 5}
    p = AgentToolCallEvent(
        agent_id="x", tenant_id="t1", tool="web_fetch",
        args=args, ok=True, duration_ms=42, trace_id="trc-2",
    ).to_dict()
    assert p["event_type"]  == "AgentToolCall"
    assert p["tool"]        == "web_fetch"
    assert p["args"]        == args
    assert p["ok"]          is True
    assert p["duration_ms"] == 42


# ─── AgentLLMCall ──────────────────────────────────────────────────────────

def test_agent_llm_call_payload():
    p = AgentLLMCallEvent(
        agent_id="x", tenant_id="t1", model="llama3.1:8b",
        prompt_tokens=120, completion_tokens=60, trace_id="trc-3",
    ).to_dict()
    assert p["event_type"]        == "AgentLLMCall"
    assert p["model"]             == "llama3.1:8b"
    assert p["prompt_tokens"]     == 120
    assert p["completion_tokens"] == 60
    assert p["trace_id"]          == "trc-3"


# ─── Cross-cutting invariants ──────────────────────────────────────────────

def test_all_event_types_emit_distinct_event_type_strings():
    types = {
        AgentDeployedEvent(agent_id="x", tenant_id="t", version="1", actor="a").to_dict()["event_type"],
        AgentStartedEvent(agent_id="x",  tenant_id="t", actor="a").to_dict()["event_type"],
        AgentStoppedEvent(agent_id="x",  tenant_id="t", reason="r", actor="a").to_dict()["event_type"],
        AgentChatMessageEvent(agent_id="x", tenant_id="t", session_id="s",
                               user_id="u", role="user", text="t",
                               trace_id="tr").to_dict()["event_type"],
        AgentToolCallEvent(agent_id="x", tenant_id="t", tool="w",
                            args={}, ok=True, duration_ms=1,
                            trace_id="tr").to_dict()["event_type"],
        AgentLLMCallEvent(agent_id="x", tenant_id="t", model="m",
                           prompt_tokens=0, completion_tokens=0,
                           trace_id="tr").to_dict()["event_type"],
    }
    assert types == {
        "AgentDeployed", "AgentStarted", "AgentStopped",
        "AgentChatMessage", "AgentToolCall", "AgentLLMCall",
    }


def test_all_event_types_emit_iso8601_ts():
    evts = [
        AgentDeployedEvent(agent_id="x", tenant_id="t", version="1", actor="a"),
        AgentStartedEvent(agent_id="x",  tenant_id="t", actor="a"),
        AgentStoppedEvent(agent_id="x",  tenant_id="t", reason="r", actor="a"),
        AgentChatMessageEvent(agent_id="x", tenant_id="t", session_id="s",
                               user_id="u", role="user", text="t",
                               trace_id="tr"),
        AgentToolCallEvent(agent_id="x", tenant_id="t", tool="w",
                            args={}, ok=True, duration_ms=1, trace_id="tr"),
        AgentLLMCallEvent(agent_id="x", tenant_id="t", model="m",
                           prompt_tokens=0, completion_tokens=0,
                           trace_id="tr"),
    ]
    for e in evts:
        assert _is_iso8601_utc(e.to_dict()["ts"])
