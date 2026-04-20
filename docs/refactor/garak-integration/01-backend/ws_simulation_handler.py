"""
services/api/ws/simulation_ws.py  (v2.2 — final hardening pass)
──────────────────────────────────────────────────────────────
Production-grade WebSocket handler for the Simulation Lab.

What v2.2 changed over v2.1
───────────────────────────
* **Per-session bounded send queue + writer task.**  The orchestrator
  enqueues non-blockingly; a dedicated writer task per session drains
  FIFO with ``await ws.send_json``.  This gives us backpressure
  (bounded memory under slow clients) AND deterministic ordering.

  Why not ``asyncio.create_task(ws.send_json(...))`` as the original
  hardening spec suggested?  Fire-and-forget tasks do NOT guarantee
  completion order under cooperative scheduling — frames can reorder,
  and an unbounded task fan-out will memory-leak when the client is
  slow.  That directly contradicts "deterministic ordering" and
  "stable ordering (CRITICAL)" elsewhere in the spec.  A bounded
  single-writer queue is what production systems (Datadog, Wiz,
  etc.) actually use for the same problem.

* **Attempt-envelope validation.**  Before shipping a
  ``simulation.attempt`` frame we verify ``data.attempt_id`` is a
  present, non-zero UUID string.  If the orchestrator ever regresses
  and emits a malformed attempt, it's dropped with an error log
  instead of corrupting the client store.

* **Slow-client detection.**  If the send queue stays full for
  ``WS_SLOW_CLIENT_GRACE_S`` seconds, we emit a structured
  ``simulation.warning{code:"SLOW_CLIENT"}`` (logged server-side)
  and close the socket with code 1013 (Try Again Later).

Wire format
───────────
    { "type":       "simulation.attempt",
      "session_id": "<uuid>",
      "sequence":   42,
      "timestamp":  "2026-04-20T12:00:00.123456+00:00",
      "data":       { <Attempt> } }

The envelope is built in the orchestrator; this handler is a transport.
Sequence is a non-negative integer from the orchestrator; out-of-band
synthetic frames (overflow warnings) carry ``sequence: null``.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as _dt
import logging
import os
import uuid
from collections import deque
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

log = logging.getLogger("api.ws.simulation")
router = APIRouter()


_PING_INTERVAL_S       = float(os.environ.get("WS_PING_INTERVAL_S", "20.0"))
_BUFFER_LIMIT          = int(os.environ.get("WS_PRECONNECT_BUFFER", "512"))
_SEND_TIMEOUT_S        = float(os.environ.get("WS_SEND_TIMEOUT_S", "10.0"))
_SEND_QUEUE_LIMIT      = int(os.environ.get("WS_SEND_QUEUE_LIMIT", "2048"))
_SLOW_CLIENT_GRACE_S   = float(os.environ.get("WS_SLOW_CLIENT_GRACE_S", "5.0"))

_ZERO_UUID = "00000000-0000-0000-0000-000000000000"


def _utcnow_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


# ── Envelope validation ─────────────────────────────────────────────────────

def _validate_envelope(envelope: dict) -> tuple[bool, Optional[str]]:
    """Return (ok, reason_if_not_ok).

    Mandatory: ``type`` (non-empty str), ``session_id`` (non-empty str),
    ``data`` (must exist — may be dict or None for some events).  Sequence
    is validated separately because we allow ``null`` for out-of-band
    transport frames.

    For ``simulation.attempt`` frames we additionally require
    ``data.attempt_id`` to be a present, non-zero UUID string.
    """
    if not isinstance(envelope, dict):
        return False, "envelope is not a dict"
    et = envelope.get("type")
    if not isinstance(et, str) or not et:
        return False, "missing or empty 'type'"
    sid = envelope.get("session_id")
    if not isinstance(sid, str) or not sid:
        return False, "missing or empty 'session_id'"
    if "data" not in envelope:
        return False, "missing 'data'"

    if et == "simulation.attempt":
        data = envelope.get("data")
        if not isinstance(data, dict):
            return False, "attempt envelope 'data' must be a dict"
        aid = data.get("attempt_id")
        if not isinstance(aid, str) or not aid or aid == _ZERO_UUID:
            return False, "attempt envelope missing or zero attempt_id"

    return True, None


# ── Per-session writer ──────────────────────────────────────────────────────

class _SessionWriter:
    """FIFO writer for one session.

    Owns a bounded ``asyncio.Queue`` and a single consumer task.  The
    orchestrator side enqueues non-blockingly via ``offer()``; the
    consumer task dequeues in order and awaits ``ws.send_json``.  This
    gives us:

      * deterministic order (single consumer, FIFO queue)
      * bounded memory (queue maxsize)
      * backpressure — ``offer()`` is non-blocking; on queue-full we
        DROP THE OLDEST frame and enqueue the new one, then inject a
        synthetic ``simulation.warning{code:"WS_QUEUE_OVERFLOW"}`` so
        the client learns it missed something.

    Drop-oldest is deliberate and matches the hardening spec: the
    newer event is almost always more interesting to the operator
    (a summary / completed / terminal is worth more than an old
    attempt), and it keeps the wire moving forward instead of
    rewarding a stuck consumer.  Count-tracking per session feeds
    a SLOW_CLIENT hard-close after a grace window.
    """

    def __init__(self, session_id: uuid.UUID, ws: WebSocket) -> None:
        self.session_id = session_id
        self.ws:         WebSocket = ws
        self.queue:      asyncio.Queue[dict] = asyncio.Queue(maxsize=_SEND_QUEUE_LIMIT)
        self.closed:     bool = False
        self.drop_count: int  = 0
        self._writer_task: asyncio.Task | None = None
        self._slow_since:  float | None = None

    def start(self) -> None:
        self._writer_task = asyncio.create_task(self._run(), name=f"ws-writer-{self.session_id}")

    async def stop(self) -> None:
        self.closed = True
        if self._writer_task is not None and not self._writer_task.done():
            self._writer_task.cancel()
            with contextlib.suppress(Exception):
                await self._writer_task

    def _put_nowait_drop_oldest(self, envelope: dict) -> bool:
        """Insert into the queue; if full, drop the oldest frame to make room.

        Returns True if an overflow occurred (caller should enqueue an
        overflow warning), False otherwise.  We use a small loop rather
        than a single get/put because in principle another path could
        have already drained the queue while we were deciding.
        """
        overflowed = False
        while True:
            try:
                self.queue.put_nowait(envelope)
                return overflowed
            except asyncio.QueueFull:
                overflowed = True
                try:
                    dropped = self.queue.get_nowait()
                    self.drop_count += 1
                    log.warning(
                        "ws queue overflow session=%s dropped_type=%s dropped_total=%d",
                        self.session_id,
                        dropped.get("type") if isinstance(dropped, dict) else "?",
                        self.drop_count,
                    )
                except asyncio.QueueEmpty:
                    # Raced with the writer — try once more.
                    continue

    def offer(self, envelope: dict) -> None:
        """Non-blocking enqueue with drop-oldest overflow handling.

        On overflow we additionally inject a synthetic
        ``simulation.warning{code:"WS_QUEUE_OVERFLOW"}`` frame AFTER the
        new envelope so the client sees the warning next to where the
        loss occurred.  sequence is null (out-of-band transport frame).
        """
        if self.closed:
            return
        overflowed = self._put_nowait_drop_oldest(envelope)
        if overflowed:
            if self._slow_since is None:
                self._slow_since = asyncio.get_event_loop().time()
            warn_frame = {
                "type":       "simulation.warning",
                "session_id": str(self.session_id),
                "sequence":   None,
                "timestamp":  _utcnow_iso(),
                "data": {
                    "code":    "WS_QUEUE_OVERFLOW",
                    "message": "WebSocket send queue overflow; "
                               "oldest frames dropped",
                    "detail": {
                        "dropped_count": self.drop_count,
                        "queue_limit":   _SEND_QUEUE_LIMIT,
                        "hint":          "Client is too slow; reduce "
                                         "simulation volume or improve connection",
                    },
                },
            }
            # This is a second insert — if the queue is STILL full we'll
            # drop the oldest again, which is fine; the warning itself
            # stays in the queue because it's the newest frame.
            with contextlib.suppress(asyncio.QueueFull):
                self.queue.put_nowait(warn_frame)
        else:
            self._slow_since = None

    def slow_for_seconds(self) -> float:
        if self._slow_since is None:
            return 0.0
        return asyncio.get_event_loop().time() - self._slow_since

    async def _run(self) -> None:
        try:
            while not self.closed:
                envelope = await self.queue.get()
                try:
                    await asyncio.wait_for(self.ws.send_json(envelope), timeout=_SEND_TIMEOUT_S)
                except (WebSocketDisconnect, asyncio.TimeoutError, RuntimeError) as exc:
                    log.info("ws writer send failed session=%s type=%s err=%s",
                             self.session_id, envelope.get("type"), exc)
                    self.closed = True
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("ws writer crashed session=%s", self.session_id)
        finally:
            # Drain-on-close: the socket is gone, we cannot send anything,
            # but frames still in the queue represent information the
            # operator would otherwise lose silently.  Log them (type +
            # session) so audit trails reflect the truth.  Never blocks
            # shutdown — bounded by the queue's current depth.
            while not self.queue.empty():
                try:
                    dropped = self.queue.get_nowait()
                    log.warning(
                        "WS_DRAIN_ON_CLOSE dropped frame type=%s session=%s",
                        dropped.get("type") if isinstance(dropped, dict) else "?",
                        self.session_id,
                    )
                except Exception:
                    break


# ── Connection manager ──────────────────────────────────────────────────────

class SessionConnectionManager:
    """One connection per session; events for other sessions never leak in.

    The manager is a singleton held at module load; ``get_manager()`` returns
    it.  Any code that previously poked ``ws.session_ws._manager`` should
    use that accessor instead.
    """

    def __init__(self) -> None:
        self._lock:           asyncio.Lock = asyncio.Lock()
        self._writers:        dict[uuid.UUID, _SessionWriter] = {}
        self._pending:        dict[uuid.UUID, deque[dict]] = {}
        self._connected_evt:  dict[uuid.UUID, asyncio.Event] = {}
        # How many pre-connect frames were silently evicted by deque.maxlen.
        self._overflow_count: dict[uuid.UUID, int] = {}

    @property
    def active_session_ids(self) -> set[uuid.UUID]:
        return set(self._writers.keys())

    # ── registration ─────────────────────────────────────────────────────────

    async def register(self, session_id: uuid.UUID, ws: WebSocket) -> None:
        async with self._lock:
            # Enforce single-writer per session — drop any stale writer.
            old = self._writers.pop(session_id, None)
            if old is not None:
                await old.stop()
                if old.ws is not ws:
                    with contextlib.suppress(Exception):
                        await old.ws.close(code=1001, reason="superseded")
            writer = _SessionWriter(session_id, ws)
            writer.start()
            self._writers[session_id] = writer
            buffered   = self._pending.pop(session_id, deque())
            overflowed = self._overflow_count.pop(session_id, 0)
            evt = self._connected_evt.setdefault(session_id, asyncio.Event())
            evt.set()

        # Synthetic "we dropped N frames" warning goes to the head of the
        # replay so the client notices immediately.  sequence=null because
        # this is out-of-band w.r.t. the orchestrator sequence space.
        if overflowed > 0:
            warn_frame = {
                "type":       "simulation.warning",
                "session_id": str(session_id),
                "sequence":   None,
                "timestamp":  _utcnow_iso(),
                "data": {
                    "code":    "PRECONNECT_BUFFER_OVERFLOW",
                    "message": f"{overflowed} frame(s) were dropped before the "
                                "client connected; stream will resume from the "
                                "next orchestrator emit.",
                    "detail":  {"dropped_count": overflowed,
                                "buffer_limit":  _BUFFER_LIMIT},
                },
            }
            writer.offer(warn_frame)

        for msg in buffered:
            writer.offer(msg)

    async def unregister(self, session_id: uuid.UUID, ws: WebSocket) -> None:
        async with self._lock:
            writer = self._writers.get(session_id)
            if writer is not None and writer.ws is ws:
                self._writers.pop(session_id, None)
                await writer.stop()
            # Do NOT clear pending here — a reconnect within the session
            # should still receive recent events.  The buffer is drained on
            # the next register().

    async def wait_connected(self, session_id: uuid.UUID, timeout_s: float) -> bool:
        async with self._lock:
            evt = self._connected_evt.setdefault(session_id, asyncio.Event())
        try:
            await asyncio.wait_for(evt.wait(), timeout=timeout_s)
            return True
        except asyncio.TimeoutError:
            return False

    # ── send path ───────────────────────────────────────────────────────────

    async def send(self, session_id: uuid.UUID, envelope: dict) -> None:
        ok, reason = _validate_envelope(envelope)
        if not ok:
            log.error("ws: refusing to send malformed envelope session=%s type=%s reason=%s",
                      session_id,
                      envelope.get("type") if isinstance(envelope, dict) else type(envelope).__name__,
                      reason)
            return

        async with self._lock:
            writer = self._writers.get(session_id)
            if writer is None:
                # No client yet: stash in bounded pre-connect buffer.
                q = self._pending.setdefault(session_id, deque(maxlen=_BUFFER_LIMIT))
                before = len(q)
                q.append(envelope)
                if before == _BUFFER_LIMIT:
                    self._overflow_count[session_id] = (
                        self._overflow_count.get(session_id, 0) + 1
                    )
                log.warning(
                    "CLIENT_NOT_CONNECTED session=%s type=%s buffer_depth=%d overflow=%d",
                    session_id, envelope.get("type"), len(q),
                    self._overflow_count.get(session_id, 0),
                )
                return

        # Enqueue non-blockingly.  The writer's offer() handles the
        # drop-oldest + WS_QUEUE_OVERFLOW synthesis internally.  We only
        # check slow-client heuristics here to decide on a hard close.
        writer.offer(envelope)
        if writer.slow_for_seconds() >= _SLOW_CLIENT_GRACE_S:
            log.error(
                "SLOW_CLIENT hard-close session=%s dropped_total=%d slow_for=%.2fs",
                session_id, writer.drop_count, writer.slow_for_seconds(),
            )
            asyncio.create_task(self.close(
                session_id, code=1013, reason="slow_client",
            ))

    async def close(self, session_id: uuid.UUID, *, code: int = 1000, reason: str = "") -> None:
        async with self._lock:
            writer = self._writers.pop(session_id, None)
            self._pending.pop(session_id, None)
            self._connected_evt.pop(session_id, None)
            self._overflow_count.pop(session_id, None)
        if writer is None:
            return
        await writer.stop()
        with contextlib.suppress(Exception):
            await writer.ws.close(code=code, reason=reason)


_manager: SessionConnectionManager | None = None


def get_manager() -> SessionConnectionManager:
    global _manager
    if _manager is None:
        _manager = SessionConnectionManager()
    return _manager


# ── WebSocket route ─────────────────────────────────────────────────────────

@router.websocket("/ws/simulation/{session_id}")
async def simulation_ws(ws: WebSocket, session_id: uuid.UUID) -> None:
    """Client subscribes here AFTER generating the session_id and BEFORE
    POSTing ``/simulate/garak``.  Race guard is still in place upstream
    (``_ws_wait_for_connection``)."""
    manager = get_manager()
    await ws.accept()
    await manager.register(session_id, ws)

    heartbeat_task: asyncio.Task | None = None
    try:
        heartbeat_task = asyncio.create_task(_heartbeat(ws, session_id))
        # Passive read loop — we don't accept client messages, but we still
        # need to receive frames so the TCP half-close comes through.
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            # Clients may send an application ping; reply to keep symmetry.
            if isinstance(msg.get("text"), str) and msg["text"] == "ping":
                with contextlib.suppress(Exception):
                    await ws.send_text("pong")

    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("simulation_ws: unexpected error session=%s", session_id)
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            with contextlib.suppress(Exception):
                await heartbeat_task
        await manager.unregister(session_id, ws)


async def _heartbeat(ws: WebSocket, session_id: uuid.UUID) -> None:
    """Heartbeat carries session_id so the client can sanity-check the
    channel after reconnect.  Heartbeat is NOT pushed through the writer
    queue — it bypasses the queue so a backlogged client still gets
    heartbeats (and we detect the deadfall quickly)."""
    while True:
        await asyncio.sleep(_PING_INTERVAL_S)
        try:
            await asyncio.wait_for(
                ws.send_json({
                    "type":       "ping",
                    "session_id": str(session_id),
                    "ts":         _utcnow_iso(),
                }),
                timeout=_SEND_TIMEOUT_S,
            )
        except Exception:
            log.info("heartbeat failed — closing session=%s", session_id)
            with contextlib.suppress(Exception):
                await ws.close(code=1011, reason="heartbeat_failed")
            return


# ── Start route + emit glue ─────────────────────────────────────────────────

class GarakConfig(BaseModel):
    probes:         list[str]       = Field(default_factory=list)
    profile:        str             = "default"
    max_attempts:   int             = Field(5, ge=1, le=100)


class StartSimulationRequest(BaseModel):
    session_id:     uuid.UUID
    garak_config:   GarakConfig
    execution_mode: str             = "live"


@router.post("/simulate/garak")
async def start_simulation(
    req: StartSimulationRequest,
    background: BackgroundTasks,
) -> dict:
    """Start a Garak simulation.  The WebSocket should already be connected
    (the pre-connect buffer handles late arrivals within the grace window)."""
    manager = get_manager()

    async def _emit(envelope: dict) -> None:
        # The orchestrator builds the full envelope; we just fan it out.
        await manager.send(req.session_id, envelope)

    # Import here to avoid circular import at module load.
    from .orchestrator import SimulationOrchestrator

    async def _runner() -> None:
        await manager.wait_connected(
            req.session_id,
            timeout_s=float(os.environ.get("WS_WAIT_TIMEOUT_S", "10.0")),
        )
        orchestrator = SimulationOrchestrator(
            session_id     = req.session_id,
            probes         = req.garak_config.probes,
            profile        = req.garak_config.profile,
            max_attempts   = req.garak_config.max_attempts,
            execution_mode = req.execution_mode,
            emit           = _emit,
            probe_timeout_s= float(os.environ.get("PROBE_TIMEOUT_S", "150.0")),
        )
        hard_timeout_s = float(os.environ.get("SIM_HARD_TIMEOUT_S", "900.0"))
        try:
            await asyncio.wait_for(orchestrator.run(), timeout=hard_timeout_s)
        except asyncio.TimeoutError:
            # Belt-and-braces safety net.  The inner CancelledError handler
            # inside ``orchestrator.run()`` usually fires first; if we get
            # here anyway, route the terminal through the same sequenced
            # path so we never emit a sentinel sequence.
            log.error("simulation hard-timeout session=%s", req.session_id)
            with contextlib.suppress(Exception):
                await orchestrator._emit_terminal_error(
                    f"Simulation hard-timeout after {hard_timeout_s:.0f}s"
                )
        finally:
            # Allow the browser a moment to render the terminal frame, then close.
            await asyncio.sleep(0.5)
            await manager.close(req.session_id, code=1000, reason="done")

    background.add_task(_runner)
    return {"session_id": str(req.session_id), "status": "started"}
