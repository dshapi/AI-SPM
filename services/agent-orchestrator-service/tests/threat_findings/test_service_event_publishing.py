"""
tests/threat_findings/test_service_event_publishing.py
────────────────────────────────────────────────────────
Regression tests for EventPublisher integration in ThreatFindingsService.

Verifies:
  1. emit_finding_created is called when a new finding is created via
     create_finding() and persist_finding_from_dict().
  2. emit_finding_status_changed is called when mark_status() runs.
  3. A publisher failure NEVER breaks the finding create / status-change path
     (non-fatal contract).
  4. When no publisher is provided (backwards-compat), everything still works.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from threat_findings.service import ThreatFindingsService
from threat_findings.schemas import CreateFindingRequest


# ── Helpers ───────────────────────────────────────────────────────────────────

@pytest.fixture
def svc():
    return ThreatFindingsService()


def _make_repos():
    """Return (finding_repo, case_repo) with sensible async mocks."""
    finding_repo = AsyncMock()
    finding_repo.get_by_batch_hash.return_value = None
    finding_repo.get_by_dedup_key.return_value = None
    finding_repo.insert.return_value = None
    finding_repo.update_priority_fields.return_value = None
    finding_repo.attach_case.return_value = None
    finding_repo.update_status.return_value = None

    case_repo = AsyncMock()
    case_repo.insert.return_value = None
    return finding_repo, case_repo


def _make_publisher():
    """Return an AsyncMock that mirrors the EventPublisher interface."""
    pub = AsyncMock()
    pub.emit_finding_created = AsyncMock(return_value=MagicMock())
    pub.emit_finding_status_changed = AsyncMock(return_value=MagicMock())
    return pub


def _make_req(**kwargs):
    defaults = dict(
        title="Suspicious exfiltration attempt",
        severity="high",
        description="desc",
        evidence=["e1"],
        ttps=["AML.T0051"],
        tenant_id="t1",
        batch_hash="hash-event-pub-test",
    )
    defaults.update(kwargs)
    return CreateFindingRequest(**defaults)


# ── create_finding ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_finding_emits_finding_created(svc):
    """emit_finding_created must be awaited once when a new finding is created."""
    finding_repo, case_repo = _make_repos()
    pub = _make_publisher()

    req = _make_req()
    result = await svc.create_finding(req, finding_repo, case_repo, publisher=pub)

    # Finding was created
    assert result.title == "Suspicious exfiltration attempt"
    assert result.deduplicated is False

    # Event was emitted
    pub.emit_finding_created.assert_awaited_once()
    call_kwargs = pub.emit_finding_created.call_args.kwargs
    assert call_kwargs["finding_id"] == result.id
    assert call_kwargs["tenant_id"] == "t1"
    assert call_kwargs["severity"] == "high"
    assert call_kwargs["title"] == "Suspicious exfiltration attempt"


@pytest.mark.asyncio
async def test_create_finding_no_event_on_dedup(svc):
    """emit_finding_created must NOT be called for deduplicated findings."""
    finding_repo, case_repo = _make_repos()
    pub = _make_publisher()

    from threat_findings.schemas import FindingRecord
    existing = FindingRecord(
        id="existing-id",
        batch_hash="hash-dup",
        title="Dup",
        severity="low",
        description="",
        evidence=[],
        ttps=[],
        tenant_id="t1",
    )
    existing.deduplicated = True
    finding_repo.get_by_batch_hash.return_value = existing

    req = _make_req(batch_hash="hash-dup", title="Dup")
    result = await svc.create_finding(req, finding_repo, case_repo, publisher=pub)

    assert result.deduplicated is True
    pub.emit_finding_created.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_finding_publisher_failure_is_non_fatal(svc):
    """A publisher exception must never cause create_finding to raise."""
    finding_repo, case_repo = _make_repos()
    pub = _make_publisher()
    pub.emit_finding_created.side_effect = RuntimeError("Kafka broker unavailable")

    req = _make_req(batch_hash="hash-pub-fail")
    # Must not raise — finding is still persisted
    result = await svc.create_finding(req, finding_repo, case_repo, publisher=pub)
    assert result.title == "Suspicious exfiltration attempt"
    finding_repo.insert.assert_called_once()


@pytest.mark.asyncio
async def test_create_finding_without_publisher_still_works(svc):
    """Omitting publisher (None) must not break create_finding (backwards compat)."""
    finding_repo, case_repo = _make_repos()

    req = _make_req(batch_hash="hash-no-pub")
    result = await svc.create_finding(req, finding_repo, case_repo, publisher=None)
    assert result.title == "Suspicious exfiltration attempt"
    finding_repo.insert.assert_called_once()


@pytest.mark.asyncio
async def test_create_finding_case_opened_event_includes_case_id(svc):
    """When a case is auto-opened, case_id must be forwarded to emit_finding_created."""
    finding_repo, case_repo = _make_repos()
    pub = _make_publisher()

    # Force priority high enough to open case
    with patch("threat_findings.service.PrioritizationEngine.run") as mock_run:
        from threat_findings.schemas import FindingRecord
        async def _mock_run(rec, _lookup):
            rec.priority_score = 0.90
            rec.suppressed = False
            return rec
        mock_run.side_effect = _mock_run

        req = _make_req(
            severity="critical",
            batch_hash="hash-case-event",
            should_open_case=True,
        )
        result = await svc.create_finding(req, finding_repo, case_repo, publisher=pub)

    call_kwargs = pub.emit_finding_created.call_args.kwargs
    # If a case was opened, case_id should be included in the event
    if result.case_id:
        assert call_kwargs["case_id"] == result.case_id
        assert call_kwargs["should_open_case"] is True


# ── persist_finding_from_dict ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_persist_finding_from_dict_emits_finding_created(svc):
    """persist_finding_from_dict must emit finding.created via publisher."""
    finding_repo, case_repo = _make_repos()
    pub = _make_publisher()

    finding_dict = {
        "finding_id": "00000000-0000-0000-0000-000000000001",
        "title": "Lateral movement detected",
        "severity": "high",
        "hypothesis": "Attacker may be moving laterally",
        "evidence": ["e1", "e2"],
        "confidence": 0.8,
        "risk_score": 0.75,
        "asset": "prod-server-01",
        "should_open_case": False,
        "triggered_policies": [],
    }
    result = await svc.persist_finding_from_dict(
        finding_dict, "t1", finding_repo, case_repo, publisher=pub
    )

    pub.emit_finding_created.assert_awaited_once()
    call_kwargs = pub.emit_finding_created.call_args.kwargs
    assert call_kwargs["tenant_id"] == "t1"
    assert call_kwargs["severity"] == "high"
    assert call_kwargs["source"] == "threat-hunting-agent"


@pytest.mark.asyncio
async def test_persist_finding_from_dict_publisher_failure_non_fatal(svc):
    """Publisher failure in persist_finding_from_dict must not raise."""
    finding_repo, case_repo = _make_repos()
    pub = _make_publisher()
    pub.emit_finding_created.side_effect = ConnectionError("Kafka down")

    finding_dict = {
        "title": "Test",
        "severity": "low",
        "evidence": [],
        "hypothesis": "",
    }
    # Must not raise
    result = await svc.persist_finding_from_dict(finding_dict, "t1", finding_repo, publisher=pub)
    assert result is not None
    finding_repo.insert.assert_called_once()


# ── mark_status ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mark_status_emits_status_changed(svc):
    """mark_status must emit finding.status_changed via publisher."""
    finding_repo, _ = _make_repos()
    pub = _make_publisher()

    await svc.mark_status(
        "finding-123",
        "investigating",
        finding_repo,
        publisher=pub,
        tenant_id="t1",
        changed_by="analyst@corp.com",
        old_status="open",
    )

    finding_repo.update_status.assert_called_once_with("finding-123", "investigating")
    pub.emit_finding_status_changed.assert_awaited_once()
    call_kwargs = pub.emit_finding_status_changed.call_args.kwargs
    assert call_kwargs["finding_id"] == "finding-123"
    assert call_kwargs["new_status"] == "investigating"
    assert call_kwargs["old_status"] == "open"
    assert call_kwargs["changed_by"] == "analyst@corp.com"
    assert call_kwargs["tenant_id"] == "t1"


@pytest.mark.asyncio
async def test_mark_status_publisher_failure_non_fatal(svc):
    """Publisher failure in mark_status must never prevent the DB update."""
    finding_repo, _ = _make_repos()
    pub = _make_publisher()
    pub.emit_finding_status_changed.side_effect = RuntimeError("oops")

    # Must not raise
    await svc.mark_status("finding-456", "resolved", finding_repo, publisher=pub)
    finding_repo.update_status.assert_called_once_with("finding-456", "resolved")


@pytest.mark.asyncio
async def test_mark_status_without_publisher_still_works(svc):
    """mark_status must work when no publisher is provided (backwards compat)."""
    finding_repo, _ = _make_repos()

    await svc.mark_status("finding-789", "resolved", finding_repo)
    finding_repo.update_status.assert_called_once_with("finding-789", "resolved")


# ── EventPublisher unit tests ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_event_publisher_emit_finding_created():
    """emit_finding_created should store event and publish to Kafka topic."""
    from events.publisher import EventPublisher, TOPIC_FINDING_CREATED
    from events.store import EventStore

    store = EventStore(max_events_per_session=100)
    publisher = EventPublisher(bootstrap_servers="localhost:9092", store=store)
    # Don't actually connect Kafka — it will fall back to log mode
    publisher._available = False

    event = await publisher.emit_finding_created(
        finding_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        tenant_id="t1",
        severity="critical",
        title="Critical exfiltration",
        risk_score=0.95,
        confidence=0.9,
        asset="prod-db",
        source="threat-hunting-agent",
        priority_score=0.88,
        should_open_case=True,
        case_id="case-xyz",
    )

    from schemas.events import EventType
    assert event.event_type == EventType.FINDING_CREATED
    assert event.status == "created"
    assert "critical exfiltration" in event.summary.lower()
    assert "case auto-opened" in event.summary.lower()
    assert event.payload["finding_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert event.payload["severity"] == "critical"
    assert event.payload["case_id"] == "case-xyz"


@pytest.mark.asyncio
async def test_event_publisher_emit_finding_status_changed():
    """emit_finding_status_changed should store event with correct fields."""
    from events.publisher import EventPublisher
    from events.store import EventStore

    store = EventStore(max_events_per_session=100)
    publisher = EventPublisher(bootstrap_servers="localhost:9092", store=store)
    publisher._available = False

    event = await publisher.emit_finding_status_changed(
        finding_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        tenant_id="t1",
        new_status="resolved",
        old_status="investigating",
        changed_by="sec-analyst",
    )

    from schemas.events import EventType
    assert event.event_type == EventType.FINDING_STATUS_CHANGED
    assert event.status == "resolved"
    assert event.payload["new_status"] == "resolved"
    assert event.payload["old_status"] == "investigating"
    assert event.payload["changed_by"] == "sec-analyst"


@pytest.mark.asyncio
async def test_event_publisher_finding_created_topic_env_override(monkeypatch):
    """KAFKA_TOPIC_FINDING_CREATED env var should override the default topic."""
    import importlib
    monkeypatch.setenv("KAFKA_TOPIC_FINDING_CREATED", "custom.tenant.findings.new")
    import events.publisher as pub_module
    importlib.reload(pub_module)
    assert pub_module.TOPIC_FINDING_CREATED == "custom.tenant.findings.new"
    # Reload back to defaults to avoid polluting other tests
    monkeypatch.delenv("KAFKA_TOPIC_FINDING_CREATED", raising=False)
    importlib.reload(pub_module)
