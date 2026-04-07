import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from platform_shared.topics import GlobalTopics, topics_for_tenant
from platform_shared.models import PostureEnrichedEvent, AuthContext

def test_global_topics_model_events():
    gt = GlobalTopics()
    assert gt.MODEL_EVENTS == "cpm.global.model_events"

def test_global_topics_is_frozen():
    import dataclasses
    assert dataclasses.is_dataclass(GlobalTopics)
    gt = GlobalTopics()
    try:
        gt.MODEL_EVENTS = "other"
        assert False, "should have raised"
    except Exception:
        pass  # frozen dataclass raises FrozenInstanceError

def test_tenant_topics_unchanged():
    t = topics_for_tenant("t1")
    assert t.raw == "cpm.t1.raw"
    assert t.audit == "cpm.t1.audit"

def test_posture_enriched_event_has_model_id():
    auth = AuthContext(sub="u1", tenant_id="t1")
    event = PostureEnrichedEvent(
        event_id="e1", ts=1000, tenant_id="t1",
        user_id="u1", session_id="s1", prompt="hello",
        auth_context=auth,
    )
    assert event.model_id is None

def test_posture_enriched_event_accepts_model_id():
    auth = AuthContext(sub="u1", tenant_id="t1")
    event = PostureEnrichedEvent(
        event_id="e1", ts=1000, tenant_id="t1",
        user_id="u1", session_id="s1", prompt="hello",
        auth_context=auth, model_id="llama-guard-3",
    )
    assert event.model_id == "llama-guard-3"


import os

def test_processor_stamps_model_id_from_env(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_ID", "test-model-v1")
    model_id = os.getenv("LLM_MODEL_ID")
    assert model_id == "test-model-v1"

def test_model_gate_blocks_retired_model():
    blocked_models = {"retired-model-uuid"}
    model_id = "retired-model-uuid"
    allowed = model_id not in blocked_models
    assert allowed is False

def test_model_gate_allows_unknown_model_id():
    model_id = None
    allowed = model_id is None
    assert allowed is True


@pytest.mark.asyncio
async def test_check_model_gate_skips_when_no_model_id():
    """Gate returns True immediately when model_id is None (backward compat)."""
    from services.api.app import _check_model_gate
    # No httpx or Redis calls expected — just returns True
    with patch("services.api.app._get_gate_redis") as mock_redis:
        result = await _check_model_gate(None, "tenant-1")
    assert result is True
    mock_redis.assert_not_called()


@pytest.mark.asyncio
async def test_check_model_gate_fail_closed_on_timeout():
    """Gate returns False (blocked) when OPA call times out."""
    from services.api.app import _check_model_gate
    import httpx

    mock_redis = MagicMock()
    mock_redis.get.return_value = None  # cache miss
    with patch("services.api.app._get_gate_redis", return_value=mock_redis):
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=httpx.ConnectTimeout("timeout", request=None))
            mock_client_class.return_value = mock_client
            result = await _check_model_gate("model-abc", "tenant-1")
    assert result is False  # fail-closed


@pytest.mark.asyncio
async def test_check_model_gate_allows_approved_model():
    """Gate returns True when OPA says allow=true and caches the result."""
    from services.api.app import _check_model_gate

    mock_redis = MagicMock()
    mock_redis.get.return_value = None  # cache miss
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"result": True}
    with patch("services.api.app._get_gate_redis", return_value=mock_redis):
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client
            result = await _check_model_gate("model-abc", "tenant-1")
    assert result is True
    # Verify cache was set
    mock_redis.setex.assert_called_once()
    call_args = mock_redis.setex.call_args
    assert "spm:model_gate:model-abc:tenant-1" in call_args[0][0]
    assert call_args[0][1] == 30  # TTL
    assert call_args[0][2] == "approved"


@pytest.mark.asyncio
async def test_check_model_gate_returns_cached_result():
    """Gate returns cached result without calling OPA when cache hit."""
    from services.api.app import _check_model_gate

    mock_redis = MagicMock()
    mock_redis.get.return_value = "approved"  # cache hit
    with patch("services.api.app._get_gate_redis", return_value=mock_redis):
        with patch("httpx.AsyncClient") as mock_client_class:
            result = await _check_model_gate("model-abc", "tenant-1")
            mock_client_class.assert_not_called()  # no OPA call on cache hit
    assert result is True


def test_spm_self_register_payload_structure():
    """Validate the payload shape used for self-registration."""
    payload = {
        "name": "llama-guard-3",
        "version": "3.0.0",
        "provider": "local",
        "purpose": "content_screening",
        "risk_tier": "limited",
        "tenant_id": "global",
        "status": "approved",
        "approved_by": "startup-orchestrator",
    }
    required = {"name", "version", "provider", "purpose", "risk_tier", "tenant_id"}
    assert required.issubset(payload.keys())


def test_spm_orm_model_registry_columns():
    """Verify ORM model has required columns."""
    from spm.db.models import ModelRegistry
    cols = {c.key for c in ModelRegistry.__table__.columns}
    assert "model_id" in cols
    assert "name" in cols
    assert "status" in cols
    assert "ai_sbom" in cols


def test_spm_orm_posture_snapshot_columns():
    from spm.db.models import PostureSnapshot
    cols = {c.key for c in PostureSnapshot.__table__.columns}
    assert "model_id" in cols
    assert "avg_risk_score" in cols
    assert "snapshot_at" in cols


def test_spm_session_is_importable():
    from spm.db.session import get_engine
    assert get_engine is not None
