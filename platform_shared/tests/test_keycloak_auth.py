"""Tests for platform_shared.keycloak_auth"""
import time, json, base64, pytest
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
from jose import jwt as jose_jwt
from jose.utils import long_to_base64

# Generate a throwaway RS256 key pair for tests
_private_key = rsa.generate_private_key(
    public_exponent=65537, key_size=2048, backend=default_backend()
)
_pub_numbers = _private_key.public_key().public_numbers()

def _make_jwks():
    n = long_to_base64(_pub_numbers.n).decode()
    e = long_to_base64(_pub_numbers.e).decode()
    return {"keys": [{"kty": "RSA", "use": "sig", "alg": "RS256",
                       "kid": "test-key", "n": n, "e": e}]}

def _make_token(claims_extra=None, key=None):
    key = key or _private_key
    now = int(time.time())
    claims = {"sub": "u1", "iss": "http://keycloak/realms/aispm",
               "aud": "aispm-ui", "iat": now, "exp": now + 60,
               "realm_access": {"roles": ["spm:admin"]}}
    if claims_extra:
        claims.update(claims_extra)
    return jose_jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})


@pytest.fixture(autouse=True)
def patch_jwks():
    with patch("platform_shared.keycloak_auth._fetch_jwks", return_value=_make_jwks()):
        import platform_shared.keycloak_auth as m
        if hasattr(m._fetch_jwks, "cache_clear"):
            m._fetch_jwks.cache_clear()
        yield


def test_valid_token_decoded():
    from platform_shared.keycloak_auth import decode_token
    tok = _make_token()
    claims = decode_token(tok, audience="aispm-ui", issuer="http://keycloak/realms/aispm")
    assert claims["sub"] == "u1"
    assert "spm:admin" in claims["roles"]


def test_wrong_audience_rejected():
    from platform_shared.keycloak_auth import decode_token
    tok = _make_token()
    with pytest.raises(Exception):
        decode_token(tok, audience="wrong-client", issuer="http://keycloak/realms/aispm")


def test_wrong_issuer_rejected():
    from platform_shared.keycloak_auth import decode_token
    tok = _make_token()
    with pytest.raises(Exception):
        decode_token(tok, audience="aispm-ui", issuer="http://evil.example.com")


def test_expired_token_rejected():
    from platform_shared.keycloak_auth import decode_token
    tok = _make_token({"exp": int(time.time()) - 10})
    with pytest.raises(Exception):
        decode_token(tok, audience="aispm-ui", issuer="http://keycloak/realms/aispm")


def test_unsigned_token_rejected():
    from platform_shared.keycloak_auth import decode_token
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({
        "sub": "evil", "aud": "aispm-ui", "iss": "http://keycloak/realms/aispm",
        "exp": int(time.time()) + 60
    }).encode()).rstrip(b"=").decode()
    unsigned_tok = f"{header}.{payload}."
    with pytest.raises(Exception):
        decode_token(unsigned_tok, audience="aispm-ui", issuer="http://keycloak/realms/aispm")


def test_roles_extracted_from_realm_access():
    from platform_shared.keycloak_auth import decode_token
    tok = _make_token({"realm_access": {"roles": ["spm:admin", "spm:auditor"]}})
    claims = decode_token(tok, audience="aispm-ui", issuer="http://keycloak/realms/aispm")
    assert "spm:admin" in claims["roles"]
    assert "spm:auditor" in claims["roles"]
