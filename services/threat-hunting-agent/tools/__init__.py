"""
tools/__init__.py
──────────────────
Exports all LangChain-compatible tool functions for the threat-hunting agent.

Each function takes plain Python args and returns a JSON string so it can
be wrapped with @tool or StructuredTool.from_function() in agent/agent.py.
"""
from tools.postgres_tool import (
    query_audit_logs,
    query_model_registry,
    query_posture_history,
    set_connection_factory,
)
from tools.redis_tool import (
    get_freeze_state,
    scan_session_memory,
    set_redis_client,
)
from tools.mitre_tool import (
    lookup_mitre_technique,
    search_mitre_techniques,
)
from tools.opa_tool import (
    evaluate_opa_policy,
    set_opa_client,
)
from tools.guard_tool import (
    screen_text,
    set_guard_url,
)
from tools.case_tool import (
    configure as configure_case_tool,
    create_case,
    create_threat_finding,
    _compute_batch_hash,
    set_http_client as set_case_http_client,
)

__all__ = [
    # Postgres
    "query_audit_logs",
    "query_posture_history",
    "query_model_registry",
    "set_connection_factory",
    # Redis
    "get_freeze_state",
    "scan_session_memory",
    "set_redis_client",
    # MITRE
    "lookup_mitre_technique",
    "search_mitre_techniques",
    # OPA
    "evaluate_opa_policy",
    "set_opa_client",
    # Guard
    "screen_text",
    "set_guard_url",
    # Case creation
    "create_case",
    "create_threat_finding",
    "configure_case_tool",
    "set_case_http_client",
]
