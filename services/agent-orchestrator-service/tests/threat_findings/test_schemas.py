from threat_findings.schemas import FindingRecord, CreateFindingRequest, FindingFilter


def test_finding_record_new_fields():
    rec = FindingRecord(id="x", batch_hash="h", title="T", severity="high",
                        description="d", evidence=[], ttps=[], tenant_id="t1")
    assert rec.confidence is None
    assert rec.risk_score is None
    assert rec.hypothesis is None
    assert rec.should_open_case is False
    assert rec.status == "open"


def test_create_finding_request_accepts_new_fields():
    req = CreateFindingRequest(
        title="T", severity="high", description="d", tenant_id="t1",
        batch_hash="h", confidence=0.8, risk_score=0.9,
        hypothesis="H", evidence=[], recommended_actions=["block"],
    )
    assert req.confidence == 0.8


def test_finding_filter_defaults():
    f = FindingFilter()
    assert f.severity is None
    assert f.limit == 50
