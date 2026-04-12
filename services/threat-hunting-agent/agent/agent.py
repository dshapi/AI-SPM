"""
agent/agent.py
───────────────
Builds and returns the LangChain threat-hunting agent.

Uses `langchain.agents.create_agent` (LangChain ≥ 1.x) with ChatGroq
as the LLM.  All 8 tool functions are wrapped with StructuredTool so
the agent sees typed schemas.

The agent is stateless and re-created per hunt batch; the Kafka consumer
calls `run_hunt()` with a batch of events and gets back a summary string.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field

from agent.prompts import SYSTEM_PROMPT
from tools import (
    create_threat_finding,
    evaluate_opa_policy,
    get_freeze_state,
    lookup_mitre_technique,
    query_audit_logs,
    query_model_registry,
    query_posture_history,
    scan_session_memory,
    screen_text,
    search_mitre_techniques,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic input schemas (so StructuredTool gets a proper JSON schema)
# ─────────────────────────────────────────────────────────────────────────────

class _QueryAuditLogsInput(BaseModel):
    tenant_id: str = Field(..., description="Tenant to scope the query")
    event_type: str = Field("", description="Optional event_type filter")
    actor: str = Field("", description="Optional actor filter")
    limit: int = Field(50, description="Max rows (1-200)")


class _QueryPostureHistoryInput(BaseModel):
    tenant_id: str = Field(..., description="Tenant to scope the query")
    model_id: str = Field("", description="Optional model UUID filter")
    hours: int = Field(24, description="How far back to look (1-168)")
    limit: int = Field(100, description="Max rows (1-500)")


class _QueryModelRegistryInput(BaseModel):
    tenant_id: str = Field(..., description="Tenant to scope the query")
    risk_tier: str = Field("", description="Optional risk tier filter")
    status: str = Field("", description="Optional status filter")
    limit: int = Field(50, description="Max rows (1-200)")


class _GetFreezeStateInput(BaseModel):
    scope: str = Field(..., description="'user', 'tenant', or 'session'")
    target: str = Field(..., description="ID to check")


class _ScanSessionMemoryInput(BaseModel):
    tenant_id: str = Field(..., description="Tenant to scope the scan")
    user_id: str = Field(..., description="User whose memory to inspect")
    namespace: str = Field("session", description="'session', 'longterm', or 'system'")
    max_keys: int = Field(50, description="Max keys to return")


class _LookupMitreInput(BaseModel):
    technique_id: str = Field(..., description="ATT&CK or ATLAS technique ID, e.g. AML.T0051")


class _SearchMitreInput(BaseModel):
    query: str = Field(..., description="Keyword search string")
    max_results: int = Field(5, description="Max results to return")


class _EvalOpaInput(BaseModel):
    policy_path: str = Field(..., description="OPA policy path, e.g. /v1/data/spm/authz/decision")
    input_data: Dict[str, Any] = Field(default_factory=dict, description="Input facts for the policy")


class _ScreenTextInput(BaseModel):
    text: str = Field(..., description="Text to screen through the guard model")


class _CreateFindingInput(BaseModel):
    tenant_id: str = Field(..., description="Tenant to scope the finding")
    title: str = Field(..., description="Short descriptive title")
    severity: str = Field(..., description="low | medium | high | critical")
    description: str = Field(..., description="Detailed description of the threat")
    evidence: Dict[str, Any] = Field(default_factory=dict, description="Supporting evidence dict")
    ttps: List[str] = Field(default_factory=list, description="MITRE ATT&CK / ATLAS TTP IDs")


# ─────────────────────────────────────────────────────────────────────────────
# Thin wrappers that drop empty-string optional args
# ─────────────────────────────────────────────────────────────────────────────

def _query_audit_logs(tenant_id: str, event_type: str = "", actor: str = "", limit: int = 50) -> str:
    return query_audit_logs(
        tenant_id=tenant_id,
        event_type=event_type or None,
        actor=actor or None,
        limit=limit,
    )


def _query_posture_history(tenant_id: str, model_id: str = "", hours: int = 24, limit: int = 100) -> str:
    return query_posture_history(
        tenant_id=tenant_id,
        model_id=model_id or None,
        hours=hours,
        limit=limit,
    )


def _query_model_registry(tenant_id: str, risk_tier: str = "", status: str = "", limit: int = 50) -> str:
    return query_model_registry(
        tenant_id=tenant_id,
        risk_tier=risk_tier or None,
        status=status or None,
        limit=limit,
    )


def _eval_opa(policy_path: str, input_data: Dict[str, Any]) -> str:
    return evaluate_opa_policy(policy_path=policy_path, input_data=input_data)


# ─────────────────────────────────────────────────────────────────────────────
# Build the LangChain tool list
# ─────────────────────────────────────────────────────────────────────────────

def _build_tools() -> list:
    return [
        StructuredTool.from_function(
            func=_query_audit_logs,
            name="query_audit_logs",
            description="Fetch recent audit log entries from the SPM database for a tenant.",
            args_schema=_QueryAuditLogsInput,
        ),
        StructuredTool.from_function(
            func=_query_posture_history,
            name="query_posture_history",
            description="Fetch posture snapshot metrics (risk scores, block rates) for a tenant or model.",
            args_schema=_QueryPostureHistoryInput,
        ),
        StructuredTool.from_function(
            func=_query_model_registry,
            name="query_model_registry",
            description="Retrieve registered AI models and their risk classification for a tenant.",
            args_schema=_QueryModelRegistryInput,
        ),
        StructuredTool.from_function(
            func=get_freeze_state,
            name="get_freeze_state",
            description="Check whether a user, tenant, or session is currently frozen.",
            args_schema=_GetFreezeStateInput,
        ),
        StructuredTool.from_function(
            func=scan_session_memory,
            name="scan_session_memory",
            description="Scan Redis for memory keys belonging to a user (detects anomalous memory usage).",
            args_schema=_ScanSessionMemoryInput,
        ),
        StructuredTool.from_function(
            func=lookup_mitre_technique,
            name="lookup_mitre_technique",
            description="Look up a specific MITRE ATT&CK or ATLAS technique by ID.",
            args_schema=_LookupMitreInput,
        ),
        StructuredTool.from_function(
            func=search_mitre_techniques,
            name="search_mitre_techniques",
            description="Search MITRE ATT&CK / ATLAS techniques by keyword.",
            args_schema=_SearchMitreInput,
        ),
        StructuredTool.from_function(
            func=_eval_opa,
            name="evaluate_opa_policy",
            description="Evaluate an OPA Rego policy to understand a decision or check a scenario.",
            args_schema=_EvalOpaInput,
        ),
        StructuredTool.from_function(
            func=screen_text,
            name="screen_text",
            description="Re-screen a suspicious prompt or output through the guard model.",
            args_schema=_ScreenTextInput,
        ),
        StructuredTool.from_function(
            func=create_threat_finding,
            name="create_threat_finding",
            description="Create a persisted threat finding in the orchestrator (deduplicated).",
            args_schema=_CreateFindingInput,
        ),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Agent factory
# ─────────────────────────────────────────────────────────────────────────────

def build_agent(groq_api_key: str, model: str = "llama-3.3-70b-versatile") -> Any:
    """
    Build and return the compiled LangChain agent graph.

    The agent is stateless — call agent.invoke() with a new HumanMessage
    for each hunt batch.
    """
    llm = ChatGroq(
        api_key=groq_api_key,
        model=model,
        temperature=0,
    )
    tools = _build_tools()
    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
    )
    return agent


# ─────────────────────────────────────────────────────────────────────────────
# High-level entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_hunt(agent: Any, tenant_id: str, events: List[Dict[str, Any]]) -> str:
    """
    Run a threat hunt over a batch of events.

    Args:
        agent: Compiled agent graph from build_agent().
        tenant_id: Tenant the events belong to.
        events: List of event dicts (PostureEnrichedEvent / DecisionEvent shapes).

    Returns:
        Human-readable hunt summary string.
    """
    event_summary = json.dumps(events, default=str, indent=2)
    prompt = (
        f"Threat hunt requested for tenant '{tenant_id}'.\n\n"
        f"Batch of {len(events)} events:\n{event_summary}\n\n"
        "Analyse these events for threats. Use your tools to gather additional context. "
        "Create a threat finding if you identify a credible threat. "
        "Finish with a concise summary."
    )

    try:
        result = agent.invoke({"messages": [HumanMessage(content=prompt)]})
        # The agent returns a dict with a 'messages' key; last message is the final answer
        messages = result.get("messages", [])
        if messages:
            last = messages[-1]
            return getattr(last, "content", str(last))
        return str(result)
    except Exception as exc:
        logger.exception("run_hunt failed for tenant=%s: %s", tenant_id, exc)
        return f"Hunt failed: {exc}"
