"""
tests/test_kafka_consumer.py
─────────────────────────────
Unit tests for consumer/kafka_consumer.py.

A fake Kafka consumer is injected so no broker is needed.
"""
from __future__ import annotations

import threading
import time
from collections import namedtuple
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from consumer.kafka_consumer import ThreatHuntConsumer

# Minimal Kafka message stub
FakeMsg = namedtuple("FakeMsg", ["topic", "value"])


def _make_consumer(messages: list):
    """Return a fake Kafka consumer that yields `messages` then raises StopIteration."""
    fake = MagicMock()
    # __iter__ is called by `for msg in consumer`
    fake.__iter__ = MagicMock(return_value=iter(messages))
    fake.close = MagicMock()
    return fake


def _make_thc(
    messages: list,
    hunt_fn=None,
    batch_window_sec: int = 60,
    queue_max: int = 10,
    persist_fn=None,
) -> ThreatHuntConsumer:
    hunt_called: List[tuple] = []

    def default_hunt(tenant_id, events):
        hunt_called.append((tenant_id, events))
        return {
            "finding_id": "test-finding-1",
            "severity": "medium",
            "should_open_case": False,
            "title": "Test Finding",
        }

    thc = ThreatHuntConsumer(
        kafka_bootstrap="localhost:9092",
        tenant_list=["t1", "t2"],
        hunt_agent=hunt_fn or default_hunt,
        batch_window_sec=batch_window_sec,
        queue_max=queue_max,
        consumer_factory=lambda: _make_consumer(messages),
        persist_fn=persist_fn,
    )
    thc._hunt_called = hunt_called
    return thc


# ─────────────────────────────────────────────────────────────────────────────
# Topic derivation
# ─────────────────────────────────────────────────────────────────────────────

class TestTopics:
    def test_topics_for_tenants(self):
        thc = _make_thc([])
        topics = thc._topics_for_tenants()
        assert "cpm.t1.audit" in topics
        assert "cpm.t1.decision" in topics
        assert "cpm.t1.posture_enriched" in topics
        assert "cpm.t2.audit" in topics

    def test_topic_count(self):
        thc = _make_thc([])
        # 5 topics × 2 tenants = 10
        # (audit, decision, posture_enriched, sessions.blocked, sessions.policy_decision)
        assert len(thc._topics_for_tenants()) == 10


# ─────────────────────────────────────────────────────────────────────────────
# _handle_message
# ─────────────────────────────────────────────────────────────────────────────

class TestHandleMessage:
    def test_enqueues_to_correct_tenant(self):
        thc = _make_thc([])
        msg = FakeMsg(topic="cpm.t1.audit", value={"event_id": "e1"})
        thc._handle_message(msg)
        assert len(thc._queues["t1"]) == 1
        assert thc._queues["t1"][0]["event_id"] == "e1"

    def test_tags_topic(self):
        thc = _make_thc([])
        # Use a high-score decision event so _should_enqueue passes it through
        msg = FakeMsg(topic="cpm.t1.decision", value={"posture_score": 0.8, "guard_verdict": "block", "guard_score": 0.9})
        thc._handle_message(msg)
        assert thc._queues["t1"][0]["_topic"] == "cpm.t1.decision"

    def test_different_tenants_separate_queues(self):
        thc = _make_thc([])
        thc._handle_message(FakeMsg("cpm.t1.audit", {"id": "a"}))
        thc._handle_message(FakeMsg("cpm.t2.audit", {"id": "b"}))
        assert len(thc._queues["t1"]) == 1
        assert len(thc._queues["t2"]) == 1

    def test_malformed_topic_ignored(self):
        thc = _make_thc([])
        thc._handle_message(FakeMsg("badinput", {"x": 1}))
        # No queues populated
        assert sum(len(q) for q in thc._queues.values()) == 0

    def test_queue_max_respected(self):
        thc = _make_thc([], queue_max=3)
        for i in range(10):
            thc._handle_message(FakeMsg("cpm.t1.audit", {"i": i}))
        assert len(thc._queues["t1"]) == 3  # deque(maxlen=3) drops oldest


# ─────────────────────────────────────────────────────────────────────────────
# _fire_hunts
# ─────────────────────────────────────────────────────────────────────────────

class TestFireHunts:
    def test_calls_hunt_agent_per_tenant(self):
        thc = _make_thc([], batch_window_sec=9999)
        # Manually enqueue events
        thc._queues["t1"].append({"event_id": "e1"})
        thc._queues["t2"].append({"event_id": "e2"})
        # Cancel auto-scheduled timer to avoid side effects
        thc._stop_event.set()
        thc._fire_hunts()

        called = {t: evts for t, evts in thc._hunt_called}
        assert "t1" in called
        assert "t2" in called

    def test_clears_queue_after_hunt(self):
        thc = _make_thc([], batch_window_sec=9999)
        thc._queues["t1"].append({"event_id": "e1"})
        thc._stop_event.set()
        thc._fire_hunts()
        assert len(thc._queues["t1"]) == 0

    def test_skips_empty_queues(self):
        hunted = []
        thc = _make_thc([], hunt_fn=lambda t, e: hunted.append(t) or "ok",
                        batch_window_sec=9999)
        thc._stop_event.set()
        thc._fire_hunts()
        # No events → no hunt calls
        assert hunted == []

    def test_hunt_exception_does_not_crash_loop(self):
        def bad_hunt(tenant_id, events):
            raise RuntimeError("hunt exploded")

        thc = _make_thc([], hunt_fn=bad_hunt, batch_window_sec=9999)
        thc._queues["t1"].append({"event_id": "e1"})
        thc._stop_event.set()
        # Should not raise
        thc._fire_hunts()


# ─────────────────────────────────────────────────────────────────────────────
# start / stop lifecycle
# ─────────────────────────────────────────────────────────────────────────────

class TestLifecycle:
    def test_start_and_stop(self):
        thc = _make_thc([], batch_window_sec=60)
        thc.start()
        time.sleep(0.05)
        thc.stop()
        assert thc._stop_event.is_set()

    def test_consumer_close_called_on_stop(self):
        thc = _make_thc([], batch_window_sec=60)
        thc.start()
        thc.stop()
        thc._consumer.close.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# persist_fn callback
# ─────────────────────────────────────────────────────────────────────────────

class TestPersistFn:
    def test_persist_fn_called_after_hunt(self):
        persisted = []
        thc = _make_thc([], batch_window_sec=9999,
                        persist_fn=lambda t, f: persisted.append((t, f)))
        thc._queues["t1"].append({"event_id": "e1"})
        thc._stop_event.set()
        thc._fire_hunts()
        assert len(persisted) == 1
        assert persisted[0][0] == "t1"
        assert persisted[0][1]["finding_id"] == "test-finding-1"

    def test_persist_fn_none_does_not_crash(self):
        thc = _make_thc([], batch_window_sec=9999, persist_fn=None)
        thc._queues["t1"].append({"event_id": "e1"})
        thc._stop_event.set()
        thc._fire_hunts()  # should not raise
