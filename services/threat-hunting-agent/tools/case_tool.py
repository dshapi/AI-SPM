"""
tools/case_tool.py
───────────────────
LangChain-compatible tools for case management in the orchestrator.

create_case  — POST /api/v1/cases/hunt  (direct, no real session needed)

An httpx-based HTTP client is used; in tests the module-level
`_http_client` is patched with a fake.
"""
from __future__ import annotations

import json
import logging
from typing import Any, List, Optional

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


# ---------------------------------------------------------------------------
# Tool: create_case
# ---------------------------------------------------------------------------

def create_case(
    title: str,
    severity: str,
    description: str,
    reason: str = "",
    tenant_id: str = "default",
    ttps: Optional[List[str]] = None,
) -> str:
    """
    Create a case directly in the orchestrator (no real session required).

    Fetches a dev-token automatically, then POSTs to /api/v1/cases/hunt.
    The case appears immediately in the Cases tab with the exact title and
    description provided — no generic placeholder text.

    Args:
        title:       Short descriptive title shown as the case heading.
        severity:    One of 'low', 'medium', 'high', 'critical'.
        description: Full narrative description of the threat.
        reason:      Brief tag shown under the case ID (e.g. 'prompt-injection').
        tenant_id:   Tenant to scope the case to.
        ttps:        Optional MITRE ATT&CK / ATLAS technique IDs.

    Returns:
        JSON with keys: case_id, summary, severity, status, created_at.
    """
    if severity not in ("low", "medium", "high", "critical"):
        return json.dumps({"error": f"Invalid severity '{severity}'. Must be low/medium/high/critical."})

    try:
        token = _fetch_dev_token()
    except Exception as exc:
        logger.exception("Failed to fetch dev-token: %s", exc)
        return json.dumps({"error": f"auth failure: {exc}"})

    payload = {
        "title": title,
        "severity": severity,
        "description": description,
        "reason": reason,
        "tenant_id": tenant_id,
        "ttps": ttps or [],
    }

    try:
        client = _get_client()
        resp = client.post(
            f"{_orchestrator_url}/api/v1/cases/hunt",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        return json.dumps(resp.json())
    except httpx.HTTPStatusError as exc:
        logger.error("create_case HTTP %d: %s", exc.response.status_code, exc.response.text)
        return json.dumps({"error": f"HTTP {exc.response.status_code}: {exc.response.text}"})
    except Exception as exc:
        logger.exception("create_case failed: %s", exc)
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# Deduplication helper
# ---------------------------------------------------------------------------

def _compute_batch_hash(tenant_id: str, title: str, evidence: dict) -> str:
    """
    Deterministic SHA-256 hash used for server-side deduplication.

    Inputs are sorted before serialisation so key order doesn't affect output.
    """
    import hashlib
    canonical = json.dumps(
        {"tenant_id": tenant_id, "title": title, "evidence": evidence},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Tool: create_threat_finding  (structured, deduplicated)
# ---------------------------------------------------------------------------

def create_threat_finding(
    tenant_id: str,
    title: str,
    severity: str,
    description: str,
    evidence: dict,
    ttps: Optional[List[str]] = None,
) -> str:
    """
    Submit a structured threat finding to the orchestrator.

    POSTs to /api/v1/threat-findings.  The server handles deduplication via
    batch_hash: a 200 response means the finding already exists (deduplicated=True);
    a 201 means it was newly created (deduplicated=False).

    Args:
        tenant_id:   Tenant scope.
        title:       Short descriptive title.
        severity:    One of 'low', 'medium', 'high', 'critical'.
        description: Narrative explanation from the agent.
        evidence:    Dict of supporting evidence facts.
        ttps:        Optional MITRE ATT&CK / ATLAS technique IDs.

    Returns:
        JSON string with keys: id, title, severity, status, created_at, deduplicated.
    """
    if severity not in ("low", "medium", "high", "critical"):
        return json.dumps({"error": f"Invalid severity '{severity}'. Must be low/medium/high/critical."})

    try:
        token = _fetch_dev_token()
    except Exception as exc:
        logger.exception("create_threat_finding: dev-token fetch failed: %s", exc)
        return json.dumps({"error": f"auth failure: {exc}"})

    batch_hash = _compute_batch_hash(tenant_id, title, evidence)
    payload = {
        "title":       title,
        "severity":    severity,
        "description": description,
        "evidence":    evidence,
        "tenant_id":   tenant_id,
        "ttps":        ttps or [],
        "batch_hash":  batch_hash,
    }

    try:
        client = _get_client()
        resp = client.post(
            f"{_orchestrator_url}/api/v1/threat-findings",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        return json.dumps(resp.json())
    except httpx.HTTPStatusError as exc:
        logger.error(
            "create_threat_finding HTTP %d: %s",
            exc.response.status_code, exc.response.text,
        )
        return json.dumps({"error": f"HTTP {exc.response.status_code}: {exc.response.text}"})
    except Exception as exc:
        logger.exception("create_threat_finding failed: %s", exc)
        return json.dumps({"error": str(exc)})
