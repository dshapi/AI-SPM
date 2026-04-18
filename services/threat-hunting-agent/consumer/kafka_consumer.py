"""
consumer/kafka_consumer.py
───────────────────────────
Kafka consumer for the threat-hunting agent.

This is a single-tenant system — the tenant ID is always "t1".
Subscribes to cpm.t1.audit, cpm.t1.decision, cpm.t1.posture_enriched,
cpm.t1.sessions.blocked, and cpm.t1.sessions.policy_decision.

Events are accumulated in a time-window batch (HUNT_BATCH_WINDOW_SEC)
and dispatched to the ReAct agent.

Design:
  - One KafkaConsumer subscribes to all topics at startup.
  - Events are buffered in a deque (max HUNT_QUEUE_MAX).
  - A background threading.Timer fires the hunt every batch_window_sec.
  - The agent runs synchronously in the timer thread (each hunt is fast
    because the LLM call is the bottleneck — no async needed).
  - Graceful shutdown via stop().
"""
from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict, deque
from typing import Any, Callable, Dict, List, Optional

from config import TENANT_ID

logger = logging.getLogger(__name__)


class ThreatHuntConsumer:
    """
    Kafka consumer that batches events and fires the hunt agent.

    Single-tenant — always subscribes to the cpm.t1.* topics.

    Args:
        kafka_bootstrap: Broker address, e.g. 'kafka-broker:9092'.
        hunt_agent: Callable(tenant_id, events) → dict  (the run_hunt wrapper).
        batch_window_sec: How long to accumulate events before hunting.
        queue_max: Max events to buffer.
        consumer_factory: Optional callable that returns a KafkaConsumer-like object
                          (used in tests to inject a fake consumer).
        persist_fn: Optional callable(tenant_id, finding) to persist findings.
    """

    GROUP_ID = "threat-hunting-agent"

    # Fixed topic list for the single tenant (t1).
    TOPICS: List[str] = [
        f"cpm.{TENANT_ID}.audit",
        f"cpm.{TENANT_ID}.decision",
        f"cpm.{TENANT_ID}.posture_enriched",
        f"cpm.{TENANT_ID}.sessions.blocked",
        f"cpm.{TENANT_ID}.sessions.policy_decision",
    ]

    def __init__(
        self,
        kafka_bootstrap: str,
        hunt_agent: Callable[[str, List[Dict[str, Any]]], str],
        batch_window_sec: int = 30,
        queue_max: int = 20,
        consumer_factory: Optional[Callable] = None,
        persist_fn: Optional[Callable] = None,
    ) -> None:
        self._bootstrap = kafka_bootstrap
        self._hunt_agent = hunt_agent
        self._batch_window_sec = batch_window_sec
        self._queue_max = queue_max
        self._consumer_factory = consumer_factory or self._default_consumer_factory
        self._persist_fn = persist_fn

        self._queue: deque = deque(maxlen=self._queue_max)
        self._queue_lock = threading.Lock()

        self._consumer: Optional[Any] = None
        self._stop_event = threading.Event()
        self._poll_thread: Optional[threading.Thread] = None
        self._hunt_timer: Optional[threading.Timer] = None

    # ── Topics ────────────────────────────────────────────────────────────

    def _topics_for_tenants(self) -> List[str]:
        """Return the fixed topic list (kept for test compatibility)."""
        return self.TOPICS

    # ── Consumer factory ──────────────────────────────────────────────────

    def _default_consumer_factory(self) -> Any:
        from kafka import KafkaConsumer
        return KafkaConsumer(
            *self._topics_for_tenants(),
            bootstrap_servers=self._bootstrap,
            group_id=self.GROUP_ID,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            auto_offset_reset="earliest",
            enable_auto_commit=True,
            auto_commit_interval_ms=1000,
            session_timeout_ms=30000,
            heartbeat_interval_ms=10000,
            max_poll_records=100,
            consumer_timeout_ms=1000,  # so the poll loop can check stop_event
            # Skip the blocking check_version() DNS call at construction time.
            # The consumer will reconnect lazily when the broker becomes available.
            api_version=(2, 0, 0),
        )

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the consumer and the hunt timer in background threads."""
        logger.info(
            "ThreatHuntConsumer starting: tenant=%s topics=%s batch_window=%ds",
            TENANT_ID, self.TOPICS, self._batch_window_sec,
        )
        self._consumer = self._consumer_factory()
        self._poll_thread = threading.Thread(
            target=self._poll_loop, name="threat-hunter-poll", daemon=True
        )
        self._poll_thread.start()
        self._schedule_hunt()
        logger.info("ThreatHuntConsumer started")

    def stop(self) -> None:
        """Signal the consumer to stop and wait for threads to exit."""
        logger.info("ThreatHuntConsumer stopping")
        self._stop_event.set()
        if self._hunt_timer:
            self._hunt_timer.cancel()
        if self._poll_thread:
            self._poll_thread.join(timeout=5)
        if self._consumer:
            try:
                self._consumer.close()
            except Exception:
                pass
        logger.info("ThreatHuntConsumer stopped")

    # ── Poll loop ─────────────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        """Consume Kafka messages and enqueue them per-tenant."""
        while not self._stop_event.is_set():
            try:
                for msg in self._consumer:
                    if self._stop_event.is_set():
                        break
                    self._handle_message(msg)
            except StopIteration:
                pass  # consumer_timeout_ms reached — loop again
            except Exception as exc:
                logger.exception("Error in Kafka poll loop: %s", exc)

    # ── Pre-filter ────────────────────────────────────────────────────────
    # These thresholds decide which events are worth waking the agent for.
    # A single routine block (e.g. one "jailbreak" keyword) is noise —
    # the guard already handled it.  The agent is only useful when there is
    # a pattern or a high-confidence signal it can act on.
    _GUARD_SCORE_MIN:   float = 0.7   # ignore low-confidence flags
    _HIGH_SCORE_MIN:    float = 0.85  # always pass through regardless of category
    _PASS_CATEGORIES: set = {"S1", "S4", "S9"}  # always escalate these (CBRN, CSAM, violence)

    def _should_enqueue(self, payload: dict) -> bool:
        """
        Return True only if this event is worth sending to the agent.

        Filtered out (returns False):
          - allow verdicts with low score (benign traffic)
          - single low-score blocks that the guard already handled cleanly
          - decision events with no guard signal at all

        Always passed through (returns True):
          - high-severity categories (S1, S4, S9)
          - guard_score >= _HIGH_SCORE_MIN
          - posture_enriched events (the agent uses these for trend analysis)
          - audit events (always interesting for context)
        """
        topic = payload.get("_topic", "")

        # Always pass posture, audit, and blocked-session events
        if ".posture_enriched" in topic or ".audit" in topic or ".sessions.blocked" in topic:
            return True

        # Decision events: apply score + category filter
        verdict  = payload.get("guard_verdict", "allow")
        score    = float(payload.get("guard_score", 0.0))
        cats     = set(payload.get("guard_categories", []))

        # Always escalate dangerous categories regardless of score
        if cats & self._PASS_CATEGORIES:
            return True

        # Always escalate very high confidence hits
        if score >= self._HIGH_SCORE_MIN:
            return True

        # Drop low-signal blocks — guard handled them, nothing for agent to add
        if verdict in ("block", "flag") and score < self._GUARD_SCORE_MIN:
            logger.debug(
                "_should_enqueue: dropping low-signal %s event score=%.2f cats=%s",
                verdict, score, cats,
            )
            return False

        # Drop clean allows with no meaningful score
        if verdict == "allow" and score < 0.3:
            return False

        return True

    def _handle_message(self, msg: Any) -> None:
        """Enqueue a Kafka message into the event queue."""
        try:
            topic: str = msg.topic
            payload = msg.value if isinstance(msg.value, dict) else {}
            payload["_topic"] = topic  # tag so agent knows the event source

            if not self._should_enqueue(payload):
                return  # drop — not worth waking the agent

            with self._queue_lock:
                self._queue.append(payload)
        except Exception as exc:
            logger.warning("_handle_message error: %s", exc)

    # ── Hunt timer ────────────────────────────────────────────────────────

    def _schedule_hunt(self) -> None:
        if self._stop_event.is_set():
            return
        self._hunt_timer = threading.Timer(
            self._batch_window_sec, self._fire_hunts
        )
        self._hunt_timer.daemon = True
        self._hunt_timer.start()

    def _fire_hunts(self) -> None:
        """Drain the event queue and run the agent if there is anything to hunt."""
        try:
            with self._queue_lock:
                events = list(self._queue)
                self._queue.clear()

            if not events:
                return  # nothing to do

            logger.info("Firing hunt: tenant=%s events=%d", TENANT_ID, len(events))
            try:
                finding = self._hunt_agent(TENANT_ID, events)
                if isinstance(finding, dict):
                    logger.info(
                        "Hunt complete: tenant=%s finding_id=%s severity=%s should_open_case=%s",
                        TENANT_ID,
                        finding.get("finding_id", "?"),
                        finding.get("severity", "?"),
                        finding.get("should_open_case", False),
                    )
                    if self._persist_fn is not None:
                        try:
                            self._persist_fn(TENANT_ID, finding)
                        except Exception as persist_exc:
                            logger.exception("persist_fn failed: %s", persist_exc)
                else:
                    # Backward-compat: old string return (should not happen post-refactor)
                    logger.info("Hunt complete: tenant=%s summary_len=%d", TENANT_ID, len(str(finding)))
            except Exception as exc:
                logger.exception("Hunt failed: tenant=%s error=%s", TENANT_ID, exc)
        finally:
            self._schedule_hunt()  # re-arm the timer
