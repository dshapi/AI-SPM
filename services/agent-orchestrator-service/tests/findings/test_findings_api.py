import pytest
from tests.findings.conftest import _make_record


# ── GET /api/v1/findings ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_findings_empty(client):
    """Empty DB returns items=[], total=0."""
    client._app._mock_svc.list_findings.return_value = []
    client._app._mock_svc.count_findings.return_value = 0

    resp = await client.get("/api/v1/findings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["limit"] == 50
    assert data["offset"] == 0


@pytest.mark.asyncio
async def test_list_findings_returns_items(client):
    """Returns paginated list with correct total."""
    recs = [_make_record(f"f-{i}") for i in range(3)]
    client._app._mock_svc.list_findings.return_value = recs
    client._app._mock_svc.count_findings.return_value = 10  # more exist beyond limit

    resp = await client.get("/api/v1/findings?limit=3&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 3
    assert data["total"] == 10
    assert data["limit"] == 3


@pytest.mark.asyncio
async def test_list_findings_passes_filters_to_service(client):
    """Query params are forwarded to the service as a FindingFilter."""
    client._app._mock_svc.list_findings.return_value = []
    client._app._mock_svc.count_findings.return_value = 0

    await client.get("/api/v1/findings?severity=high&status=open&min_risk_score=0.7")

    call_args = client._app._mock_svc.list_findings.call_args
    filters = call_args[0][0]   # first positional arg
    assert filters.severity == "high"
    assert filters.status == "open"
    assert filters.min_risk_score == 0.7


# ── GET /api/v1/findings/{id} ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_finding_returns_full_detail(client):
    """Returns all fields including evidence, ttps, hypothesis."""
    rec = _make_record("f-detail")
    client._app._mock_svc.get_finding_by_id.return_value = rec

    resp = await client.get("/api/v1/findings/f-detail")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "f-detail"
    assert data["evidence"] == ["log line 1"]
    assert data["ttps"] == ["T1059"]
    assert data["tenant_id"] == "acme"
    assert data["batch_hash"] == "bh-f-detail"


@pytest.mark.asyncio
async def test_get_finding_not_found_returns_404(client):
    """Missing finding_id returns 404 with FINDING_NOT_FOUND code."""
    client._app._mock_svc.get_finding_by_id.return_value = None

    resp = await client.get("/api/v1/findings/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "FINDING_NOT_FOUND"


# ── PATCH /api/v1/findings/{id}/status ───────────────────────────────────────

@pytest.mark.asyncio
async def test_patch_status_returns_updated_finding(client):
    """Status update returns the finding with new status."""
    rec = _make_record("f-patch", status="open")
    updated = _make_record("f-patch", status="investigating")
    # get_finding_by_id: first call (existence check) returns original,
    # second call (re-fetch) returns updated
    client._app._mock_svc.get_finding_by_id.side_effect = [rec, updated]

    resp = await client.patch(
        "/api/v1/findings/f-patch/status",
        json={"status": "investigating"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "investigating"


@pytest.mark.asyncio
async def test_patch_status_invalid_value_returns_422(client):
    """A status value not matching the pattern returns 422 from Pydantic."""
    resp = await client.patch(
        "/api/v1/findings/f-any/status",
        json={"status": "unknown"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_status_not_found_returns_404(client):
    client._app._mock_svc.get_finding_by_id.return_value = None
    resp = await client.patch(
        "/api/v1/findings/missing/status",
        json={"status": "resolved"},
    )
    assert resp.status_code == 404


# ── POST /api/v1/findings/{id}/link-case ─────────────────────────────────────

@pytest.mark.asyncio
async def test_link_case_returns_updated_finding(client):
    rec = _make_record("f-link", case_id=None)
    updated = _make_record("f-link", case_id="case-xyz")
    client._app._mock_svc.get_finding_by_id.side_effect = [rec, updated]

    resp = await client.post(
        "/api/v1/findings/f-link/link-case",
        json={"case_id": "case-xyz"},
    )
    assert resp.status_code == 200
    assert resp.json()["case_id"] == "case-xyz"


# ── POST /api/v1/findings/query ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_query_with_body_filters(client):
    """POST /query with body filters returns paginated list."""
    recs = [_make_record("q-1", severity="critical")]
    client._app._mock_svc.list_findings.return_value = recs
    client._app._mock_svc.count_findings.return_value = 1

    resp = await client.post("/api/v1/findings/query", json={
        "severity": "critical",
        "limit": 10,
        "offset": 0,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["severity"] == "critical"
