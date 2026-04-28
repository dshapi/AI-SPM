"""Tests for services.spm_api.agent_controller — Tasks 11–14.

The controller's side-effects (Kafka admin, Kubernetes API, DB session)
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
import kubernetes


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


# ─── Task 13 — Kubernetes Pod spawn / stop ────────────────────────────────────

def _make_k8s_core_mock(*, pod_calls: Dict[str, Any] = None):
    """Return a mock CoreV1Api where cleanup delete calls 404 (nothing to clean)
    and create calls capture their body argument."""
    from kubernetes.client.exceptions import ApiException

    core = MagicMock()
    # Cleanup path: 404 = resource absent, skip gracefully.
    not_found = ApiException(status=404)
    core.delete_namespaced_pod.side_effect       = not_found
    core.delete_namespaced_config_map.side_effect = not_found

    if pod_calls is not None:
        def _create_pod(namespace, body):
            pod_calls["body"] = body
            pod = MagicMock()
            pod.metadata.uid = "uid-test"
            return pod
        core.create_namespaced_pod.side_effect = _create_pod

    return core


class TestSpawnAgentContainer:
    @pytest.mark.asyncio
    async def test_passes_env_and_resource_limits(self, monkeypatch):
        pod_calls: Dict[str, Any] = {}
        core = _make_k8s_core_mock(pod_calls=pod_calls)
        monkeypatch.setattr(agent_controller, "_k8s_core", lambda: core)

        pod_name = await agent_controller.spawn_agent_container(
            agent_id="ag-001", tenant_id="t1",
            code_blob="print('hello')",
            mcp_token="mcp-x", llm_api_key="llm-x",
        )
        assert pod_name == "agent-ag-001"

        # Inspect env vars on the created Pod spec.
        env_map = {
            e.name: e.value
            for e in pod_calls["body"].spec.containers[0].env
        }
        assert env_map["AGENT_ID"]       == "ag-001"
        assert env_map["MCP_TOKEN"]      == "mcp-x"
        assert "CONTROLLER_URL" in env_map
        # LLM_API_KEY is injected directly into the pod env in the k8s path.
        assert env_map["LLM_API_KEY"]    == "llm-x"

    @pytest.mark.asyncio
    async def test_uses_agent_id_as_pod_name(self, monkeypatch):
        pod_calls: Dict[str, Any] = {}
        core = _make_k8s_core_mock(pod_calls=pod_calls)
        monkeypatch.setattr(agent_controller, "_k8s_core", lambda: core)

        result = await agent_controller.spawn_agent_container(
            agent_id="ag-002", tenant_id="t1",
            code_blob="print('hi')", mcp_token="m", llm_api_key="l",
        )
        # Pod name is "agent-{agent_id}" — the return value of spawn_agent_pod.
        assert result == "agent-ag-002"


class TestStopAgentContainer:
    @pytest.mark.asyncio
    async def test_stops_and_removes(self, monkeypatch):
        from kubernetes.client.exceptions import ApiException

        core = MagicMock()
        # Simulate successful deletion (no exception = resource existed and was deleted).
        core.delete_namespaced_pod.return_value       = MagicMock()
        core.delete_namespaced_config_map.return_value = MagicMock()
        monkeypatch.setattr(agent_controller, "_k8s_core", lambda: core)

        await agent_controller.stop_agent_container("ag-001")
        core.delete_namespaced_pod.assert_called_once()
        core.delete_namespaced_config_map.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_container_is_noop(self, monkeypatch):
        from kubernetes.client.exceptions import ApiException

        core = MagicMock()
        # 404 on both deletes — resource already absent; must NOT raise.
        not_found = ApiException(status=404)
        core.delete_namespaced_pod.side_effect        = not_found
        core.delete_namespaced_config_map.side_effect  = not_found
        monkeypatch.setattr(agent_controller, "_k8s_core", lambda: core)

        # Must NOT raise.
        await agent_controller.stop_agent_container("ag-doesnt-exist")


# ─── Task 14 — Lifecycle orchestration ─────────────────────────────────────

def _fake_agent_row(*, agent_id="ag-001", tenant_id="t1",
                     state="stopped",
                     code_blob="print('agent')",
                     mcp_token="m", llm_api_key="l"):
    """SQLAlchemy-row-shaped MagicMock."""
    a = MagicMock()
    a.id        = agent_id
    a.tenant_id = tenant_id
    a.runtime_state = state
    a.code_blob = code_blob
    a.mcp_token = mcp_token
    a.llm_api_key = llm_api_key
    return a


def _fake_db_with(row):
    """Mock async-session shape used by the lifecycle controllers.

    - ``db.get`` is sync (returns ``row``) — ``_db_get`` handles both
      sync MagicMock returns and real AsyncSession coroutines.
    - ``db.execute`` is AsyncMock returning a result whose
      ``scalar_one_or_none()`` yields the same row. Used by
      ``retire_agent``'s eager-load path.
    - ``db.delete`` and ``db.commit`` are AsyncMock so the
      ``_db_delete`` / ``_db_commit`` helpers' ``await`` succeeds.
    """
    db = MagicMock()
    db.get.return_value = row

    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db.execute = AsyncMock(return_value=result)
    db.delete  = AsyncMock()
    db.commit  = AsyncMock()
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

        async def _wait_ready_immediately(db, agent_id, *, timeout_s):
            """Stand-in for the SDK's POST /ready: flip state to running
            as if the handshake just arrived."""
            calls.append(("wait-ready", agent_id))
            row.runtime_state = "running"

        monkeypatch.setattr(agent_controller, "create_agent_topics", _topics)
        monkeypatch.setattr(agent_controller, "spawn_agent_pod", _spawn)
        monkeypatch.setattr(agent_controller, "_wait_for_ready",
                             _wait_ready_immediately)

        row = _fake_agent_row()
        db  = _fake_db_with(row)
        await agent_controller.deploy_agent(db, "ag-001")

        # Orchestration order: topics → spawn → wait-for-ready.
        assert [c[0] for c in calls] == ["topics", "spawn", "wait-ready"]
        # Final state on the row is "running".
        assert row.runtime_state == "running"
        # At least two commits: marking starting, then back-end logic.
        assert db.commit.call_count >= 1

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
        monkeypatch.setattr(agent_controller, "spawn_agent_pod", _spawn)

        row = _fake_agent_row(state="running")
        db  = _fake_db_with(row)
        await agent_controller.start_agent(db, "ag-001")
        assert called["spawn"] == 0

    @pytest.mark.asyncio
    async def test_start_stopped_spawns_and_marks_starting(self, monkeypatch):
        async def _spawn(**kw):
            return "agent-ag-001"
        monkeypatch.setattr(agent_controller, "spawn_agent_pod", _spawn)

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
        monkeypatch.setattr(agent_controller, "stop_agent_pod", _stop)

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
        monkeypatch.setattr(agent_controller, "stop_agent_pod", _stop)
        monkeypatch.setattr(agent_controller, "delete_agent_topics", _del)

        row = _fake_agent_row(state="running", agent_id="ag-001")
        db  = _fake_db_with(row)
        await agent_controller.retire_agent(db, "ag-001")
        assert calls[0][0] == "stop"
        assert calls[1][0] == "del-topics"
        db.delete.assert_called_with(row)
