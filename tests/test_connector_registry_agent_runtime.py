"""Tests for the agent-runtime ConnectorType + probe_agent_runtime.

Phase 1, Task 5. Verifies:
  - ``agent-runtime`` is registered in CONNECTOR_TYPES with the right
    metadata and field surface (Defaults / Resources / Tool behaviour /
    Audit groups, both required enum_integration fields).
  - ``probe_agent_runtime`` returns a clean failure when spm-mcp is
    unreachable (the typical Phase-1 dev state until the service is up).
  - ``probe_integration_by_id`` short-circuits cleanly on empty ID and
    on unknown connector_type without raising.
"""
from __future__ import annotations

from typing import Any, Dict, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import connector_registry  # noqa: E402  — sys.path set in conftest
import connector_probes    # noqa: E402
from connector_registry import (  # noqa: E402
    CONNECTOR_TYPES,
    list_connector_types,
    options_provider_filters,
    probe_integration_by_id,
)


# ─── 1. Registry surface ───────────────────────────────────────────────────

class TestAgentRuntimeRegistered:
    def test_agent_runtime_present(self):
        assert "agent-runtime" in CONNECTOR_TYPES

    def test_agent_runtime_metadata(self):
        ct = CONNECTOR_TYPES["agent-runtime"]
        assert ct["key"]      == "agent-runtime"
        assert ct["category"] == "AI Providers"
        assert ct["vendor"]   == "AI-SPM"
        assert ct["label"].startswith("AI-SPM Agent Runtime Control Plane")

    def test_required_field_keys(self):
        keys = {f["key"] for f in CONNECTOR_TYPES["agent-runtime"]["fields"]}
        # Spec § 5 — minimum surface
        assert {"default_llm_integration_id",
                "tavily_integration_id",
                "default_memory_mb",
                "default_cpu_quota",
                "tool_call_timeout_s",
                "max_concurrent_agents",
                "max_sessions_per_agent",
                "tavily_max_results",
                "tavily_max_chars",
                "log_llm_prompts",
                "audit_topic_suffix"} <= keys

    def test_required_field_groups(self):
        groups = {f.get("group")
                  for f in CONNECTOR_TYPES["agent-runtime"]["fields"]
                  if f.get("group")}
        assert {"Defaults", "Resources", "Tool behaviour", "Audit"} <= groups

    def test_enum_integration_fields_carry_options_provider(self):
        ct = CONNECTOR_TYPES["agent-runtime"]
        by_key = {f["key"]: f for f in ct["fields"]}

        f_llm = by_key["default_llm_integration_id"]
        assert f_llm["type"]             == "enum_integration"
        assert f_llm["options_provider"] == "ai_provider_integrations"
        assert f_llm.get("required")     is True

        f_tav = by_key["tavily_integration_id"]
        assert f_tav["type"]             == "enum_integration"
        assert f_tav["options_provider"] == "tavily_integrations"
        assert f_tav.get("required")     is True

    def test_options_providers_resolve_to_filter_pairs(self):
        # Each enum_integration field's options_provider MUST resolve to a
        # known (category, vendor) pair, else the frontend dropdown would
        # be empty.
        ct = CONNECTOR_TYPES["agent-runtime"]
        for f in ct["fields"]:
            if f.get("type") == "enum_integration":
                cat, _vend = options_provider_filters(f["options_provider"])
                assert cat is not None, (
                    f"options_provider {f['options_provider']!r} not "
                    f"registered in connector_registry._OPTIONS_PROVIDER_FILTERS"
                )

    def test_appears_in_list_connector_types(self):
        rows = list_connector_types()
        keys = {r["key"] for r in rows}
        assert "agent-runtime" in keys
        # Sorted by (category, label) — agent-runtime is in AI Providers.
        agent_row = next(r for r in rows if r["key"] == "agent-runtime")
        assert agent_row["category"] == "AI Providers"


# ─── 2. probe_agent_runtime ────────────────────────────────────────────────

