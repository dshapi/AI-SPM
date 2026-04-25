"""Tests for services.spm_api.agent_controller — Tasks 11–14.

The controller's side-effects (Kafka admin, Docker SDK, DB session)
are heavy; we mock them all and assert the controller wires the right
arguments at the right time. End-to-end smoke is in tests/e2e
(Task 18) which exercises the real stack.
"""
from __future__ import annotations

import re
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest

import agent_controller


# ─── Task 11 — mint_agent_tokens ──────────────────────────────────────────

class TestMintAgentTokens:
    def test_returns_two_distinct_tokens(self):
        m, l = agent_controller.mint_agent_tokens()
        assert m != l

    def test_token_format(self):
        # token_urlsafe(32) → ~43 chars, URL-safe base64 alphabet.
        for t in agent_controller.mint_agent_tokens():
            assert re.fullmatch(r"[A-Za-z0-9_-]{32,}", t)

    def test_minted_pairs_are_unique(self):
        a = agent_controller.mint_agent_tokens()
        b = agent_controller.mint_agent_tokens()
        assert a != b
        # And no token from pair A repeats in pair B.
        assert not (set(a) & set(b))


# ─── Task 12 — Kafka topic CRUD ────────────────────────────────────────────

class TestKafkaTopicCRUD:
    @pytest.mark.asyncio
    async def test_create_creates_in_and_out(self, monkeypatch):
        captured: Dict[str, Any] = {}

        def _fake_admin():
            adm = MagicMock()
            def _create(new_topics, validate_only):
                captured["names"] = [t.name for t in new_topics]
                captured["validate_only"] = validate_only
            adm.create_topics = _create
            return adm
        monkeypatch.setattr(agent_controller, "_kafka_admin", _fake_admin)

        await agent_controller.create_agent_topics(
            tenant_id="t1", agent_id="ag-001",
        )
        assert "cpm.t1.agents.ag-001.chat.in"  in captured["names"]
        assert "cpm.t1.agents.ag-001.chat.out" in captured["names"]
        assert captured["validate_only"] is False

    @pytest.mark.asyncio
    async def test_create_swallows_already_exists(self, monkeypatch):
        from kafka.errors import TopicAlreadyExistsError

        def _fake_admin():
            adm = MagicMock()
            def _create(new_topics, validate_only):
                raise TopicAlreadyExistsError("dupe")
            adm.create_topics = _create
            return adm
        monkeypatch.setattr(agent_controller, "_kafka_admin", _fake_admin)

        # Must NOT raise.
        await agent_controller.create_agent_topics(
            tenant_id="t1", agent_id="ag-001",
        )

    @pytest.mark.asyncio
    async def test_delete_calls_admin(self, monkeypatch):
        captured: Dict[str, Any] = {}

        def _fake_admin():
            adm = MagicMock()
            def _delete(names):
                captured["names"] = list(names)
            adm.delete_topics = _delete
            return adm
        monkeypatch.setattr(agent_controller, "_kafka_admin", _fake_admin)

        await agent_controller.delete_agent_topics(
            tenant_id="t1", agent_id="ag-001",
        )
        assert "cpm.t1.agents.ag-001.chat.in"  in captured["names"]
        assert "cpm.t1.agents.ag-001.chat.out" in captured["names"]


# ─── Task 13 — Docker spawn / stop ─────────────────────────────────────────

class TestSpawnAgentContainer:
    @pytest.mark.asyncio
    async def test_passes_env_and_resource_limits(self, monkeypatch):
        captured: Dict[str, Any] = {}

        def _fake_client():
            client = MagicMock()
            def _run(*args, **kwargs):
                captured.update(kwargs)
                ctr = MagicMock()
                ctr.id = "ctr-abc"
                return ctr
            client.containers.run = _run
            return client
        monkeypatch.setattr(agent_controller, "_docker_client", _fake_client)

        cid = await agent_controller.spawn_agent_container(
            agent_id="ag-001", tenant_id="t1",
            code_path="/var/agents/ag-001/agent.py",
            mcp_token="mcp-x", llm_api_key="llm-x",
            mem_mb=256, cpu_quota=0.5,
        )
        assert cid == "ctr-abc"

        env = captured["environment"]
        assert env["AGENT_ID"]      == "ag-001"
        assert env["TENANT_ID"]     == "t1"
        assert env["MCP_TOKEN"]     == "mcp-x"
        assert env["LLM_API_KEY"]   == "llm-x"
        assert env["MCP_URL"]       == "http://spm-mcp:8500/mcp"
        assert env["LLM_BASE_URL"]  == "http://spm-llm-proxy:8500/v1"
        assert "KAFKA_BOOTSTRAP_SERVERS" in env

        assert captured["mem_limit"] == "256m"
        assert captured["network"]   == "agent-net"
        assert captured["detach"]    is True

    @pytest.mark.asyncio
    async def test_uses_agent_id_as_container_name(self, monkeypatch):
        captured: Dict[str, Any] = {}
        def _fake_client():
            client = MagicMock()
            def _run(*args, **kw):
                captured.update(kw)
                ctr = MagicMock(); ctr.id = "x"; return ctr
            client.containers.run = _run
            return client
        monkeypatch.setattr(agent_controller, "_docker_client", _fake_client)

        await agent_controller.spawn_agent_container(
            agent_id="ag-002", tenant_id="t1",
            code_path="/x", mcp_token="m", llm_api_key="l",
        )
        assert captured["name"] == "agent-ag-002"


