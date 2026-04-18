"""
ws/simulation_ws.py
────────────────────
WebSocket alias route for simulation sessions.

/ws/simulation/{session_id} is functionally identical to
/ws/sessions/{session_id} — both use the same ConnectionManager singleton
that session_ws.py initialises via init_ws_layer().

We import _manager from session_ws directly rather than keeping a
separate reference; this avoids duplicated init logic in app.py.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from models.ws_event import WsConnectedFrame, WsPingFrame
import ws.session_ws as _session_ws   # singletons populated by lifespan

log = logging.getLogger("api.ws.simulation")

router = APIRouter(tags=["WebSocket"])

# Heartbeat interval matches session_ws.py
HEARTBEAT_INTERVAL: float = float(30)


@router.websocket("/ws/simulation/{session_id}")
async def simulation_events_ws(websocket: WebSocket, session_id: str) -> None:
    """
    Stream simulation events for the given session_id.
    Mirrors /ws/sessions/{session_id} using the same infrastructure.
    """
    manager = _session_ws._manager
    if manager is None:
        await websocket.close(code=1011, reason="WS layer not initialized")
        return

    # Accept + register
    queue: asyncio.Queue[dict] = await manager.connect(session_id, websocket)
    log.info("simulation_ws_open session_id=%s client=%s", session_id, websocket.client)

    # Send "connected" confirmation
    await websocket.send_text(
        WsConnectedFrame(
            session_id=session_id,
            message=f"Streaming simulation events for session {session_id}",
        ).model_dump_json()
    )

    try:
        # Main event loop
        while True:
            try:
                event_dict = await asyncio.wait_for(
                    queue.get(),
                    timeout=HEARTBEAT_INTERVAL,
                )
            except asyncio.TimeoutError:
                # No event within the window — send heartbeat
                if websocket.client_state == WebSocketState.CONNECTED:
                    try:
                        await websocket.send_text(WsPingFrame().model_dump_json())
                    except Exception:
                        break
                continue

            if websocket.client_state != WebSocketState.CONNECTED:
                break

            try:
                await websocket.send_text(event_dict)
                log.debug(
                    "simulation_event_sent session_id=%s",
                    session_id,
                )
            except Exception as exc:
                log.info(
                    "simulation_send_error session_id=%s error=%s — closing",
                    session_id,
                    exc,
                )
                break

    except WebSocketDisconnect as exc:
        log.info("simulation_ws_disconnect session_id=%s code=%s", session_id, exc.code)
    except Exception as exc:
        log.exception("simulation_ws_error session_id=%s error=%s", session_id, exc)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        # Cleanup — always runs
        await manager.disconnect(session_id, websocket)
        log.info(
            "simulation_ws_closed session_id=%s",
            session_id,
        )
