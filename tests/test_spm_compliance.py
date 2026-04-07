# tests/test_spm_compliance.py
import json, os

def test_nist_mapping_file_exists():
    path = "spm/compliance/nist_airm_mapping.json"
    assert os.path.exists(path), f"Missing: {path}"

def test_nist_mapping_has_all_four_functions():
    with open("spm/compliance/nist_airm_mapping.json") as f:
        controls = json.load(f)
    functions = {c["function"] for c in controls}
    assert functions == {"GOVERN", "MAP", "MEASURE", "MANAGE"}

def test_nist_mapping_required_fields():
    with open("spm/compliance/nist_airm_mapping.json") as f:
        controls = json.load(f)
    for c in controls:
        assert "framework" in c
        assert "function" in c
        assert "category" in c
        assert "cpm_control" in c
        assert "evaluation_rule" in c

def test_compliance_coverage_calculation():
    """Coverage % calculation logic."""
    controls = [
        {"status": "satisfied"},
        {"status": "satisfied"},
        {"status": "not_satisfied"},
        {"status": "partial"},
    ]
    satisfied = sum(1 for c in controls if c["status"] == "satisfied")
    coverage = satisfied / len(controls) * 100
    assert coverage == 50.0
