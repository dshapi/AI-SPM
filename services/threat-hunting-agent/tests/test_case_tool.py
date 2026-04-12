"""
tests/test_case_tool.py
"""
from __future__ import annotations

import hashlib
import json
from unittest.mock import MagicMock, patch

import pytest

import tools.case_tool as ct
from tools.case_tool import (
    _compute_batch_hash,
    configure,
    create_threat_finding,
    set_http_client,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_client(token_resp: dict, finding_resp: dict, finding_status: int = 201):
    """Return a fake httpx.Client that handles GET /dev-token and POST /threat-findings."""
    client = MagicMock()

    def mock_get(url, **kwargs):
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.json.return_value = token_resp
        return r

    def mock_post(url, **kwargs):
        r = MagicMock()
        r.status_code = finding_status
        r.raise_for_status = MagicMock()
        r.json.return_value = finding_resp
        return r

    client.get.side_effect = mock_get
    client.post.side_effect = mock_post
    return client


# ─────────────────────────────────────────────────────────────────────────────
# _compute_batch_hash
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeBatchHash:
    def test_deterministic(self):
        h1 = _compute_batch_hash("t1", "Injection detected", {"count": 5})
        h2 = _compute_batch_hash("t1", "Injection detected", {"count": 5})
        assert h1 == h2

    def test_different_inputs_different_hash(self):
        h1 = _compute_batch_hash("t1", "A", {})
        h2 = _compute_batch_hash("t1", "B", {})
        assert h1 != h2

    def test_is_sha256_length(self):
        h = _compute_batch_hash("t1", "title", {})
        assert len(h) == 64

    def test_evidence_order_insensitive(self):
        h1 = _compute_batch_hash("t1", "T", {"b": 2, "a": 1})
        h2 = _compute_batch_hash("t1", "T", {"a": 1, "b": 2})
        assert h1 == h2


# ─────────────────────────────────────────────────────────────────────────────
# create_threat_finding
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateThreatFinding:
    def setup_method(self):
        configure("http://api:8080", "http://orchestrator:8094")

    def test_creates_new_finding(self):
        finding = {"id": "f1", "title": "T", "severity": "high",
                   "status": "open", "created_at": "2024-01-01T00:00:00Z",
                   "deduplicated": False}
        set_http_client(_make_client({"token": "tok123"}, finding, 201))

        result = json.loads(create_threat_finding(
            tenant_id="t1", title="T", severity="high",
            description="D", evidence={"ip": "1.2.3.4"},
        ))
        assert result["id"] == "f1"
        assert result["deduplicated"] is False

    def test_deduplication_returns_existing(self):
        finding = {"id": "f-old", "deduplicated": True, "severity": "high",
                   "title": "T", "status": "open", "created_at": "2024-01-01T00:00:00Z"}
        set_http_client(_make_client({"token": "tok"}, finding, 200))

        result = json.loads(create_threat_finding(
            tenant_id="t1", title="T", severity="high",
            description="D", evidence={},
        ))
        assert result["deduplicated"] is True
        assert result["id"] == "f-old"

    def test_invalid_severity_returns_error(self):
        set_http_client(MagicMock())
        result = json.loads(create_threat_finding(
            tenant_id="t1", title="T", severity="extreme",
            description="D", evidence={},
        ))
        assert "error" in result
        assert "severity" in result["error"]

    def test_ttps_sent_in_payload(self):
        finding = {"id": "f1", "deduplicated": False, "severity": "critical",
                   "title": "T", "status": "open", "created_at": "2024-01-01"}
        fake_client = _make_client({"token": "tok"}, finding, 201)
        set_http_client(fake_client)

        create_threat_finding(
            tenant_id="t1", title="T", severity="critical",
            description="D", evidence={},
            ttps=["AML.T0051", "T1059"],
        )
        call_kwargs = fake_client.post.call_args[1]
        assert "AML.T0051" in call_kwargs["json"]["ttps"]

    def test_auth_header_sent(self):
        finding = {"id": "f1", "deduplicated": False, "severity": "low",
                   "title": "T", "status": "open", "created_at": "2024-01-01"}
        fake_client = _make_client({"token": "mytoken"}, finding, 201)
        set_http_client(fake_client)

        create_threat_finding("t1", "T", "low", "D", {})
        call_kwargs = fake_client.post.call_args[1]
        assert call_kwargs["headers"]["Authorization"] == "Bearer mytoken"

    def test_token_fetch_failure_returns_error(self):
        client = MagicMock()
        client.get.side_effect = Exception("connection refused")
        set_http_client(client)

        result = json.loads(create_threat_finding("t1", "T", "low", "D", {}))
        assert "error" in result
        assert "auth failure" in result["error"]

    def test_http_error_from_orchestrator_returns_error(self):
        import httpx
        # Token fetch succeeds, POST raises HTTPStatusError
        fake_client = MagicMock()

        tok_resp = MagicMock()
        tok_resp.raise_for_status = MagicMock()
        tok_resp.json.return_value = {"token": "tok"}
        fake_client.get.return_value = tok_resp

        err_resp = MagicMock()
        err_resp.status_code = 422
        err_resp.text = "validation error"
        fake_client.post.side_effect = httpx.HTTPStatusError(
            "422", request=MagicMock(), response=err_resp
        )
        set_http_client(fake_client)

        result = json.loads(create_threat_finding("t1", "T", "low", "D", {}))
        assert "error" in result
        assert "422" in result["error"]

    def test_batch_hash_included_in_post_payload(self):
        finding = {"id": "f1", "deduplicated": False, "severity": "medium",
                   "title": "T", "status": "open", "created_at": "2024-01-01"}
        fake_client = _make_client({"token": "tok"}, finding, 201)
        set_http_client(fake_client)

        evidence = {"signal": "high_drift"}
        create_threat_finding("t1", "Title", "medium", "Desc", evidence)

        expected_hash = _compute_batch_hash("t1", "Title", evidence)
        call_kwargs = fake_client.post.call_args[1]
        assert call_kwargs["json"]["batch_hash"] == expected_hash

    def test_create_threat_finding_sends_new_fields(self):
        """Test that new optional Finding fields are forwarded in the payload."""
        finding = {"id": "fid1", "deduplicated": False, "severity": "high",
                   "title": "Test", "status": "open", "created_at": "2024-01-01"}
        fake_client = _make_client({"token": "tok"}, finding, 201)
        set_http_client(fake_client)

        result = create_threat_finding(
            tenant_id="t1",
            title="Test",
            severity="high",
            description="desc",
            evidence={"key": "value"},
            ttps=["T1234"],
            confidence=0.8,
            risk_score=0.9,
            hypothesis="H",
            recommended_actions=["block"],
            should_open_case=True,
        )
        # Extract the payload that was POSTed
        call_kwargs = fake_client.post.call_args[1]
        payload = call_kwargs["json"]

        assert payload["confidence"] == 0.8
        assert payload["risk_score"] == 0.9
        assert payload["should_open_case"] is True
        assert payload["recommended_actions"] == ["block"]
        assert payload["hypothesis"] == "H"
        assert json.loads(result)["deduplicated"] is False
