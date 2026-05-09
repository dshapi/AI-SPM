"""Tests that _decode_token verifies the JWT signature."""
import base64, json, time, pytest


def _unsigned_token():
    """Craft a token with alg=none — must be rejected after fix."""
    h = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
    p = base64.urlsafe_b64encode(json.dumps({
        "sub": "attacker", "iss": "http://keycloak.local:8180/realms/aispm",
        "aud": "aispm-ui", "exp": int(time.time()) + 3600,
        "realm_access": {"roles": ["spm:admin"]}
    }).encode()).rstrip(b"=").decode()
    return f"{h}.{p}."


def test_unsigned_token_not_accepted():
    """alg=none token must be fully rejected — result must be empty dict."""
    from dependencies.auth import _decode_token
    result = _decode_token(_unsigned_token())
    # Vulnerable code returns the raw claims (sub, realm_access, etc.).
    # Fixed code must return {} — signature rejected, no claims leaked.
    assert result == {}, (
        f"Unsigned token was accepted and returned claims: {result!r}. "
        "Signature verification is not being enforced."
    )


def test_missing_token_returns_empty():
    from dependencies.auth import _decode_token
    assert _decode_token("") == {}


def test_garbage_token_returns_empty():
    from dependencies.auth import _decode_token
    assert _decode_token("not.a.token") == {}
