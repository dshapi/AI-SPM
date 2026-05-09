"""Tests that both WebSocket endpoints reject unauthenticated connections."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import JWTError

# ── session WebSocket ─────────────────────────────────────────────────────────
from services.api.ws.session_ws import router as session_router

session_app = FastAPI()
session_app.include_router(session_router)
session_client = TestClient(session_app)


def test_session_ws_without_token_returns_error():
    with session_client.websocket_connect("/ws/sessions/test") as ws:
        data = ws.receive_json()
        assert data.get("error") == "unauthorized"


def test_session_ws_with_invalid_token_returns_error():
    with patch("platform_shared.keycloak_auth.decode_token",
               side_effect=JWTError("bad")):
        with session_client.websocket_connect(
                "/ws/sessions/test?token=bad.tok.en") as ws:
            data = ws.receive_json()
            assert data.get("error") == "unauthorized"


# ── simulation WebSocket ──────────────────────────────────────────────────────
from services.api.ws.simulation_ws import router as sim_router

sim_app = FastAPI()
sim_app.include_router(sim_router)
sim_client = TestClient(sim_app)


def test_simulation_ws_without_token_returns_error():
    with sim_client.websocket_connect("/ws/simulation/test") as ws:
        data = ws.receive_json()
        assert data.get("error") == "unauthorized"


def test_simulation_ws_with_invalid_token_returns_error():
    with patch("platform_shared.keycloak_auth.decode_token",
               side_effect=JWTError("bad")):
        with sim_client.websocket_connect(
                "/ws/simulation/test?token=bad.tok.en") as ws:
            data = ws.receive_json()
            assert data.get("error") == "unauthorized"
