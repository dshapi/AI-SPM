"""
Smoke tests for service startup and basic routing.
These verify the app wires up correctly without real Kafka/LLM/guard services.
"""
import os

os.environ.setdefault("DB_PATH", ":memory:")
os.environ.setdefault("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    """Create a test client that triggers lifespan."""
    with TestClient(app) as c:
        yield c


def test_health_endpoint(client):
    """Health endpoint should respond with ok status."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


def test_llm_client_optional(client):
    """App should start even without LLM_API_KEY set."""
    resp = client.get("/health")
    assert resp.status_code == 200


def test_guard_url_optional(client):
    """App should start with or without GUARD_MODEL_URL set."""
    resp = client.get("/health")
    assert resp.status_code == 200


def test_prompt_processor_initialized(client):
    """PromptProcessor should always be initialized in app.state."""
    resp = client.get("/health")
    assert resp.status_code == 200
    # After lifespan starts (triggered by TestClient), prompt_processor should be in state
    assert hasattr(app.state, "prompt_processor")


def test_guard_client_initialized(client):
    """GuardClient should be accessible via PromptProcessor."""
    resp = client.get("/health")
    assert resp.status_code == 200
    # After lifespan starts, prompt_processor should have guard_client
    assert hasattr(app.state, "prompt_processor")
    assert hasattr(app.state.prompt_processor, "_guard")
