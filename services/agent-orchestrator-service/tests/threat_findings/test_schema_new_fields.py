# tests/threat_findings/test_schema_new_fields.py
from threat_findings.schemas import FindingRecord, FindingFilter, FindingResponse
import dataclasses

def test_finding_record_has_prioritization_fields():
    fields = {f.name for f in dataclasses.fields(FindingRecord)}
    for name in ("dedup_key", "occurrence_count", "first_seen", "last_seen",
                 "group_id", "group_size", "priority_score", "suppressed"):
        assert name in fields, f"FindingRecord missing field: {name}"

def test_finding_filter_has_include_suppressed():
    f = FindingFilter()
    assert hasattr(f, "include_suppressed")
    assert f.include_suppressed is False  # default hides suppressed

def test_finding_response_has_priority_fields():
    hints = FindingResponse.model_fields
    assert "priority_score" in hints
    assert "suppressed" in hints
    assert "occurrence_count" in hints
    assert "group_id" in hints
    assert "group_size" in hints
