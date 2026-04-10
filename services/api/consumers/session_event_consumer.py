"""
consumers/session_event_consumer.py
─────────────────────────────────────
Single shared Kafka consumer with async fan-out by session_id.

Design
──────
kafka-python-ng (kafka-python) is a blocking library.  Rather than
wrapping it in aiokafka (a separate dependency), we run the consumer in a
dedicated daemon thread and bridge events to the async world through
asyncio.Queue + loop.call_soon_threadsafe().

One consumer thread serves all active WebSocket connections:

  Browser A  ──┐
  Browser B  ──┤   asyncio.Queue per WS
  Browser C  ──┘         ▲
                          │  loop.call_soon_threadsafe(queue.put_nowait, event)
               [daemon thread]
               KafkaConsumer.poll()
                          │
               [Kafka topics: cpm.t1.raw, cpm.t1.decision, …]

Thread-safety contract:
  * _subscribers dict is protected by threading.Lock.
  * Queue.put_nowait is called via loop.call_soon_threadsafe from the
    consumer thread — the only cross-thread call.  All other asyncio
    operations happen exclusively in the event loop thread.

Backpressure:
  Each queue has a fixed cap (QUEUE_MAX_SIZE = 256 by default).  When full
  the event is logged and dropped rather than blocking the consumer thread.

Upstream enrichment note:
  Not every Kafka message carries a session_id.  Services that emit events
  without a session_id SHOULD be updated to include:
    { "session_id": "<uuid>", ... }
  in the top-level payload.  Until then, those events are silently ignored
  by the bridge (they have no registered subscriber anyway).
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from kafka import KafkaConsumer
from kafka.errors import KafkaError

from platform_shared.config import get_settings
from consumers.topic_resolver import infer_source_service

log = logging.getLogger("api.consumers.session_event_consumer")

# Bounded queue cap per WebSocket connection
QUEUE_MAX_SIZE: int = 256

# How long poll() blocks waiting for records (ms)
_POLL_TIMEOUT_MS: int = 200

# Back-off before reconnecting after a Kafka error (seconds)
_RECONNECT_BACKOFF_S: int = 5


# Internal subscriber entry: (loop_id, event_loop, asyncio.Queue)
_Subscriber = Tuple[int, asyncio.AbstractEventLoop, "asyncio.Queue[dict]"]


class SessionEventConsumer:
    """
    Shared Kafka consumer — one instance per API process.

    Usage
    ─────
    consumer = SessionEventConsumer(topics=[...], group_id="api-ws-bridge")
    consumer.start()                        # call once in lifespan startup
    consumer.subscribe(session_id, loop, queue)   # called per WS connect
    consumer.unsubscribe(session_id, queue)        # called per WS disconnect
    consumer.stop()                         # call once in lifespan shutdown
    """

    def __init__(
        self,
        topics: List[str],
        group_id: str = "api-ws-bridge",
        poll_timeout_ms: int = _POLL_TIMEOUT_MS,
        queue_max_size: int = QUEUE_MAX_SIZE,
    ) -> None:
        self._topics = topics
        self._group_id = group_id
        self._poll_timeout_ms = poll_timeout_ms
        self._queue_max_size = queue_max_size

        # session_id → set of subscriber tuples
        self._subscribers: Dict[str, Set[_Subscriber]] = {}
        self._lock = threading.Lock()

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        # Hold reference so we can call wakeup() on shutdown
        self._consumer: Optional[KafkaConsumer] = None

    # ── Subscription management ───────────────────────────────────────────────

    def subscribe(
        self,
        session_id: str,
        loop: asyncio.AbstractEventLoop,
        queue: "asyncio.Queue[dict]",
    ) -> None:
        """Register *queue* to receive events for *session_id*."""
        with self._lock:
            if session_id not in self._subscribers:
                self._subscribers[session_id] = set()
            self._subscribers[session_id].add((id(loop), loop, queue))
        log.info(
            "ws_subscribe session_id=%s sessions_with_subs=%d",
            session_id,
            len(self._subscribers),
        )

    def unsubscribe(
        self,
        session_id: str,
        queue: "asyncio.Queue[dict]",
    ) -> None:
        """Remove *queue* from the fan-out registry for *session_id*."""
        with self._lock:
            if session_id in self._subscribers:
                self._subscribers[session_id] = {
                    sub for sub in self._subscribers[session_id]
                    if sub[2] is not queue
                }
                if not self._subscribers[session_id]:
                    del self._subscribers[session_id]
        log.info(
            "ws_unsubscribe session_id=%s sessions_with_subs=%d",
            session_id,
            len(self._subscribers),
        )

    # ── Fan-out helpers ───────────────────────────────────────────────────────

    def _get_subscribers(self, session_id: str) -> List[_Subscriber]:
        """Return a snapshot of subscribers for *session_id* (lock-safe copy)."""
        with self._lock:
            return list(self._subscribers.get(session_id, set()))

    def _dispatch(self, session_id: str, event: dict) -> None:
        """
        Route *event* to all queues registered for *session_id*.
        Called from the consumer thread.
        """
        subs = self._get_subscribers(session_id)
        if not subs:
            return

        for _lid, loop, queue in subs:
            if queue.qsize() >= self._queue_max_size:
                log.warning(
                    "ws_queue_full session_id=%s event_type=%s — dropping",
                    session_id,
                    event.get("event_type", "?"),
                )
                continue
            try:
                loop.call_soon_threadsafe(queue.put_nowait, event)
            except Exception as exc:
                log.warning(
                    "ws_dispatch_error session_id=%s error=%s",
                    session_id,
                    exc,
                )

    # ── Message handling ──────────────────────────────────────────────────────

    @staticmethod
    def _extract_session_id(value: Any) -> Optional[str]:
        """
        Pull session_id from a Kafka message value.

        Checks:
          1. Top-level "session_id" or "sessionId"
          2. Nested under "payload" dict
        Returns None if not found (event will be ignored).
        """
        if not isinstance(value, dict):
            return None
        for key in ("session_id", "sessionId"):
            if val := value.get(key):
                return str(val)
        if isinstance(payload := value.get("payload"), dict):
            for key in ("session_id", "sessionId"):
                if val := payload.get(key):
                    return str(val)
        return None

    def _handle_message(self, topic: str, value: Any) -> None:
        """
        Process one deserialized Kafka message.

        Normalizes the raw dict into a WsEvent-compatible shape, then
        dispatches to registered queues.  Messages without a session_id
        are skipped — they have no subscriber anyway.
        """
        session_id = self._extract_session_id(value)
        if not session_id:
            return  # no session_id — not bridgeable; skip

        # Fast-path: skip if no one is listening for this session
        with self._lock:
            if session_id not in self._subscribers:
                return

        if not isinstance(value, dict):
            return

        # ── Normalize to WsEvent wire shape ───────────────────────────────────
        _SKIP_KEYS = frozenset({"session_id", "sessionId", "event_type", "source_service", "timestamp", "ts"})
        event: dict = {
            "session_id":     session_id,
            "event_type":     value.get("event_type") or value.get("type") or "unknown",
            "source_service": value.get("source_service") or infer_source_service(topic),
            "timestamp":      value.get("timestamp") or value.get("ts") or "",
            "payload":        {k: v for k, v in value.items() if k not in _SKIP_KEYS},
        }
        self._dispatch(session_id, event)

    # ── Consumer thread ───────────────────────────────────────────────────────

    def _build_consumer(self) -> KafkaConsumer:
        s = get_settings()
        return KafkaConsumer(
            *self._topics,
            bootstrap_servers=s.kafka_bootstrap_servers,
            group_id=self._group_id,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            # "latest" — WS bridge only needs live events, not historical replay
            auto_offset_reset="latest",
            enable_auto_commit=True,
            auto_commit_interval_ms=1000,
            session_timeout_ms=30_000,
            heartbeat_interval_ms=10_000,
            max_poll_records=50,
            fetch_max_wait_ms=self._poll_timeout_ms,
        )

    def _run(self) -> None:
        """Main consumer loop — runs inside the daemon thread."""
        log.info(
            "kafka_consumer_starting topics=%s group=%s",
            self._topics,
            self._group_id,
        )

        while not self._stop_event.is_set():
            consumer: Optional[KafkaConsumer] = None
            try:
                consumer = self._build_consumer()
                self._consumer = consumer
                log.info("kafka_consumer_connected bootstrap=%s", get_settings().kafka_bootstrap_servers)

                while not self._stop_event.is_set():
                    records = consumer.poll(timeout_ms=self._poll_timeout_ms)
                    for tp, messages in records.items():
                        for msg in messages:
                            try:
                                self._handle_message(tp.topic, msg.value)
                            except Exception as exc:
                                log.warning(
                                    "kafka_msg_handler_error topic=%s offset=%s error=%s",
                                    tp.topic,
                                    msg.offset,
                                    exc,
                                )

            except KafkaError as exc:
                log.error(
                    "kafka_consumer_error error=%s — reconnecting in %ds",
                    exc,
                    _RECONNECT_BACKOFF_S,
                )
                time.sleep(_RECONNECT_BACKOFF_S)
            except Exception as exc:
                log.exception(
                    "kafka_consumer_unexpected_error error=%s — reconnecting in %ds",
                    exc,
                    _RECONNECT_BACKOFF_S,
                )
                time.sleep(_RECONNECT_BACKOFF_S)
            finally:
                if consumer is not None:
                    try:
                        consumer.close()
                    except Exception:
                        pass
                self._consumer = None

        log.info("kafka_consumer_stopped")

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self, topics: Optional[List[str]] = None) -> None:
        """
        Start the background consumer thread.

        Parameters
        ----------
        topics : optional override; uses the list passed to __init__ if None.
        """
        if topics:
            self._topics = topics
        if not self._topics:
            log.warning("kafka_consumer_no_topics_configured — not starting")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="kafka-ws-consumer",
            daemon=True,   # exits automatically when the main process exits
        )
        self._thread.start()
        log.info("kafka_consumer_thread_started thread=%s", self._thread.name)

    def stop(self, timeout: float = 10.0) -> None:
        """Signal the consumer thread to stop and wait for it to exit."""
        log.info("kafka_consumer_stopping")
        self._stop_event.set()
        # Interrupt an in-progress poll() so the thread exits promptly
        consumer = self._consumer
        if consumer is not None:
            try:
                consumer.wakeup()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                log.warning("kafka_consumer_thread_did_not_stop_in_time timeout=%ss", timeout)
        log.info("kafka_consumer_thread_stopped")

    # ── Observability ─────────────────────────────────────────────────────────

    @property
    def active_session_count(self) -> int:
        """Number of session_ids that currently have at least one subscriber."""
        with self._lock:
            return len(self._subscribers)

    @property
    def total_subscriber_count(self) -> int:
        """Total number of individual queue subscriptions across all sessions."""
        with self._lock:
            return sum(len(v) for v in self._subscribers.values())

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