class TestStopAgentContainer:
    @pytest.mark.asyncio
    async def test_stops_and_removes(self, monkeypatch):
        ctr = MagicMock()
        client = MagicMock()
        client.containers.get.return_value = ctr
        monkeypatch.setattr(agent_controller, "_docker_client", lambda: client)

        await agent_controller.stop_agent_container("ag-001")
        client.containers.get.assert_called_with("agent-ag-001")
        ctr.stop.assert_called_with(timeout=10)
        ctr.remove.assert_called_with(force=True)

    @pytest.mark.asyncio
    async def test_missing_container_is_noop(self, monkeypatch):
        import docker.errors  # type: ignore
        client = MagicMock()
        client.containers.get.side_effect = docker.errors.NotFound("nope")
        monkeypatch.setattr(agent_controller, "_docker_client", lambda: client)

        # Must NOT raise.
        await agent_controller.stop_agent_container("ag-doesnt-exist")


# ─── Task 14 — Lifecycle orchestration ─────────────────────────────────────

def _fake_agent_row(*, agent_id="ag-001", tenant_id="t1",
                     state="stopped",
                     code_path="/v/agent.py",
                     mcp_token="m", llm_api_key="l"):
    """SQLAlchemy-row-shaped MagicMock."""
    a = MagicMock()
    a.id        = agent_id
    a.tenant_id = tenant_id
    a.runtime_state = state
    a.code_path = code_path
    a.mcp_token = mcp_token
    a.llm_api_key = llm_api_key
    return a


def _fake_db_with(row):
    db = MagicMock()
    db.get.return_value = row
    return db


class TestDeployAgent:
    @pytest.mark.asyncio
    async def test_deploy_calls_topics_then_spawn_then_marks_running(
            self, monkeypatch):
        calls = []

        async def _topics(*, tenant_id, agent_id):
            calls.append(("topics", tenant_id, agent_id))

        async def _spawn(**kw):
            calls.append(("spawn", kw["agent_id"]))
            return "ctr-x"

        # Skip the readiness sleep entirely.
        monkeypatch.setattr(agent_controller, "_READY_SLEEP_S", 0.0)
        monkeypatch.setattr(agent_controller, "create_agent_topics", _topics)
        monkeypatch.setattr(agent_controller, "spawn_agent_container", _spawn)

        row = _fake_agent_row()
        db  = _fake_db_with(row)
        await agent_controller.deploy_agent(db, "ag-001")

        # Order: topics → spawn (state flipped to starting between them
        # via db.commit()).
        assert calls[0][0] == "topics"
        assert calls[1][0] == "spawn"
        # Final state on the row is "running".
        assert row.runtime_state == "running"
        # Two commits: one after marking starting, one after marking running.
        assert db.commit.call_count >= 2

    @pytest.mark.asyncio
    async def test_deploy_unknown_agent_raises(self):
        db = MagicMock()
        db.get.return_value = None
        with pytest.raises(ValueError, match="not found"):
            await agent_controller.deploy_agent(db, "missing")


class TestStartAgent:
    @pytest.mark.asyncio
    async def test_start_running_is_noop(self, monkeypatch):
        called = {"spawn": 0}
        async def _spawn(**kw):
            called["spawn"] += 1
        monkeypatch.setattr(agent_controller, "spawn_agent_container", _spawn)

        row = _fake_agent_row(state="running")
        db  = _fake_db_with(row)
        await agent_controller.start_agent(db, "ag-001")
        assert called["spawn"] == 0

    @pytest.mark.asyncio
    async def test_start_stopped_spawns_and_marks_starting(self, monkeypatch):
        async def _spawn(**kw):
            return "ctr"
        monkeypatch.setattr(agent_controller, "spawn_agent_container", _spawn)

        row = _fake_agent_row(state="stopped")
        db  = _fake_db_with(row)
        await agent_controller.start_agent(db, "ag-001")
        assert row.runtime_state == "starting"
        db.commit.assert_called()


class TestStopAndRetire:
    @pytest.mark.asyncio
    async def test_stop_marks_stopped(self, monkeypatch):
        async def _stop(aid):
            pass
        monkeypatch.setattr(agent_controller, "stop_agent_container", _stop)

        row = _fake_agent_row(state="running")
        db  = _fake_db_with(row)
        await agent_controller.stop_agent(db, "ag-001")
        assert row.runtime_state == "stopped"
        db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_retire_stops_then_deletes_topics_then_row(self, monkeypatch):
        calls = []
        async def _stop(aid):
            calls.append(("stop", aid))
        async def _del(*, tenant_id, agent_id):
            calls.append(("del-topics", tenant_id, agent_id))
        monkeypatch.setattr(agent_controller, "stop_agent_container", _stop)
        monkeypatch.setattr(agent_controller, "delete_agent_topics", _del)

        row = _fake_agent_row(state="running", agent_id="ag-001")
        db  = _fake_db_with(row)
        await agent_controller.retire_agent(db, "ag-001")
        assert calls[0][0] == "stop"
        assert calls[1][0] == "del-topics"
        db.delete.assert_called_with(row)
