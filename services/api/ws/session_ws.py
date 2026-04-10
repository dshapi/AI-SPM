"""
ws/session_ws.py
──────────────────
WebSocket endpoint: /ws/sessions/{session_id}

Protocol
────────
1. Client opens:   ws://api-host/ws/sessions/<uuid>
2. Server sends:   {"type": "connected", "session_id": "...", "message": "..."}
3. Server streams: WsEvent JSON frames as Kafka events arrive
4. Server sends:   {"type": "ping"} every HEARTBEAT_INTERVAL seconds
5. Client sends:   {"type": "pong"} — ignored, but keeps connection alive
6. Either side closes the connection normally when done

Authentication
──────────────
This reference implementation does not enforce auth at the WebSocket layer.
In production, validate the upgrade request before calling ws.accept():

  token = websocket.query_params.get("token")
  # or: token = websocket.headers.get("authorization", "").removeprefix("Bearer ")
  claims = validate_jwt_token(token)   # raises HTTPException on failure

Then pass identity/tenant_id into the handler so the endpoint can scope
topic subscriptions and log the caller correctly.

Lifecycle
─────────
  connect():
    1. Accept WS, create bounded queue, register with ConnectionManager.
    2. Subscribe queue+loop to SessionEventConsumer (Kafka fan-out).
    3. Send "connected" frame.
    4. Launch concurrent _client_reader task to detect disconnects & pongs.
    5. Loop: wait on queue → validate WsEvent → send JSON frame.
       Heartbeat fires inline when queue.get() times out.

  disconnect (any cause):
    1. Cancel _client_reader task.
    2. Unsubscribe from SessionEventConsumer.
    3. Remove from ConnectionManager registry.
    4. Log closure.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from consumers.session_event_consumer import SessionEventConsumer
from models.ws_event import WsConnectedFrame, WsEvent, WsPingFrame
from ws.connection_manager import ConnectionManager

log = logging.getLogger("api.ws.session_ws")

router = APIRouter(tags=["WebSocket"])

# ── Tuneables ─────────────────────────────────────────────────────────────────

# Seconds between server→client heartbeat pings
HEARTBEAT_INTERVAL: float = float(30)

# ── Module-level singletons — injected by lifespan ───────────────────────────

_manager: Optional[ConnectionManager] = None
_consumer: Optional[SessionEventConsumer] = None


def init_ws_layer(
    manager: ConnectionManager,
    consumer: SessionEventConsumer,
) -> None:
    """
    Wire the singletons created in app.py's lifespan into this module.
    Must be called once during startup before any WS connections are accepted.
    """
    global _manager, _consumer
    _manager = manager
    _consumer = consumer
    log.info("ws_layer_initialized")


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@router.websocket("/ws/sessions/{session_id}")
async def ws_session(websocket: WebSocket, session_id: str) -> None:
    """
    Stream live Kafka events for *session_id* to the connected browser.

    Each message is validated against WsEvent before being forwarded so
    malformed Kafka payloads never reach the browser as raw noise.
    """
    if _manager is None or _consumer is None:
        # lifespan not complete — refuse the upgrade cleanly
        await websocket.close(code=1011, reason="WS layer not initialized")
        return

    # ── Accept + register ─────────────────────────────────────────────────────
    queue: asyncio.Queue[dict] = await _manager.connect(session_id, websocket)
    loop = asyncio.get_running_loop()
    _consumer.subscribe(session_id, loop, queue)

    log.info("ws_session_open session_id=%s client=%s", session_id, websocket.client)

    # ── Client reader — detects disconnects and handles pong ──────────────────
    disconnect_event = asyncio.Event()

    async def _client_reader() -> None:
        """Drain incoming client frames.  Sets disconnect_event on any error."""
        try:
            while not disconnect_event.is_set():
                raw = await websocket.receive_text()
                try:
                    msg = json.loads(raw)
                    if msg.get("type") == "pong":
                        pass  # expected heartbeat reply — no action needed
                    else:
                        log.debug(
                            "ws_client_msg session_id=%s type=%s",
                            session_id,
                            msg.get("type", "?"),
                        )
                except (json.JSONDecodeError, AttributeError):
                    pass  # non-JSON client frame — ignore
        except WebSocketDisconnect:
            log.info("ws_client_disconnect session_id=%s", session_id)
        except Exception as exc:
            log.debug("ws_client_reader_exit session_id=%s reason=%s", session_id, exc)
        finally:
            disconnect_event.set()

    reader_task = asyncio.create_task(_client_reader(), name=f"ws-reader-{session_id}")

    try:
        # ── Send "connected" confirmation ─────────────────────────────────────
        await _send_json(
            websocket,
            WsConnectedFrame(
                session_id=session_id,
                message=f"Streaming live events for session {session_id}",
            ).model_dump(),
        )

        # ── Main event loop ───────────────────────────────────────────────────
        while not disconnect_event.is_set():
            # Wait for next Kafka event; timeout triggers a heartbeat instead
            try:
                event_dict = await asyncio.wait_for(
                    queue.get(),
                    timeout=HEARTBEAT_INTERVAL,
                )
            except asyncio.TimeoutError:
                # No Kafka event within the window — send heartbeat
                if websocket.client_state == WebSocketState.CONNECTED:
                    try:
                        await _send_json(websocket, WsPingFrame().model_dump())
                    except Exception:
                        break
                continue

            # Validate against the WsEvent contract before forwarding
            try:
                validated = WsEvent(**event_dict)
            except Exception as exc:
                log.warning(
                    "ws_event_validation_error session_id=%s error=%s payload=%s",
                    session_id,
                    exc,
                    event_dict,
                )
                continue

            if websocket.client_state != WebSocketState.CONNECTED:
                break

            try:
                await websocket.send_text(validated.model_dump_json())
                log.debug(
                    "ws_event_sent session_id=%s event_type=%s",
                    session_id,
                    validated.event_type,
                )
            except Exception as exc:
                log.info(
                    "ws_send_error session_id=%s error=%s — closing",
                    session_id,
                    exc,
                )
                break

    except WebSocketDisconnect as exc:
        log.info("ws_session_disconnect session_id=%s code=%s", session_id, exc.code)
    except Exception as exc:
        log.exception("ws_session_error session_id=%s error=%s", session_id, exc)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        # ── Cleanup — always runs ─────────────────────────────────────────────
        disconnect_event.set()
        reader_task.cancel()
        try:
            await reader_task
        except asyncio.CancelledError:
            pass

        _consumer.unsubscribe(session_id, queue)
        await _manager.disconnect(session_id, websocket)

        log.info(
            "ws_session_closed session_id=%s remaining_sessions=%d",
            session_id,
            _consumer.active_session_count,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _send_json(ws: WebSocket, data: dict) -> None:
    """Serialize *data* to JSON and send as a text frame."""
    await ws.send_text(json.dumps(data, default=str))
