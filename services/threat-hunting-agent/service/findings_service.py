"""
service/findings_service.py
────────────────────────────
HTTP client that persists every Finding dict to the orchestrator's
/api/v1/threat-findings endpoint.

Uses a synchronous httpx.Client (thread-safe; one instance per app).
Case linkage and status updates are sent via PATCH calls to the same service.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class FindingsService:
    """Stateless singleton; one instance on app.state."""

    def __init__(
        self,
        orchestrator_url: str = "http://agent-orchestrator:8094",
        dev_token_url: str = "http://api:8080/dev-token",
        timeout: float = 10.0,
    ) -> None:
        self._orchestrator_url = orchestrator_url.rstrip("/")
        self._dev_token_url = dev_token_url
        self._client = httpx.Client(timeout=timeout, trust_env=False)

    def _fetch_token(self) -> str:
        resp = self._client.get(self._dev_token_url)
        resp.raise_for_status()
        data = resp.json()
        token = data.get("token") or data.get("access_token")
        if not token:
            raise ValueError(f"dev-token endpoint returned: {list(data.keys())}")
        return token

    def persist_finding(self, finding_dict: Dict[str, Any], tenant_id: str) -> dict:
        """
        POST finding_dict to /api/v1/threat-findings.
        Returns the response JSON dict, or {"error": ...} on failure.
        Never raises.
        """
        try:
            token = self._fetch_token()
        except Exception as exc:
            logger.warning("FindingsService: token fetch failed: %s", exc)
            return {"error": f"auth: {exc}"}

        evidence = finding_dict.get("evidence", [])
        title = finding_dict.get("title", "")
        canonical = json.dumps(
            {"tenant_id": tenant_id, "title": title, "evidence": evidence},
            sort_keys=True, default=str,
        )
        batch_hash = hashlib.sha256(canonical.encode()).hexdigest()

        payload = {
            "title": title,
            "severity": finding_dict.get("severity", "low"),
            "description": finding_dict.get("hypothesis", ""),
            "evidence": evidence,
            "ttps": finding_dict.get("triggered_policies", []),
            "tenant_id": tenant_id,
            "batch_hash": batch_hash,
            # Full Finding fields
            "timestamp": finding_dict.get("timestamp"),
            "confidence": finding_dict.get("confidence"),
            "risk_score": finding_dict.get("risk_score"),
            "hypothesis": finding_dict.get("hypothesis"),
            "asset": finding_dict.get("asset"),
            "environment": finding_dict.get("environment"),
            "correlated_events": finding_dict.get("correlated_events"),
            "correlated_findings": finding_dict.get("correlated_findings"),
            "triggered_policies": finding_dict.get("triggered_policies"),
            "policy_signals": finding_dict.get("policy_signals"),
            "recommended_actions": finding_dict.get("recommended_actions"),
            "should_open_case": bool(finding_dict.get("should_open_case", False)),
            "source": finding_dict.get("source", "threat-hunting-agent"),
        }
        # Remove None values
        payload = {k: v for k, v in payload.items() if v is not None}

        try:
            resp = self._client.post(
                f"{self._orchestrator_url}/api/v1/threat-findings",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info(
                "FindingsService: persisted id=%s deduplicated=%s",
                data.get("id"), data.get("deduplicated"),
            )
            return data
        except Exception as exc:
            logger.exception("FindingsService.persist_finding failed: %s", exc)
            return {"error": str(exc)}

    def persist_many(
        self, findings: List[Dict[str, Any]], tenant_id: str
    ) -> List[dict]:
        """Persist a list of findings; continues on individual errors."""
        return [self.persist_finding(f, tenant_id) for f in findings]

    def link_case(self, finding_id: str, case_id: str) -> dict:
        """PATCH /api/v1/threat-findings/{finding_id}/case."""
        try:
            token = self._fetch_token()
            resp = self._client.patch(
                f"{self._orchestrator_url}/api/v1/threat-findings/{finding_id}/case",
                json={"case_id": case_id},
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.exception("FindingsService.link_case failed: %s", exc)
            return {"error": str(exc)}

    def mark_status(self, finding_id: str, new_status: str) -> dict:
        """PATCH /api/v1/threat-findings/{finding_id}/status."""
        try:
            token = self._fetch_token()
            resp = self._client.patch(
                f"{self._orchestrator_url}/api/v1/threat-findings/{finding_id}/status",
                json={"status": new_status},
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.exception("FindingsService.mark_status failed: %s", exc)
            return {"error": str(exc)}
