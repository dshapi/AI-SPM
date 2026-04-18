"""
threathunting_ai/collectors/network_collector.py
──────────────────────────────────────────────────
Probe known internal service ports to detect unexpected reachability.

Read-only (socket connect only, no data sent). Deterministic.
"""
from __future__ import annotations

import logging
import socket
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# (host, port, expected_reachable, service_name)
# expected_reachable=True  → flag if NOT reachable (service down)
# expected_reachable=False → flag if IS reachable (rogue / misconfigured)
_PROBE_TARGETS = [
    ("agent-orchestrator", 8094, True,  "agent-orchestrator-service"),
    ("api",                8080, True,  "platform-api"),
    ("guard-model",        8200, True,  "guard-model-service"),
    ("opa",                8181, True,  "opa-policy-engine"),
    ("redis",              6379, True,  "redis-cache"),
    ("kafka-broker",       9092, True,  "kafka-broker"),
    # DB should NOT be directly reachable from agent container
    ("spm-db",             5432, False, "postgres-spm-db"),
]

_CONNECT_TIMEOUT = 1.0   # seconds — keep scans fast


def _probe(host: str, port: int) -> bool:
    """Return True if (host, port) is reachable, False otherwise."""
    try:
        with socket.create_connection((host, port), timeout=_CONNECT_TIMEOUT):
            return True
    except (ConnectionRefusedError, socket.timeout, OSError):
        return False


def collect() -> List[Dict[str, Any]]:
    """
    Probe all known service endpoints and return a structured status list.
    Flags unexpected reachability and unexpected outages.
    """
    results: List[Dict[str, Any]] = []
    for host, port, expected, service_name in _PROBE_TARGETS:
        try:
            reachable = _probe(host, port)
            anomalous = reachable != expected
            results.append({
                "type":               "port_status",
                "host":               host,
                "port":               port,
                "service_name":       service_name,
                "reachable":          reachable,
                "expected_reachable": expected,
                "anomalous":          anomalous,
            })
            if anomalous:
                logger.warning(
                    "network_collector: anomaly host=%s port=%d reachable=%s expected=%s",
                    host, port, reachable, expected,
                )
        except Exception as exc:
            logger.warning("network_collector: probe failed host=%s port=%d: %s", host, port, exc)

    return results
