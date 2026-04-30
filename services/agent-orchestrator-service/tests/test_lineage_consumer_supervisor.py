"""
tests/test_lineage_consumer_supervisor.py
─────────────────────────────────────────
Regression coverage for the LineageEventConsumer supervisor loop.

The bug
───────
Before this PR, ``LineageEventConsumer.start()`` was a one-shot connect:
on broker-unreachable at app boot it caught the exception, logged
``LOG-ONLY mode``, and never tried again for the lifetime of the pod.

Symptom in production: agent chats succeeded but the Runtime page stayed
empty because chat-lineage events never landed in ``agent_sessions`` /
``session_events`` — the consumer that was supposed to populate them was
silently disabled and only a pod restart after Kafka was healthy could
restore the persistence path.

What the supervisor guarantees
──────────────────────────────
* ``start()`` returns immediately (non-blocking, same external contract).
* If the first connect fails, the supervisor retries with exponential
  backoff capped at 60s — the consumer eventually catches up once Kafka
  is reachable, no manual restart required.
* On a connection drop mid-run, the supervisor reconnects on its own.
* ``stop()`` cancels the supervisor cleanly even if it's mid-retry.
"""
from __future__ import annotations

import asyncio
from typing import List

import pytest

from consumers.lineage_consumer import LineageEventConsumer


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


class _FakeConsumer:
    """Async-iterable stand-in for AIOKafkaConsumer.

    Yields a fixed list of envelopes then blocks (so the supervisor stays
    in the drain loop the way it would against a real broker).  ``stop()``
    raises ``StopAsyncIteration`` on the next ``__anext__`` so the drain
    exits cleanly when the supervisor tears it down.
    """

    def __init__(self, envelopes: List[dict]) -> None:
        self._envelopes = list(envelopes)
        self._stopped   = asyncio.Event()

    def __aiter__(self):
        return self

    async def __anext__(self):
        # Drain the queued envelopes synchronously — no need to wait.
        if self._envelopes:
            from collections import namedtuple
            Msg = namedtuple("Msg", ("value", "topic", "offset"))
            return Msg(value=self._envelopes.pop(0),
                       topic="cpm.global.lineage_events", offset=0)
        # No more envelopes — wait for stop() before raising.
        await self._stopped.wait()
        raise StopAsyncIteration

    async def stop(self) -> None:
        self._stopped.set()


@pytest.fixture
def consumer() -> LineageEventConsumer:
    """A consumer with a no-op session factory (we never call _persist)."""
    class _NoopFactory:
        def __call__(self):
            class _Ctx:
                async def __aenter__(self):
                    return None

                async def __aexit__(self, *_):
                    return None
            return _Ctx()

    return LineageEventConsumer(
        bootstrap_servers="kafka-0.kafka.aispm.svc.cluster.local:9092",
        topic="cpm.global.lineage_events",
        group_id="agent-orchestrator-lineage",
        session_factory=_NoopFactory(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_returns_immediately_on_connect_failure(
    monkeypatch, consumer
):
    """Old bug: a failing first connect blocked or disabled the consumer.

    New behaviour: ``start()`` does no connecting itself — it just
    creates the supervisor task and returns.  Even if ``_connect``
    raises forever, ``start()`` completes in microseconds.

    We verify by timing the call and asserting the supervisor task is
    alive afterwards.  No ``asyncio.wait_for`` patching is needed
    here — start() doesn't call it; only the background supervisor
    task does, and that's not what we're timing.
    """
    async def _always_fail(self_):
        raise ConnectionError("kafka unreachable in test")

    monkeypatch.setattr(LineageEventConsumer, "_connect", _always_fail)

    t0 = asyncio.get_event_loop().time()
    await consumer.start()
    elapsed = asyncio.get_event_loop().time() - t0

    # start() is essentially `create_task` + log — should be sub-millisecond.
    # Generous bound to avoid CI flake but still 1000× the expected runtime.
    assert elapsed < 0.1, (
        f"start() took {elapsed:.3f}s — should return immediately"
    )

    # Supervisor task is alive and retrying (not dead with LOG-ONLY).
    assert consumer._task is not None
    assert not consumer._task.done()
    assert not consumer._available     # connection never succeeded yet

    # stop() will cancel the supervisor mid-retry.
    await consumer.stop()
    assert consumer._task is None


@pytest.mark.asyncio
async def test_supervisor_retries_until_connect_succeeds(
    monkeypatch, consumer
):
    """The first N _connect calls fail, then one succeeds.

    Asserts the supervisor doesn't bail on the first failure and actually
    becomes available once the broker recovers.
    """
    attempts = {"n": 0}
    fake = _FakeConsumer(envelopes=[])

    async def _flaky_connect(self_):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ConnectionError("still unreachable")
        self_._consumer  = fake
        self_._available = True

    monkeypatch.setattr(LineageEventConsumer, "_connect", _flaky_connect)

    # Make the backoff sleep instant so the test doesn't wall-clock.
    async def _instant_wait_for(awaitable, timeout):
        raise asyncio.TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", _instant_wait_for)

    await consumer.start()

    # Wait up to 1s for _connect to succeed.
    deadline = asyncio.get_event_loop().time() + 1.0
    while not consumer._available:
        if asyncio.get_event_loop().time() > deadline:
            pytest.fail(
                f"consumer never connected after {attempts['n']} attempts"
            )
        await asyncio.sleep(0.01)

    assert attempts["n"] >= 3, "supervisor gave up too early"
    assert consumer._available is True

    await consumer.stop()


@pytest.mark.asyncio
async def test_stop_cancels_mid_retry(monkeypatch, consumer):
    """stop() must wake the supervisor even while it's sleeping in backoff."""
    async def _always_fail(self_):
        raise ConnectionError("never coming back")

    monkeypatch.setattr(LineageEventConsumer, "_connect", _always_fail)

    await consumer.start()
    # Let the supervisor enter its first sleep.
    await asyncio.sleep(0.05)
    # stop() must complete promptly even though we're mid-retry.
    await asyncio.wait_for(consumer.stop(), timeout=2.0)
    assert consumer._task is None
    assert consumer._available is False


@pytest.mark.asyncio
async def test_drain_processes_envelopes_after_connect(
    monkeypatch, consumer
):
    """End-to-end: connect succeeds, envelopes drain, _persist gets called."""
    persisted: List[dict] = []

    async def _capture_persist(self_, env):
        persisted.append(env)

    monkeypatch.setattr(LineageEventConsumer, "_persist", _capture_persist)

    fake = _FakeConsumer(envelopes=[
        {"session_id": "s1", "event_type": "AgentChatMessage", "payload": {}},
        {"session_id": "s2", "event_type": "AgentChatMessage", "payload": {}},
    ])

    async def _connect_with_fake(self_):
        self_._consumer  = fake
        self_._available = True

    monkeypatch.setattr(LineageEventConsumer, "_connect", _connect_with_fake)

    await consumer.start()

    # Drain happens as messages flow; give the loop a tick to process.
    deadline = asyncio.get_event_loop().time() + 1.0
    while len(persisted) < 2:
        if asyncio.get_event_loop().time() > deadline:
            pytest.fail(
                f"only {len(persisted)} envelopes drained, expected 2"
            )
        await asyncio.sleep(0.01)

    assert {e["session_id"] for e in persisted} == {"s1", "s2"}
    await consumer.stop()
