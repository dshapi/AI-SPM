"""
threathunting_ai/collectors/proc_network_collector.py
──────────────────────────────────────────────────────
Scan /proc/net/tcp (and /proc/net/tcp6) for unexpected LISTEN-state ports.

Any port found in LISTEN state (tcp_state == 0x0A) that is NOT in the
allowlist of expected service ports is reported as a finding.

Read-only. No external connections. Deterministic. Works inside container.
Returns [] gracefully if /proc/net/tcp is unavailable (e.g. macOS).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

TENANT_ID = "t1"

# ─── known-good LISTEN ports ─────────────────────────────────────────────────
# Add any port the service legitimately binds in this container.
_ALLOWED_LISTEN_PORTS: Set[int] = {
    22,    # SSH
    80,    # HTTP
    443,   # HTTPS
    8000,  # FastAPI / uvicorn dev
    8080,  # alternate HTTP
    5432,  # PostgreSQL (if sidecar)
    6379,  # Redis (if sidecar)
}

# /proc/net/tcp state hex value for LISTEN
_TCP_STATE_LISTEN = 0x0A

# Files to check — tcp6 covers IPv4-mapped addresses on dual-stack kernels too
_PROC_FILES = ["/proc/net/tcp", "/proc/net/tcp6"]


# ─── parser ──────────────────────────────────────────────────────────────────

def _hex_port(local_address: str) -> int:
    """Parse the port from a /proc/net/tcp local_address field '0100007F:1F40'."""
    try:
        return int(local_address.split(":")[1], 16)
    except (IndexError, ValueError):
        return -1


def _parse_proc_net_tcp(path: str) -> List[int]:
    """
    Return a list of ports that are in LISTEN state in `path`.
    Skips the header line. Handles short / malformed lines gracefully.
    """
    listening: List[int] = []
    try:
        with open(path, "r") as fh:
            for line in fh:
                parts = line.split()
                # Header line starts with "sl" — skip
                if len(parts) < 4 or parts[0] == "sl":
                    continue
                local_address = parts[1]   # e.g. "0100007F:1F40"
                state_hex = parts[3]       # e.g. "0A"
                try:
                    state = int(state_hex, 16)
                except ValueError:
                    continue
                if state == _TCP_STATE_LISTEN:
                    port = _hex_port(local_address)
                    if port >= 0:
                        listening.append(port)
    except FileNotFoundError:
        pass   # /proc not available on this OS
    except PermissionError as exc:
        logger.debug("proc_network_collector: cannot read %s: %s", path, exc)
    return listening


# ─── collector ───────────────────────────────────────────────────────────────

class ProcNetworkCollector:
    """Detect unexpected LISTEN-state ports by reading /proc/net/tcp."""

    def collect(self) -> List[Dict[str, Any]]:
        """
        Scan /proc/net/tcp (+ tcp6) for unexpected LISTEN ports.
        Returns [] on macOS / when /proc is not mounted.
        """
        all_listening: Set[int] = set()
        for proc_file in _PROC_FILES:
            all_listening.update(_parse_proc_net_tcp(proc_file))

        if not all_listening:
            # /proc unavailable or nothing listening — nothing to report
            return []

        unexpected = sorted(all_listening - _ALLOWED_LISTEN_PORTS)
        if not unexpected:
            return []

        findings: List[Dict[str, Any]] = []
        for port in unexpected:
            findings.append({
                "type": "unexpected_listen_port",
                "pattern": "unexpected_listen_port",
                "severity": _severity_for_port(port),
                "asset": f"localhost:{port}",
                "description": (
                    f"Port {port} is in LISTEN state but is not in the allowlist of "
                    f"expected service ports. This may indicate a rogue or misconfigured "
                    f"process binding to an unexpected interface."
                ),
                "anomalous": True,
                "evidence": [{"port": port, "state": "LISTEN", "source": "/proc/net/tcp"}],
                "scan_type": "proc_network_scan",
            })

        return findings


def _severity_for_port(port: int) -> str:
    """
    Heuristic severity based on port range:
      - Well-known (< 1024): high — unexpected privileged binding
      - Registered (1024–49151): medium
      - Dynamic / ephemeral (>= 49152): low
    """
    if port < 1024:
        return "high"
    if port < 49152:
        return "medium"
    return "low"


# ── Backward-compatible module-level API ─────────────────────────────────────
def collect() -> List[Dict[str, Any]]:
    """Module-level shim — wraps ProcNetworkCollector for backward compatibility."""
    return ProcNetworkCollector().collect()
