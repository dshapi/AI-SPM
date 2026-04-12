"""
tests/test_opa_tool.py
"""
from __future__ import annotations
import json
from unittest.mock import MagicMock
import pytest

import tools.opa_tool as opa_mod
from tools.opa_tool import evaluate_opa_policy, set_opa_client


class TestEvaluateOpaPolicy:
    def test_returns_policy_result(self):
        fake_client = MagicMock()
        fake_client.eval.return_value = {"decision": "allow"}
        set_opa_client(fake_client)

        result = json.loads(evaluate_opa_policy(
            "/v1/data/spm/authz/decision",
            {"user": "alice", "action": "read"},
        ))
        assert result["result"]["decision"] == "allow"
        assert result["policy_path"] == "/v1/data/spm/authz/decision"

    def test_passes_input_to_client(self):
        fake_client = MagicMock()
        fake_client.eval.return_value = {}
        set_opa_client(fake_client)

        input_data = {"tenant_id": "t1", "posture_score": 0.9}
        evaluate_opa_policy("/v1/data/spm/posture/risk_level", input_data)
        fake_client.eval.assert_called_once_with(
            "/v1/data/spm/posture/risk_level", input_data
        )

    def test_error_returns_json(self):
        fake_client = MagicMock()
        fake_client.eval.side_effect = Exception("opa down")
        set_opa_client(fake_client)

        result = json.loads(evaluate_opa_policy("/v1/data/test", {}))
        assert "error" in result

    def test_raises_if_client_not_set(self):
        opa_mod._opa_client = None
        with pytest.raises(RuntimeError, match="not initialised"):
            opa_mod._get_opa()
