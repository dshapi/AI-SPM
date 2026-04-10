"""
models/ws_event.py
──────────────────
Standardized outbound WebSocket message contract.

Every frame the server sends to a connected browser is serialized from
one of these models, guaranteeing a stable, typed wire format regardless
of which Kafka topic the event originated from.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class WsEvent(BaseModel):
    """
    Live Kafka event forwarded to a browser WebSocket connection.

    Fields
    ------
    session_id      UUID of the AI agent session being watched.
    event_type      Kafka event type string (e.g. "risk.calculated").
    source_service  Originating microservice ("api", "posture-engine", …).
    timestamp       ISO-8601 string from the originating service.
    payload         Remaining event fields verbatim from Kafka.
    """

    session_id: str
    event_type: str
    source_service: str
    timestamp: str
    payload: dict[str, Any] = Field(default_factory=dict)


class WsPingFrame(BaseModel):
    """Heartbeat frame sent every ~30 s to keep load-balancer connections alive."""

    type: Literal["ping"] = "ping"


class WsConnectedFrame(BaseModel):
    """Sent immediately after the WebSocket handshake is accepted."""

    type: Literal["connected"] = "connected"
    session_id: str
    message: str
