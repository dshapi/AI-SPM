"""Module-level connection constants.

The SDK fetches its connection bundle (TENANT_ID, MCP_URL, LLM_*,
KAFKA_BOOTSTRAP_SERVERS) from the controller's DB-backed
``/agents/{id}/bootstrap`` endpoint at import time. When the controller
is unreachable (as in these tests — no spm-api process is running) the
SDK falls back to the matching env vars; that's what we exercise here.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def aispm_with_env(monkeypatch):
    """Install env vars then reload aispm so its constants pick them up."""
    def _install(env: dict):
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        import aispm
        importlib.reload(aispm)
        return aispm
    return _install


def test_constants_populated(aispm_with_env):
    aispm = aispm_with_env({
        "AGENT_ID":     "ag-001",
        "TENANT_ID":    "t1",
        "MCP_URL":      "http://spm-mcp:8500/mcp",
        "MCP_TOKEN":    "mcp-x",
        "LLM_BASE_URL": "http://spm-llm-proxy:8500/v1",
        "LLM_API_KEY":  "llm-x",
        "KAFKA_BOOTSTRAP_SERVERS": "kafka-broker:9092",
    })
    assert aispm.AGENT_ID                == "ag-001"
    assert aispm.TENANT_ID               == "t1"
    assert aispm.MCP_URL                 == "http://spm-mcp:8500/mcp"
    assert aispm.MCP_TOKEN               == "mcp-x"
    assert aispm.LLM_BASE_URL            == "http://spm-llm-proxy:8500/v1"
    assert aispm.LLM_API_KEY              == "llm-x"
    assert aispm.KAFKA_BOOTSTRAP_SERVERS == "kafka-broker:9092"


def test_unset_env_defaults_to_empty(aispm_with_env, monkeypatch):
    # No env, no controller — every connection constant should be the
    # empty string. Only CONTROLLER_URL has a hardcoded default
    # (the in-cluster spm-api host) because we need *something* to point
    # the bootstrap call at.
    for k in ("AGENT_ID", "TENANT_ID", "MCP_URL", "MCP_TOKEN", "LLM_BASE_URL",
              "LLM_API_KEY", "KAFKA_BOOTSTRAP_SERVERS", "CONTROLLER_URL"):
        monkeypatch.delenv(k, raising=False)

    aispm = aispm_with_env({})
    assert aispm.AGENT_ID  == ""
    assert aispm.MCP_URL   == ""
    assert aispm.TENANT_ID == ""
    assert aispm.CONTROLLER_URL.startswith("http://spm-api")


def test_public_surface_exposes_submodules(aispm_with_env):
    aispm = aispm_with_env({})
    for name in ("chat", "lifecycle", "llm", "log", "mcp", "secrets", "types"):
        assert hasattr(aispm, name), f"aispm.{name} missing"
    assert callable(aispm.get_secret)
    assert callable(aispm.ready)
