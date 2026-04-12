"""
tests/test_mitre_tool.py
"""
from __future__ import annotations
import json
import pytest

from tools.mitre_tool import lookup_mitre_technique, search_mitre_techniques


class TestLookupMitreTechnique:
    def test_known_attck_technique(self):
        result = json.loads(lookup_mitre_technique("T1059"))
        assert result["name"] == "Command and Scripting Interpreter"
        assert result["tactic"] == "Execution"

    def test_atlas_technique(self):
        result = json.loads(lookup_mitre_technique("AML.T0051"))
        assert "Prompt Injection" in result["name"]
        assert "prompt injection" in [k.lower() for k in result["keywords"]]

    def test_case_insensitive(self):
        result = json.loads(lookup_mitre_technique("t1059"))
        assert "error" not in result

    def test_unknown_technique_returns_error(self):
        result = json.loads(lookup_mitre_technique("T9999"))
        assert "error" in result
        assert "available_count" in result

    def test_subtechnique(self):
        result = json.loads(lookup_mitre_technique("T1059.001"))
        assert "PowerShell" in result["name"]


class TestSearchMitreTechniques:
    def test_prompt_injection_search(self):
        result = json.loads(search_mitre_techniques("prompt injection"))
        hits = result["results"]
        assert len(hits) > 0
        ids = [h["id"] for h in hits]
        assert "AML.T0051" in ids

    def test_jailbreak_search(self):
        result = json.loads(search_mitre_techniques("jailbreak"))
        hits = result["results"]
        ids = [h["id"] for h in hits]
        assert "AML.T0054" in ids

    def test_no_matches_returns_empty(self):
        result = json.loads(search_mitre_techniques("zzz_no_match_xyz"))
        assert result["results"] == []
        assert result["total_matches"] == 0

    def test_max_results_respected(self):
        result = json.loads(search_mitre_techniques("data", max_results=2))
        assert len(result["results"]) <= 2

    def test_results_include_required_fields(self):
        result = json.loads(search_mitre_techniques("exfiltration"))
        for r in result["results"]:
            assert "id" in r
            assert "name" in r
            assert "tactic" in r
            assert "description" in r
