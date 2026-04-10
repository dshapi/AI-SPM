"""Unit tests for ResultsService caching behaviour."""
import json
import datetime
import pytest
from unittest.mock import AsyncMock
from results.service import ResultsService
from results.schemas import SessionResults


def _make_event_record(event_type, step=1):
    from models.event import EventRecord
    payload = json.dumps({"risk_score": 0.1, "risk_tier": "low", "signals": []})
    return EventRecord(
        session_id="sess-abc",
        event_type=event_type,
        payload=payload,
        timestamp=datetime.datetime(2025, 1, 1, 12, 0, step, tzinfo=datetime.timezone.utc),
        id=f"ev-{step}",
    )


def _make_full_session():
    return [
        _make_event_record("prompt.received", 1),
        _make_event_record("risk.calculated", 2),
        _make_event_record("policy.decision", 3),
        _make_event_record("session.created", 4),
        _make_event_record("session.completed", 5),
    ]


@pytest.fixture
def mock_repo():
    repo = AsyncMock()
    repo.get_by_session_id.return_value = _make_full_session()
    return repo


@pytest.mark.asyncio
async def test_get_results_returns_session_results(mock_repo):
    svc = ResultsService()
    result = await svc.get_results("sess-abc", mock_repo)
    assert isinstance(result, SessionResults)


@pytest.mark.asyncio
async def test_get_results_calls_repo(mock_repo):
    svc = ResultsService()
    await svc.get_results("sess-abc", mock_repo)
    mock_repo.get_by_session_id.assert_called_once_with("sess-abc")


@pytest.mark.asyncio
async def test_get_results_cached_on_same_event_count(mock_repo):
    svc = ResultsService()
    r1 = await svc.get_results("sess-abc", mock_repo)
    r2 = await svc.get_results("sess-abc", mock_repo)
    # Repo called twice (to check count), but same object returned
    assert mock_repo.get_by_session_id.call_count == 2
    assert r1 is r2


@pytest.mark.asyncio
async def test_get_results_invalidated_on_new_events(mock_repo):
    svc = ResultsService()
    r1 = await svc.get_results("sess-abc", mock_repo)

    # Simulate more events arriving
    mock_repo.get_by_session_id.return_value = _make_full_session() + [
        _make_event_record("audit.logged", 6),
    ]

    r2 = await svc.get_results("sess-abc", mock_repo)
    assert r1 is not r2  # cache was busted, new object


@pytest.mark.asyncio
async def test_get_results_empty_session_returns_partial(mock_repo):
    mock_repo.get_by_session_id.return_value = []
    svc = ResultsService()
    result = await svc.get_results("sess-empty", mock_repo)
    assert result.meta.partial is True


@pytest.mark.asyncio
async def test_invalidate_clears_cache(mock_repo):
    svc = ResultsService()
    r1 = await svc.get_results("sess-abc", mock_repo)
    svc.invalidate("sess-abc")
    r2 = await svc.get_results("sess-abc", mock_repo)
    # After invalidation, same count but new object computed
    assert r1 is not r2