class TestProbeAgentRuntime:
    """The probe runs three checks; each test isolates one."""

    @pytest.mark.asyncio
    async def test_returns_false_when_spm_mcp_unreachable(self, monkeypatch):
        # No spm-mcp running in the test env — httpx raises a connect error.
        # The probe must catch it and return (False, msg, None).
        async def _bad_get(self, url, **kw):
            raise httpx.ConnectError("connection refused", request=None)
        monkeypatch.setattr(httpx.AsyncClient, "get", _bad_get)

        ok, msg, _ = await connector_probes.probe_agent_runtime(
            config={
                "default_llm_integration_id": "int-llm",
                "tavily_integration_id":      "int-tav",
            },
            creds={},
        )
        assert ok is False
        assert "spm-mcp" in msg.lower()

    @pytest.mark.asyncio
    async def test_returns_false_when_health_returns_non_200(self, monkeypatch):
        async def _500(self, url, **kw):
            return httpx.Response(500, request=httpx.Request("GET", url))
        monkeypatch.setattr(httpx.AsyncClient, "get", _500)

        ok, msg, _ = await connector_probes.probe_agent_runtime(
            config={
                "default_llm_integration_id": "int-llm",
                "tavily_integration_id":      "int-tav",
            },
            creds={},
        )
        assert ok is False
        assert "500" in msg

    @pytest.mark.asyncio
    async def test_returns_false_when_default_llm_id_unset(self, monkeypatch):
        async def _200(self, url, **kw):
            return httpx.Response(200, json={"ok": True},
                                  request=httpx.Request("GET", url))
        monkeypatch.setattr(httpx.AsyncClient, "get", _200)

        ok, msg, _ = await connector_probes.probe_agent_runtime(
            config={"tavily_integration_id": "int-tav"},  # no default LLM
            creds={},
        )
        assert ok is False
        assert "Default LLM" in msg or "default_llm_integration_id" in msg.lower()

    @pytest.mark.asyncio
    async def test_returns_false_when_tavily_id_unset(self, monkeypatch):
        # /health → 200
        async def _200(self, url, **kw):
            return httpx.Response(200, json={"ok": True},
                                  request=httpx.Request("GET", url))
        monkeypatch.setattr(httpx.AsyncClient, "get", _200)

        # Mock probe_integration_by_id so the default-LLM check passes
        # without touching the DB; that lets the test reach the Tavily
        # branch where the missing config field is the only failure mode.
        async def _ok(integration_id):
            return True, "stubbed ok", 1
        monkeypatch.setattr(connector_registry,
                             "probe_integration_by_id", _ok)

        ok, msg, _ = await connector_probes.probe_agent_runtime(
            config={"default_llm_integration_id": "int-llm"},  # no Tavily
            creds={},
        )
        assert ok is False
        assert "Tavily" in msg or "tavily_integration_id" in msg.lower()

    @pytest.mark.asyncio
    async def test_returns_true_when_all_three_checks_pass(self, monkeypatch):
        async def _200(self, url, **kw):
            return httpx.Response(200, json={"ok": True},
                                  request=httpx.Request("GET", url))
        monkeypatch.setattr(httpx.AsyncClient, "get", _200)

        async def _ok(integration_id):
            return True, "stubbed ok", 1
        monkeypatch.setattr(connector_registry,
                             "probe_integration_by_id", _ok)

        ok, msg, latency = await connector_probes.probe_agent_runtime(
            config={
                "default_llm_integration_id": "int-llm",
                "tavily_integration_id":      "int-tav",
            },
            creds={},
        )
        assert ok is True, msg
        assert latency is not None and latency >= 0


# ─── 3. probe_integration_by_id ────────────────────────────────────────────

class TestProbeIntegrationById:
    @pytest.mark.asyncio
    async def test_empty_id_returns_false(self):
        ok, msg, latency = await probe_integration_by_id("")
        assert ok is False
        assert "missing" in msg.lower()
        assert latency is None

    @pytest.mark.asyncio
    async def test_unknown_id_returns_false(self, monkeypatch):
        # Mock get_session_factory → async session that returns no rows.
        result = MagicMock()
        result.scalar_one_or_none.return_value = None

        session = MagicMock()
        session.execute = AsyncMock(return_value=result)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__  = AsyncMock(return_value=None)

        sf = MagicMock(return_value=session)
        # Patch through the lazy-import boundary in connector_registry.
        import spm.db.session as db_session
        monkeypatch.setattr(db_session, "get_session_factory", lambda: sf)

        ok, msg, _ = await probe_integration_by_id("does-not-exist")
        assert ok is False
        assert "not found" in msg.lower()
