"""
consumer/kafka_consumer.py
───────────────────────────
Kafka consumer for the threat-hunting agent.

Subscribes to audit + decision + posture_enriched topics for each tenant
in the configured TENANTS list.  Events are accumulated in a time-window
batch (HUNT_BATCH_WINDOW_SEC) and dispatched to the ReAct agent.

Design:
  - One KafkaConsumer subscribes to all topics at startup.
  - Events are buffered per-tenant in a deque (max HUNT_QUEUE_MAX).
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

logger = logging.getLogger(__name__)


class ThreatHuntConsumer:
    """
    Kafka consumer that batches events per tenant and fires the agent.

    Args:
        kafka_bootstrap: Broker address, e.g. 'kafka-broker:9092'.
        tenant_list: List of tenant IDs to subscribe to.
        hunt_agent: Callable(tenant_id, events) → str  (the run_hunt wrapper).
        batch_window_sec: How long to accumulate events before hunting.
        queue_max: Max events to buffer per tenant.
        consumer_factory: Optional callable that returns a KafkaConsumer-like object
                          (used in tests to inject a fake consumer).
    """

    GROUP_ID = "threat-hunting-agent"

    def __init__(
        self,
        kafka_bootstrap: str,
        tenant_list: List[str],
        hunt_agent: Callable[[str, List[Dict[str, Any]]], str],
        batch_window_sec: int = 30,
        queue_max: int = 20,
        consumer_factory: Optional[Callable] = None,
    ) -> None:
        self._bootstrap = kafka_bootstrap
        self._tenant_list = tenant_list
        self._hunt_agent = hunt_agent
        self._batch_window_sec = batch_window_sec
        self._queue_max = queue_max
        self._consumer_factory = consumer_factory or self._default_consumer_factory

        # Per-tenant event queues
        self._queues: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self._queue_max))
        self._queue_lock = threading.Lock()

        self._consumer: Optional[Any] = None
        self._stop_event = threading.Event()
        self._poll_thread: Optional[threading.Thread] = None
        self._hunt_timer: Optional[threading.Timer] = None

    # ── Topics ────────────────────────────────────────────────────────────

    def _topics_for_tenants(self) -> List[str]:
        topics = []
        for tid in self._tenant_list:
            topics.append(f"cpm.{tid}.audit")
            topics.append(f"cpm.{tid}.decision")
            topics.append(f"cpm.{tid}.posture_enriched")
        return topics

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
        )

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the consumer and the hunt timer in background threads."""
        logger.info(
            "ThreatHuntConsumer starting: tenants=%s topics=%s batch_window=%ds",
            self._tenant_list, self._topics_for_tenants(), self._batch_window_sec,
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

    def _handle_message(self, msg: Any) -> None:
        """Enqueue a Kafka message into the appropriate tenant queue."""
        try:
            topic: str = msg.topic
            # Derive tenant_id from topic name: cpm.{tenant}.{event_type}
            parts = topic.split(".", 2)
            if len(parts) < 2:
                return
            tenant_id = parts[1]
            payload = msg.value if isinstance(msg.value, dict) else {}
            payload["_topic"] = topic  # tag so agent knows the event source
            with self._queue_lock:
                self._queues[tenant_id].append(payload)
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
        """Drain all tenant queues and run the agent for each non-empty batch."""
        try:
            with self._queue_lock:
                batches = {
                    tid: list(q)
                    for tid, q in self._queues.items()
                    if q
                }
                for q in self._queues.values():
                    q.clear()

            for tenant_id, events in batches.items():
                logger.info("Firing hunt: tenant=%s events=%d", tenant_id, len(events))
                try:
                    summary = self._hunt_agent(tenant_id, events)
                    logger.info("Hunt complete: tenant=%s summary_len=%d", tenant_id, len(summary))
                except Exception as exc:
                    logger.exception("Hunt failed: tenant=%s error=%s", tenant_id, exc)
        finally:
            self._schedule_hunt()  # re-arm the timer
