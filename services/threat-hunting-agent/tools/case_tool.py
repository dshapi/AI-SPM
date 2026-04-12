"""
tools/case_tool.py
───────────────────
LangChain-compatible tool for creating threat findings in the orchestrator.

Flow:
  1. Fetch a short-lived dev-token from {PLATFORM_API_URL}/dev-token.
  2. POST the finding to {ORCHESTRATOR_URL}/api/v1/threat-findings.
  3. Return the finding ID (or existing ID if deduplicated).

batch_hash deduplication:
  The agent computes a stable SHA-256 of the sorted (tenant_id, title, evidence)
  dict to avoid creating duplicate findings for the same burst of events.

An httpx-based HTTP client is used; in tests the module-level
`_http_client` is patched with a fake.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Runtime config — set at startup via configure()
# ---------------------------------------------------------------------------

_platform_api_url: str = "http://api:8080"
_orchestrator_url: str = "http://agent-orchestrator:8094"
_timeout: float = 10.0
_http_client: Optional[httpx.Client] = None  # injected in tests


def configure(platform_api_url: str, orchestrator_url: str, timeout: float = 10.0) -> None:
    """Set target URLs at service startup."""
    global _platform_api_url, _orchestrator_url, _timeout
    _platform_api_url = platform_api_url
    _orchestrator_url = orchestrator_url
    _timeout = timeout


def set_http_client(client: Any) -> None:
    """Inject a mock httpx.Client for tests."""
    global _http_client
    _http_client = client


def _get_client() -> httpx.Client:
    if _http_client is not None:
        return _http_client
    return httpx.Client(timeout=_timeout)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_dev_token() -> str:
    """Retrieve a short-lived admin JWT from the platform API."""
    client = _get_client()
    resp = client.get(f"{_platform_api_url}/dev-token")
    resp.raise_for_status()
    data = resp.json()
    token = data.get("token") or data.get("access_token")
    if not token:
        raise ValueError(f"dev-token endpoint returned unexpected shape: {list(data.keys())}")
    return token


def _compute_batch_hash(tenant_id: str, title: str, evidence: Dict[str, Any]) -> str:
    """Stable SHA-256 of the key finding fields to enable deduplication."""
    payload = json.dumps(
        {"tenant_id": tenant_id, "title": title, "evidence": evidence},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Tool: create_threat_finding
# ---------------------------------------------------------------------------

def create_threat_finding(
    tenant_id: str,
    title: str,
    severity: str,
    description: str,
    evidence: Dict[str, Any],
    ttps: Optional[List[str]] = None,
) -> str:
    """
    Create a threat finding in the orchestrator service.

    Fetches a dev-token automatically, then POSTs to /api/v1/threat-findings.
    If an identical finding already exists (same batch_hash), the existing
    record is returned with deduplicated=true.

    Args:
        tenant_id: Tenant to scope the finding to.
        title: Short descriptive title (max ~100 chars).
        severity: One of 'low', 'medium', 'high', 'critical'.
        description: Detailed human-readable description of the threat.
        evidence: Dict of supporting evidence (log excerpts, metric values, etc.).
        ttps: Optional list of MITRE ATT&CK / ATLAS technique IDs (e.g. ['AML.T0051']).

    Returns:
        JSON with keys: id, title, severity, status, created_at, deduplicated.
    """
    if severity not in ("low", "medium", "high", "critical"):
        return json.dumps({"error": f"Invalid severity '{severity}'. Must be low/medium/high/critical."})

    ttps = ttps or []
    batch_hash = _compute_batch_hash(tenant_id, title, evidence)

    try:
        token = _fetch_dev_token()
    except Exception as exc:
        logger.exception("Failed to fetch dev-token: %s", exc)
        return json.dumps({"error": f"auth failure: {exc}"})

    payload = {
        "title": title,
        "severity": severity,
        "description": description,
        "evidence": evidence,
        "ttps": ttps,
        "tenant_id": tenant_id,
        "batch_hash": batch_hash,
    }

    try:
        client = _get_client()
        resp = client.post(
            f"{_orchestrator_url}/api/v1/threat-findings",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        data = resp.json()
        return json.dumps(data)
    except httpx.HTTPStatusError as exc:
        logger.error("create_threat_finding HTTP %d: %s", exc.response.status_code, exc.response.text)
        return json.dumps({"error": f"HTTP {exc.response.status_code}: {exc.response.text}"})
    except Exception as exc:
        logger.exception("create_threat_finding failed: %s", exc)
        return json.dumps({"error": str(exc)})
