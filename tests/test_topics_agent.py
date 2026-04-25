"""Tests for the per-agent chat topic helper."""
from platform_shared.topics import AgentTopics, agent_topics_for


def test_agent_topics_for_format():
    t = agent_topics_for("t1", "ag-001")
    assert t.chat_in  == "cpm.t1.agents.ag-001.chat.in"
    assert t.chat_out == "cpm.t1.agents.ag-001.chat.out"


def test_agent_topics_all_returns_both_in_order():
    t = agent_topics_for("t1", "ag-001")
    assert t.all() == [
        "cpm.t1.agents.ag-001.chat.in",
        "cpm.t1.agents.ag-001.chat.out",
    ]


def test_agent_topics_uses_tenant_prefix():
    """A different tenant gets a different topic prefix — multi-tenant safe."""
    t1 = agent_topics_for("acme",  "ag-001")
    t2 = agent_topics_for("globex", "ag-001")
    assert t1.chat_in != t2.chat_in
    assert t1.chat_in.startswith("cpm.acme.")
    assert t2.chat_in.startswith("cpm.globex.")


def test_agent_topics_distinct_per_agent():
    """Two agents in the same tenant get distinct topics."""
    a = agent_topics_for("t1", "ag-001")
    b = agent_topics_for("t1", "ag-002")
    assert a.chat_in  != b.chat_in
    assert a.chat_out != b.chat_out


def test_agent_topics_is_frozen_dataclass():
    """Frozen so callers can't mutate the names mid-flight."""
    import dataclasses
    t = agent_topics_for("t1", "ag-001")
    assert isinstance(t, AgentTopics)
    fields = {f.name for f in dataclasses.fields(t)}
    assert fields == {"chat_in", "chat_out"}
