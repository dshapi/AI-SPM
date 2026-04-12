"""
threathunting_ai/scan_registry.py
───────────────────────────────────
Central registry of all ThreatHunting AI proactive scans.

Each entry maps a scan name to a ScanDefinition with a deterministic,
read-only collector callable. The LLM is never in the scan path.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List


@dataclass(frozen=True)
class ScanDefinition:
    """Immutable descriptor for one proactive scan."""
    name:        str
    description: str
    collector:   Callable[[], List[Dict[str, Any]]]


def _lazy_secrets() -> List[Dict[str, Any]]:
    from threathunting_ai.collectors.secrets_collector import collect
    return collect()


def _lazy_network() -> List[Dict[str, Any]]:
    from threathunting_ai.collectors.network_collector import collect
    return collect()


def _lazy_agent_config() -> List[Dict[str, Any]]:
    from threathunting_ai.collectors.agent_config_collector import collect
    return collect()


def _lazy_runtime() -> List[Dict[str, Any]]:
    from threathunting_ai.collectors.runtime_collector import collect
    return collect()


def _lazy_sensitive_data() -> List[Dict[str, Any]]:
    from threathunting_ai.collectors.secrets_collector import collect_sensitive_data
    return collect_sensitive_data()


def _lazy_prompt_secrets() -> List[Dict[str, Any]]:
    from threathunting_ai.collectors.prompt_secrets_collector import collect
    return collect()


def _lazy_data_leakage() -> List[Dict[str, Any]]:
    from threathunting_ai.collectors.data_leakage_collector import collect
    return collect()


def _lazy_tool_misuse() -> List[Dict[str, Any]]:
    from threathunting_ai.collectors.tool_misuse_collector import collect
    return collect()


def _lazy_proc_network() -> List[Dict[str, Any]]:
    from threathunting_ai.collectors.proc_network_collector import collect
    return collect()


SCAN_REGISTRY: Dict[str, ScanDefinition] = {
    "exposed_credentials": ScanDefinition(
        name="exposed_credentials",
        description=(
            "Scan Redis key names for patterns matching API keys, tokens, "
            "passwords, and other credentials that should not be in memory."
        ),
        collector=_lazy_secrets,
    ),
    "unused_open_ports": ScanDefinition(
        name="unused_open_ports",
        description=(
            "Probe known internal service ports to detect unexpected "
            "reachability that may indicate a misconfigured or rogue service."
        ),
        collector=_lazy_network,
    ),
    "overprivileged_tools": ScanDefinition(
        name="overprivileged_tools",
        description=(
            "Query the model registry for AI models with unacceptable risk tier "
            "still in active status, or missing mandatory approval metadata."
        ),
        collector=_lazy_agent_config,
    ),
    "sensitive_data_exposure": ScanDefinition(
        name="sensitive_data_exposure",
        description=(
            "Broader scan for PII patterns, database connection strings, and "
            "other sensitive data stored under unexpected Redis namespaces."
        ),
        collector=_lazy_sensitive_data,
    ),
    "runtime_anomaly_detection": ScanDefinition(
        name="runtime_anomaly_detection",
        description=(
            "Detect abnormal session patterns: high-frequency actors, enforcement "
            "block clusters (3+ blocks/session/hour), and session storms "
            "(5+ distinct sessions/actor/10 min)."
        ),
        collector=_lazy_runtime,
    ),
    "prompt_secret_exfiltration": ScanDefinition(
        name="prompt_secret_exfiltration",
        description=(
            "Scan audit log for prompt payloads that contain secret-like patterns "
            "(API keys, bearer tokens, passwords) about to leave the system."
        ),
        collector=_lazy_prompt_secrets,
    ),
    "data_leakage_detection": ScanDefinition(
        name="data_leakage_detection",
        description=(
            "Detect PII and sensitive data patterns (SSN, credit-card numbers, "
            "email addresses) appearing in agent responses or tool outputs."
        ),
        collector=_lazy_data_leakage,
    ),
    "tool_misuse_detection": ScanDefinition(
        name="tool_misuse_detection",
        description=(
            "Detect tool-abuse patterns: high-frequency tool calls per actor/hour, "
            "rapid chaining (>5 calls/session/minute), and high blocked-call ratios."
        ),
        collector=_lazy_tool_misuse,
    ),
    "unexpected_listen_ports": ScanDefinition(
        name="unexpected_listen_ports",
        description=(
            "Parse /proc/net/tcp to detect ports in LISTEN state that are not in "
            "the expected service allowlist — potential rogue or misconfigured processes."
        ),
        collector=_lazy_proc_network,
    ),
}

# Ordered list for deterministic iteration
SCAN_NAMES: List[str] = list(SCAN_REGISTRY.keys())
