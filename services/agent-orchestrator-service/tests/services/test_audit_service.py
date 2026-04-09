# tests/services/test_audit_service.py
import pytest
from services.audit_service import AuditService

svc = AuditService(tenant_id="t1", component="test")

@pytest.mark.asyncio
async def test_emit_audit_does_not_raise():
    # Must not raise even if Kafka is unavailable (falls back to stdout)
    await svc.emit("session_created", session_id="sess-1", principal="user-1")

@pytest.mark.asyncio
async def test_emit_security_alert_does_not_raise():
    await svc.security_alert(
        "secret_in_output",
        ttp_codes=["AML.T0048"],
        session_id="sess-1",
        principal="user-1",
    )

def test_audit_service_has_tenant_and_component():
    assert svc.tenant_id == "t1"
    assert svc.component == "test"

@pytest.mark.asyncio
async def test_emit_with_details_does_not_raise():
    await svc.emit(
        "risk_scored",
        session_id="s1",
        principal="u1",
        severity="warning",
        details={"score": 0.85, "tier": "HIGH"},
        ttp_codes=["AML.T0051"],
    )

@pytest.mark.asyncio
async def test_emit_minimal_args():
    # All optional args omitted
    await svc.emit("test_event")
