# tests/clients/test_output_scanner.py
import pytest
from clients.output_scanner import OutputScanner, ScanResult

scanner = OutputScanner(guard_base_url=None, llm_scan_enabled=False)

def test_clean_text_passes():
    r = scanner.scan("The answer is 42.")
    assert r.pii_types == []
    assert r.secret_types == []
    assert r.verdict == "allow"

def test_ssn_detected():
    r = scanner.scan("User SSN: 123-45-6789")
    assert "ssn" in r.pii_types

def test_api_key_detected():
    r = scanner.scan("api_key=sk-abc123456789abcdefghij")
    assert len(r.secret_types) > 0

def test_pem_key_detected():
    r = scanner.scan("-----BEGIN PRIVATE KEY-----\nMIIEvAIBAD...")
    assert "pem_private_key" in r.secret_types

def test_jwt_detected():
    fake_jwt = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1c2VyMSJ9.fakesigfakesigfakesig"
    r = scanner.scan(fake_jwt)
    assert "jwt_token" in r.secret_types

def test_scan_result_has_required_fields():
    r = scanner.scan("test")
    assert hasattr(r, "verdict")
    assert hasattr(r, "pii_types")
    assert hasattr(r, "secret_types")
    assert hasattr(r, "scan_notes")

def test_has_pii_property():
    r = scanner.scan("User SSN: 123-45-6789")
    assert r.has_pii is True

def test_has_secrets_property():
    r = scanner.scan("-----BEGIN PRIVATE KEY-----\nABC")
    assert r.has_secrets is True

def test_clean_text_no_pii_no_secrets():
    r = scanner.scan("Paris is the capital of France.")
    assert r.has_pii is False
    assert r.has_secrets is False

def test_redact_pii_replaces_ssn():
    redacted = OutputScanner.redact_pii("SSN: 123-45-6789")
    assert "123-45-6789" not in redacted
    assert "REDACTED" in redacted

@pytest.mark.asyncio
async def test_scan_async_clean_text():
    r = await scanner.scan_async("Hello world")
    assert r.verdict == "allow"
