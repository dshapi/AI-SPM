"""
tests/test_kafka_pii_exclusion.py
───────────────────────────────────
Verifies that PII fields (user_email, user_name) are:
  - PRESENT  in the full model_dump() used by the in-memory store → admin UI
  - ABSENT   from model_dump_kafka() used by _make_envelope → Kafka wire format

Also verifies the KafkaSafe mixin contract for future payload types.

No external dependencies, no I/O.  Run with:
    pytest tests/test_kafka_pii_exclusion.py -v
"""
from __future__ import annotations

import json
from uuid import uuid4

import pytest

from schemas.events import KafkaSafe, PromptReceivedPayload


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_payload(**overrides) -> PromptReceivedPayload:
    defaults = dict(
        session_id=uuid4(),
        agent_id="chat-agent",
        user_id="user-123",
        user_email="dany.shapiro@gmail.com",
        user_name="Dany Shapiro",
        tenant_id="acme",
        prompt_hash="abc123",
        prompt_len=42,
        tools=[],
    )
    defaults.update(overrides)
    return PromptReceivedPayload(**defaults)


# ─────────────────────────────────────────────────────────────────────────────
# Core PII exclusion contract
# ─────────────────────────────────────────────────────────────────────────────

class TestPromptReceivedPIIExclusion:
    def test_full_dump_contains_pii(self):
        """model_dump() (→ in-memory store / UI) must include PII fields."""
        payload = _make_payload()
        data = payload.model_dump(mode="json")
        assert data["user_email"] == "dany.shapiro@gmail.com"
        assert data["user_name"] == "Dany Shapiro"

    def test_kafka_dump_strips_email(self):
        """model_dump_kafka() (→ Kafka envelope) must NOT include user_email."""
        payload = _make_payload()
        data = payload.model_dump_kafka()
        assert "user_email" not in data, (
            f"user_email must be stripped from Kafka payload, got: {data}"
        )

    def test_kafka_dump_strips_name(self):
        """model_dump_kafka() (→ Kafka envelope) must NOT include user_name."""
        payload = _make_payload()
        data = payload.model_dump_kafka()
        assert "user_name" not in data, (
            f"user_name must be stripped from Kafka payload, got: {data}"
        )

    def test_kafka_dump_retains_non_pii_fields(self):
        """Non-PII fields must survive the Kafka serialization."""
        payload = _make_payload()
        data = payload.model_dump_kafka()
        assert data["user_id"] == "user-123"
        assert data["agent_id"] == "chat-agent"
        assert data["tenant_id"] == "acme"
        assert data["prompt_hash"] == "abc123"
        assert data["prompt_len"] == 42

    def test_kafka_dump_with_none_pii(self):
        """Payload with no PII values still serializes cleanly."""
        payload = _make_payload(user_email=None, user_name=None)
        data = payload.model_dump_kafka()
        assert "user_email" not in data
        assert "user_name" not in data
        assert data["user_id"] == "user-123"

    def test_pii_fields_declaration(self):
        """_kafka_pii_fields must declare the expected fields."""
        assert "user_email" in PromptReceivedPayload._kafka_pii_fields
        assert "user_name"  in PromptReceivedPayload._kafka_pii_fields


# ─────────────────────────────────────────────────────────────────────────────
# _make_envelope integration
# ─────────────────────────────────────────────────────────────────────────────

class TestMakeEnvelopePIIExclusion:
    def test_envelope_bytes_do_not_contain_email(self):
        """The raw Kafka bytes must not contain the user's email address."""
        from events.publisher import _make_envelope
        payload = _make_payload()
        envelope_bytes = _make_envelope(
            event_type="prompt.received",
            correlation_id="corr-1",
            session_id=payload.session_id,
            payload=payload,
            tenant_id="acme",
        )
        envelope_str = envelope_bytes.decode("utf-8")
        assert "dany.shapiro@gmail.com" not in envelope_str, (
            "Email found in Kafka envelope bytes — PII leak!"
        )

    def test_envelope_bytes_do_not_contain_name(self):
        """The raw Kafka bytes must not contain the user's display name."""
        from events.publisher import _make_envelope
        payload = _make_payload()
        envelope_bytes = _make_envelope(
            event_type="prompt.received",
            correlation_id="corr-1",
            session_id=payload.session_id,
            payload=payload,
            tenant_id="acme",
        )
        envelope_str = envelope_bytes.decode("utf-8")
        # "Dany Shapiro" should not appear; user_id ("user-123") is fine
        assert "Dany Shapiro" not in envelope_str, (
            "Display name found in Kafka envelope bytes — PII leak!"
        )

    def test_envelope_is_valid_json(self):
        """Envelope bytes must be valid JSON after PII stripping."""
        from events.publisher import _make_envelope
        payload = _make_payload()
        envelope_bytes = _make_envelope(
            event_type="prompt.received",
            correlation_id="corr-1",
            session_id=payload.session_id,
            payload=payload,
        )
        parsed = json.loads(envelope_bytes)
        assert parsed["event_type"] == "prompt.received"
        assert "data" in parsed
        assert "user_email" not in parsed["data"]


# ─────────────────────────────────────────────────────────────────────────────
# KafkaSafe mixin contract (generic)
# ─────────────────────────────────────────────────────────────────────────────

class TestKafkaSafeMixin:
    def test_base_mixin_excludes_nothing_by_default(self):
        """A KafkaSafe subclass with no override strips nothing."""
        class MyPayload(KafkaSafe):
            name: str
            value: int

        p = MyPayload(name="test", value=42)
        assert p.model_dump_kafka() == {"name": "test", "value": 42}

    def test_mixin_strips_declared_fields(self):
        """A subclass declaring _kafka_pii_fields has them stripped."""
        from typing import ClassVar, FrozenSet

        class SensitivePayload(KafkaSafe):
            _kafka_pii_fields: ClassVar[FrozenSet[str]] = frozenset({"secret"})
            public: str
            secret: str

        p = SensitivePayload(public="hello", secret="s3kr3t")
        kafka_data = p.model_dump_kafka()
        assert "secret" not in kafka_data
        assert kafka_data["public"] == "hello"

    def test_mixin_full_dump_still_includes_pii(self):
        """model_dump() is unaffected — KafkaSafe only changes model_dump_kafka()."""
        from typing import ClassVar, FrozenSet

        class SensitivePayload(KafkaSafe):
            _kafka_pii_fields: ClassVar[FrozenSet[str]] = frozenset({"secret"})
            public: str
            secret: str

        p = SensitivePayload(public="hello", secret="s3kr3t")
        full = p.model_dump()
        assert full["secret"] == "s3kr3t"
        assert full["public"] == "hello"
