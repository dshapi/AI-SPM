"""Tests for simulation topic registration and event publisher."""
from platform_shared.topics import topics_for_tenant

def test_simulation_events_topic_name():
    t = topics_for_tenant("t1")
    assert t.simulation_events == "cpm.t1.simulation.events"

def test_simulation_events_in_all_topics():
    t = topics_for_tenant("t1")
    assert t.simulation_events in t.all_topics()

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services', 'api'))
from consumers.topic_resolver import resolve_topics

def test_simulation_events_topic_in_resolver():
    topics = resolve_topics(["t1"])
    assert "cpm.t1.simulation.events" in topics


from unittest.mock import MagicMock, patch
import platform_shared.simulation_events as sim_events

def _make_producer():
    p = MagicMock()
    p.produce = MagicMock()
    return p

def test_publish_started_calls_send_event():
    producer = _make_producer()
    with patch("platform_shared.simulation_events.send_event") as mock_send:
        sim_events.publish_started(
            producer, session_id="sess-1", prompt="hello",
            attack_type="custom", execution_mode="live",
        )
    mock_send.assert_called_once()
    kwargs = mock_send.call_args
    assert kwargs[1]["event_type"] == "simulation.started"
    assert kwargs[1]["source_service"] == "api-simulation"
    assert kwargs[1]["session_id"] == "sess-1"

def test_publish_blocked_includes_categories():
    producer = _make_producer()
    with patch("platform_shared.simulation_events.send_event") as mock_send:
        sim_events.publish_blocked(
            producer, session_id="sess-1", categories=["S1", "S2"],
            correlation_id="corr-1", decision_reason="Guard model block",
        )
    payload = mock_send.call_args[0][2].model_dump()   # 3rd positional arg is _SimPayload
    assert payload["categories"] == ["S1", "S2"]

def test_publish_completed_event_type():
    producer = _make_producer()
    with patch("platform_shared.simulation_events.send_event") as mock_send:
        sim_events.publish_completed(producer, session_id="sess-1", summary={})
    assert mock_send.call_args[1]["event_type"] == "simulation.completed"

def test_sim_payload_model_dump_returns_payload():
    from platform_shared.simulation_events import _SimPayload
    sp = _SimPayload({"key": "value"})
    assert sp.model_dump() == {"key": "value"}

def test_publish_blocked_passes_explanation_in_payload():
    producer = _make_producer()
    explanation = {
        "title": "Prompt Injection Attempt Detected",
        "reason": "The input contains a known instruction override pattern.",
        "matched_signal": "ignore all previous",
        "risk_level": "high",
        "impact": "Prevents unauthorized override.",
        "technical_details": {"blocked_by": "lexical", "categories": ["S15"]},
    }
    with patch("platform_shared.simulation_events.send_event") as mock_send:
        sim_events.publish_blocked(
            producer, session_id="sess-1", categories=["S15"],
            correlation_id="corr-1", decision_reason="lexical block",
            explanation=explanation,
        )
    payload = mock_send.call_args[0][2].model_dump()
    assert payload["explanation"] == explanation

def test_publish_blocked_no_explanation_still_works():
    producer = _make_producer()
    with patch("platform_shared.simulation_events.send_event") as mock_send:
        sim_events.publish_blocked(
            producer, session_id="sess-1", categories=["S9"],
            decision_reason="guard block",
        )
    payload = mock_send.call_args[0][2].model_dump()
    assert "explanation" not in payload or payload.get("explanation") is None
