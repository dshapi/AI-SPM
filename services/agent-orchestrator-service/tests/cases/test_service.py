"""Unit tests for CasesService."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from cases.service import CasesService, _build_summary
from cases.schemas import CaseRecord
from models.session import SessionRecord
from results.schemas import SessionResults, SessionResultsMeta, RiskAnalysis


def _make_session(session_id: str = "sess-abc") -> SessionRecord:
    return SessionRecord(
        session_id=session_id,
        agent_id="TestAgent",
        user_id="user-1",
        tenant_id="tenant-1",
        prompt_hash="abc123",
        tools=[],
        context={},
        status="completed",
        risk_score=0.75,
        risk_tier="high",
        risk_signals=["pii_detected"],
        policy_decision="escalate",
        policy_reason="PII risk threshold exceeded",
        policy_version="v1",
        trace_id="trace-1",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _make_results(session_id: str = "sess-abc") -> SessionResults:
    return SessionResults(
        meta=SessionResultsMeta(session_id=session_id, event_count=3),
        status="completed",
        decision="escalate",
        risk=RiskAnalysis(score=0.75, tier="high"),
    )


@pytest.mark.asyncio
async def test_create_case_returns_case_record():
    """Happy path: session exists, returns a populated CaseRecord."""
    svc = CasesService()
    session = _make_session()
    results = _make_results()

    mock_session_repo = AsyncMock()
    mock_session_repo.get_by_id.return_value = session

    mock_event_repo = AsyncMock()
    mock_event_repo.get_by_session_id.return_value = [MagicMock(), MagicMock()]

    mock_results_svc = AsyncMock()
    mock_results_svc.get_results.return_value = results

    mock_case_repo = AsyncMock()
    mock_case_repo.insert = AsyncMock()

    case = await svc.create_case(
        session_id="sess-abc",
        reason="Suspicious PII exposure",
        session_repo=mock_session_repo,
        event_repo=mock_event_repo,
        results_svc=mock_results_svc,
        case_repo=mock_case_repo,
    )

    assert case is not None
    assert case.session_id == "sess-abc"
    assert case.status == "open"
    assert case.reason == "Suspicious PII exposure"
    assert case.risk_score == 0.75
    assert case.decision == "escalate"
    assert len(case.case_id) > 0
    assert "sess-abc" in case.summary


@pytest.mark.asyncio
async def test_create_case_returns_none_when_session_not_found():
    """Session not found → service returns None (router maps this to 404)."""
    svc = CasesService()

    mock_session_repo = AsyncMock()
    mock_session_repo.get_by_id.return_value = None

    mock_event_repo = AsyncMock()
    mock_results_svc = AsyncMock()

    mock_case_repo = AsyncMock()

    result = await svc.create_case(
        session_id="nonexistent",
        reason="test",
        session_repo=mock_session_repo,
        event_repo=mock_event_repo,
        results_svc=mock_results_svc,
        case_repo=mock_case_repo,
    )

    assert result is None
    mock_event_repo.get_by_session_id.assert_not_called()
    mock_results_svc.get_results.assert_not_called()


@pytest.mark.asyncio
async def test_list_cases_returns_newest_first():
    """list_cases() delegates to case_repo.list_all and returns what it gets."""
    from datetime import timedelta
    svc = CasesService()

    now = datetime.now(timezone.utc)
    c1 = CaseRecord(case_id="c1", session_id="s1", reason="r1", summary="", risk_score=0.1, decision="allow", created_at=now - timedelta(hours=2))
    c2 = CaseRecord(case_id="c2", session_id="s2", reason="r2", summary="", risk_score=0.5, decision="block", created_at=now - timedelta(hours=1))
    c3 = CaseRecord(case_id="c3", session_id="s3", reason="r3", summary="", risk_score=0.9, decision="escalate", created_at=now)

    # Repository returns records pre-sorted newest-first (DB responsibility)
    mock_case_repo = AsyncMock()
    mock_case_repo.list_all = AsyncMock(return_value=[c3, c2, c1])

    result = await svc.list_cases(mock_case_repo)

    assert [c.case_id for c in result] == ["c3", "c2", "c1"]
    mock_case_repo.list_all.assert_awaited_once_with(limit=200)


@pytest.mark.asyncio
async def test_list_cases_empty():
    """list_cases() returns empty list when repository has no records."""
    svc = CasesService()

    mock_case_repo = AsyncMock()
    mock_case_repo.list_all = AsyncMock(return_value=[])

    result = await svc.list_cases(mock_case_repo)
    assert result == []


def test_build_summary_contains_key_fields():
    """_build_summary includes session_id, agent_id, risk tier, and decision."""
    session = _make_session("sess-xyz")
    results = _make_results("sess-xyz")
    summary = _build_summary(session, results, event_count=5)

    assert "sess-xyz" in summary
    assert "TestAgent" in summary
    assert "high" in summary.lower()
    assert "escalate" in summary.lower()
