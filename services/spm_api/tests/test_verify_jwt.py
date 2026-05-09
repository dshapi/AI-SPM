"""Tests that verify_jwt enforces audience claim."""
import pytest, os
from unittest.mock import patch
from fastapi import HTTPException


def test_wrong_audience_returns_401(monkeypatch):
    """A token with wrong audience must be rejected with 401."""
    from jose import JWTError
    monkeypatch.setattr(
        "platform_shared.keycloak_auth.decode_token",
        lambda token, **kw: (_ for _ in ()).throw(JWTError("Invalid audience"))
    )
    from services.spm_api.app import verify_jwt
    with pytest.raises(HTTPException) as exc_info:
        import asyncio
        asyncio.run(verify_jwt.__wrapped__("Bearer bad.aud.token") if hasattr(verify_jwt, '__wrapped__') else verify_jwt("Bearer bad.aud.token"))
    assert exc_info.value.status_code == 401


def test_missing_token_returns_401():
    """No Authorization header must return 401."""
    from services.spm_api.app import verify_jwt
    with pytest.raises(HTTPException) as exc_info:
        verify_jwt(None)
    assert exc_info.value.status_code == 401


def test_valid_token_returns_claims(monkeypatch):
    """A valid token must return claims dict."""
    monkeypatch.setattr(
        "platform_shared.keycloak_auth.decode_token",
        lambda token, **kw: {"sub": "u1", "roles": ["spm:admin"],
                              "realm_access": {"roles": ["spm:admin"]}}
    )
    from services.spm_api.app import verify_jwt
    result = verify_jwt("Bearer valid.token.here")
    assert result["sub"] == "u1"
    assert "spm:admin" in result["roles"]
