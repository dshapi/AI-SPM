"""Unit tests for FindingsService — all HTTP calls are mocked."""
import pytest
from unittest.mock import MagicMock, patch
from service.findings_service import FindingsService


def _minimal_finding() -> dict:
    return {
        "finding_id": "fid1",
        "timestamp": "2026-04-12T00:00:00+00:00",
        "severity": "high",
        "confidence": 0.8,
        "risk_score": 0.9,
        "title": "Test Finding",
        "hypothesis": "H",
        "evidence": ["ev1"],
        "correlated_events": [],
        "triggered_policies": [],
        "policy_signals": [],
        "recommended_actions": ["block"],
        "should_open_case": True,
    }


class TestFindingsService:
    def _svc(self):
        return FindingsService(
            orchestrator_url="http://orchestrator:8094",
            dev_token_url="http://api:8080/dev-token",
        )

    def test_persist_finding_calls_orchestrator(self):
        svc = self._svc()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"id": "fid1", "deduplicated": False}
        mock_resp.raise_for_status = MagicMock()
        with patch.object(svc._client, "get") as mock_get, \
             patch.object(svc._client, "post") as mock_post:
            mock_get.return_value = MagicMock(
                raise_for_status=MagicMock(),
                json=MagicMock(return_value={"token": "tok"}),
            )
            mock_post.return_value = mock_resp
            result = svc.persist_finding(_minimal_finding(), "t1")
        assert result["id"] == "fid1"
        mock_post.assert_called_once()

    def test_persist_finding_returns_fallback_on_http_error(self):
        svc = self._svc()
        with patch.object(svc._client, "get") as mock_get, \
             patch.object(svc._client, "post") as mock_post:
            mock_get.return_value = MagicMock(
                raise_for_status=MagicMock(),
                json=MagicMock(return_value={"token": "tok"}),
            )
            mock_post.side_effect = Exception("connection refused")
            result = svc.persist_finding(_minimal_finding(), "t1")
        assert "error" in result

    def test_persist_finding_sends_should_open_case(self):
        svc = self._svc()
        captured = {}
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"id": "x", "deduplicated": False}
        mock_resp.raise_for_status = MagicMock()
        def capture_post(url, json=None, headers=None):
            captured["payload"] = json
            return mock_resp
        with patch.object(svc._client, "get") as mock_get, \
             patch.object(svc._client, "post", side_effect=capture_post):
            mock_get.return_value = MagicMock(
                raise_for_status=MagicMock(),
                json=MagicMock(return_value={"token": "tok"}),
            )
            svc.persist_finding(_minimal_finding(), "t1")
        assert captured["payload"]["should_open_case"] is True

    def test_persist_many_calls_persist_for_each(self):
        svc = self._svc()
        findings = [_minimal_finding(), {**_minimal_finding(), "finding_id": "fid2"}]
        with patch.object(svc, "persist_finding", return_value={"id": "x"}) as mock_p:
            results = svc.persist_many(findings, "t1")
        assert mock_p.call_count == 2
        assert len(results) == 2

    def test_link_case_posts_to_correct_url(self):
        svc = self._svc()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {}
        with patch.object(svc._client, "get") as mock_get, \
             patch.object(svc._client, "patch") as mock_patch:
            mock_get.return_value = MagicMock(
                raise_for_status=MagicMock(),
                json=MagicMock(return_value={"token": "tok"}),
            )
            mock_patch.return_value = mock_resp
            svc.link_case("fid1", "case-x")
        mock_patch.assert_called_once()
        url = mock_patch.call_args[0][0]
        assert "fid1" in url

    def test_persist_finding_passes_source_through(self):
        """source in finding_dict must reach the POST payload unchanged."""
        svc = self._svc()
        captured = {}

        def fake_post(url, json=None, headers=None, **kwargs):
            captured["payload"] = json
            resp = MagicMock()
            resp.raise_for_status = lambda: None
            resp.json.return_value = {"id": "x", "deduplicated": False}
            return resp

        def fake_get(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = lambda: None
            resp.json.return_value = {"token": "tok", "expires_in": 3600}
            return resp

        with patch.object(svc._client, "post", side_effect=fake_post), \
             patch.object(svc._client, "get", side_effect=fake_get):
            svc.persist_finding(
                {"title": "T", "severity": "low", "source": "threathunting_ai"},
                "t1",
            )

        assert captured["payload"]["source"] == "threathunting_ai"

    def test_persist_finding_defaults_source_when_missing(self):
        """When source is absent from finding_dict, default to 'threat-hunting-agent'."""
        svc = self._svc()
        captured = {}

        def fake_post(url, json=None, headers=None, **kwargs):
            captured["payload"] = json
            resp = MagicMock()
            resp.raise_for_status = lambda: None
            resp.json.return_value = {"id": "x", "deduplicated": False}
            return resp

        def fake_get(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = lambda: None
            resp.json.return_value = {"token": "tok", "expires_in": 3600}
            return resp

        with patch.object(svc._client, "post", side_effect=fake_post), \
             patch.object(svc._client, "get", side_effect=fake_get):
            svc.persist_finding({"title": "T", "severity": "low"}, "t1")

        assert captured["payload"]["source"] == "threat-hunting-agent"
