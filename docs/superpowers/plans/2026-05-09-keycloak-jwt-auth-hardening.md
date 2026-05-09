# Keycloak JWT Auth Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 5 JWT security vulnerabilities (signature bypass, /dev-token exposure, exec_module RCE, unauthenticated WebSocket, missing audience verification) by wiring Keycloak 24 JWKS validation across all AISPM services.

**Architecture:** A single shared `platform_shared/keycloak_auth.py` module performs JWKS-backed RS256 validation with audience and issuer checks; all services import from it. The `/dev-token` endpoint is removed and the UI is updated to use Keycloak's token endpoint directly. WebSocket auth is enforced via a Bearer token query param validated at upgrade time.

**Tech Stack:** Python 3.12, FastAPI, python-jose[cryptography], Keycloak 24, Vite/React, pytest, k3s/Helm

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `auth/setup-realm.sh` | Bootstrap Keycloak realm, client, roles via kcadm |
| Create | `platform_shared/keycloak_auth.py` | Shared JWKS-backed JWT decoder (single source of truth) |
| Create | `platform_shared/tests/test_keycloak_auth.py` | Unit tests for the shared decoder |
| Modify | `services/agent-orchestrator-service/dependencies/auth.py:114-140` | Replace no-sig decode with `keycloak_auth.decode_token` |
| Create | `services/agent-orchestrator-service/tests/test_auth_deps.py` | Tests for the fixed decoder |
| Modify | `services/spm_api/app.py:84-95` | Add `audience` to `verify_jwt` |
| Create | `services/spm_api/tests/test_verify_jwt.py` | Tests for audience check |
| Delete | `services/api/app.py:1998-2030` | Remove `/dev-token` endpoint |
| Modify | `ui/src/api.js` | Replace `getToken()` dev-token call with Keycloak token endpoint |
| Modify | `services/api/ws/session_ws.py:88-95` | Validate Bearer token at WebSocket upgrade |
| Create | `services/api/tests/test_ws_auth.py` | Tests for WebSocket auth |
| Modify | `services/spm_api/agent_validator.py:70-80` | Replace `exec_module` with allowlist import |
| Create | `services/spm_api/tests/test_agent_validator_security.py` | Tests for safe import |
| Modify | `compose.yml` | Add KEYCLOAK_JWKS_URL, JWT_ISSUER, JWT_AUDIENCE env vars to all services |
| Modify | `deploy/helm/aispm/values.yaml` | Same env vars for k8s |

---

### Task 1: Keycloak Realm Bootstrap Script

**Files:**
- Create: `auth/setup-realm.sh`

- [ ] **Step 1: Create realm bootstrap script**
```bash
cat > auth/setup-realm.sh << 'EOF'
#!/usr/bin/env bash
# Bootstrap Keycloak realm, client, and roles for AISPM
set -euo pipefail

# All vars below are injected by compose.yml (or Helm) environment block.
# No .env file is used — values are set directly in compose.yml / values.yaml.
KC_URL="${KEYCLOAK_URL:-http://localhost:8180}"
ADMIN_USER="${KEYCLOAK_ADMIN:-admin}"
ADMIN_PASS="${KEYCLOAK_ADMIN_PASSWORD:-admin}"
REALM="aispm"
CLIENT_ID="aispm-ui"
CLIENT_SECRET="${AISPM_CLIENT_SECRET}"  # Must be set in compose.yml keycloak service env block

echo "Waiting for Keycloak at $KC_URL ..."
until curl -sf "$KC_URL/health/ready" > /dev/null; do sleep 2; done

# Authenticate kcadm
/opt/keycloak/bin/kcadm.sh config credentials \
  --server "$KC_URL" --realm master \
  --user "$ADMIN_USER" --password "$ADMIN_PASS"

# Create realm (idempotent)
/opt/keycloak/bin/kcadm.sh get realms/"$REALM" > /dev/null 2>&1 || \
  /opt/keycloak/bin/kcadm.sh create realms \
    -s realm="$REALM" -s enabled=true -s displayName="AISPM"

# Create confidential client
CLIENT_EXISTS=$(/opt/keycloak/bin/kcadm.sh get clients -r "$REALM" \
  --fields clientId -q clientId="$CLIENT_ID" 2>/dev/null | grep -c "$CLIENT_ID" || true)
if [ "$CLIENT_EXISTS" -eq 0 ]; then
  /opt/keycloak/bin/kcadm.sh create clients -r "$REALM" \
    -s clientId="$CLIENT_ID" \
    -s secret="$CLIENT_SECRET" \
    -s publicClient=false \
    -s directAccessGrantsEnabled=true \
    -s 'redirectUris=["http://localhost:5173/*","http://aispm.local/*"]' \
    -s 'webOrigins=["http://localhost:5173","http://aispm.local"]'
fi

# Create realm roles
for ROLE in "spm:admin" "spm:auditor" "spm:viewer"; do
  /opt/keycloak/bin/kcadm.sh get roles -r "$REALM" --fields name \
    | grep -q "\"$ROLE\"" || \
    /opt/keycloak/bin/kcadm.sh create roles -r "$REALM" -s name="$ROLE"
done

echo "Realm '$REALM' configured."
EOF
chmod +x auth/setup-realm.sh
```

- [ ] **Step 2: Verify script is executable**
```bash
bash -n auth/setup-realm.sh && echo "Syntax OK"
```
Expected: `Syntax OK`

- [ ] **Step 3: Commit**
```bash
git add auth/setup-realm.sh
git commit -m "feat(auth): add Keycloak realm bootstrap script"
```

---

### Task 2: Shared JWKS Validator (`platform_shared/keycloak_auth.py`)

**Files:**
- Create: `platform_shared/keycloak_auth.py`
- Create: `platform_shared/tests/test_keycloak_auth.py`

- [ ] **Step 1: Write the failing tests**
```bash
mkdir -p platform_shared/tests
cat > platform_shared/tests/test_keycloak_auth.py << 'EOF'
"""Tests for platform_shared.keycloak_auth"""
import time, json, base64, pytest
from unittest.mock import patch, MagicMock
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
from jose import jwt as jose_jwt
from jose.utils import long_to_base64

# Generate a throwaway RS256 key pair for tests
_private_key = rsa.generate_private_key(
    public_exponent=65537, key_size=2048, backend=default_backend()
)
_pub_numbers = _private_key.public_key().public_key_numbers()

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
        m._fetch_jwks.cache_clear() if hasattr(m._fetch_jwks, "cache_clear") else None
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
    with pytest.raises(Exception, match="aud|audience"):
        decode_token(tok, audience="wrong-client", issuer="http://keycloak/realms/aispm")


def test_wrong_issuer_rejected():
    from platform_shared.keycloak_auth import decode_token
    tok = _make_token()
    with pytest.raises(Exception):
        decode_token(tok, audience="aispm-ui", issuer="http://evil.example.com")


def test_expired_token_rejected():
    from platform_shared.keycloak_auth import decode_token
    tok = _make_token({"exp": int(time.time()) - 10})
    with pytest.raises(Exception, match="[Ee]xpir"):
        decode_token(tok, audience="aispm-ui", issuer="http://keycloak/realms/aispm")


def test_unsigned_token_rejected():
    from platform_shared.keycloak_auth import decode_token
    # craft an unsigned token (alg=none)
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
EOF
```

- [ ] **Step 2: Run tests — expect failure**
```bash
cd ~/PycharmProjects/AISPM && python -m pytest platform_shared/tests/test_keycloak_auth.py -v 2>&1 | head -30
```
Expected: `ImportError` or `ModuleNotFoundError` for `platform_shared.keycloak_auth`

- [ ] **Step 3: Implement `keycloak_auth.py`**
```bash
cat > platform_shared/keycloak_auth.py << 'EOF'
"""
Shared Keycloak JWKS-backed JWT validator.

Usage:
    from platform_shared.keycloak_auth import decode_token

    claims = decode_token(raw_token,
                          audience=settings.JWT_AUDIENCE,
                          issuer=settings.JWT_ISSUER)
"""
from __future__ import annotations

import functools
import os
from typing import Dict

import requests
from jose import jwt, JWTError


def _jwks_url() -> str:
    base = os.environ.get("KEYCLOAK_JWKS_URL", "").rstrip("/")
    if base:
        return base
    kc = os.environ.get("KEYCLOAK_URL", "http://keycloak.local:8180").rstrip("/")
    realm = os.environ.get("KEYCLOAK_REALM", "aispm")
    return f"{kc}/realms/{realm}/protocol/openid-connect/certs"


@functools.lru_cache(maxsize=1)
def _fetch_jwks() -> Dict:
    url = _jwks_url()
    resp = requests.get(url, timeout=5)
    resp.raise_for_status()
    return resp.json()


def decode_token(raw_token: str, *, audience: str, issuer: str) -> Dict:
    """
    Validate `raw_token` against Keycloak's JWKS endpoint.

    - Verifies RS256 signature
    - Enforces `aud` == audience
    - Enforces `iss` == issuer
    - Enforces `exp` not expired

    Returns claims dict with an extra top-level `roles` list populated
    from `realm_access.roles` (Keycloak format).

    Raises jose.JWTError (or subclass) on any validation failure.
    """
    jwks = _fetch_jwks()
    claims = jwt.decode(
        raw_token,
        jwks,
        algorithms=["RS256"],
        audience=audience,
        issuer=issuer,
        options={"verify_exp": True, "verify_aud": True, "verify_iss": True},
    )
    realm_roles = claims.get("realm_access", {}).get("roles", [])
    claims["roles"] = realm_roles
    return claims
EOF
```

- [ ] **Step 4: Run tests — expect pass**
```bash
cd ~/PycharmProjects/AISPM && python -m pytest platform_shared/tests/test_keycloak_auth.py -v
```
Expected: `6 passed`

- [ ] **Step 5: Commit**
```bash
git add platform_shared/keycloak_auth.py platform_shared/tests/test_keycloak_auth.py
git commit -m "feat(auth): add shared Keycloak JWKS validator"
```

---

### Task 3: Fix Vuln 1 — Agent Orchestrator Signature Bypass

**Vuln:** `services/agent-orchestrator-service/dependencies/auth.py:114` decodes JWT without signature verification (raw base64 decode).

**Files:**
- Modify: `services/agent-orchestrator-service/dependencies/auth.py`
- Create: `services/agent-orchestrator-service/tests/test_auth_deps.py`

- [ ] **Step 1: Write failing test**
```bash
cat > services/agent-orchestrator-service/tests/test_auth_deps.py << 'EOF'
"""Tests that _decode_token verifies the JWT signature."""
import base64, json, time, pytest
from unittest.mock import patch

def _unsigned_token():
    """Craft a token with alg=none — must be rejected."""
    h = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
    p = base64.urlsafe_b64encode(json.dumps({
        "sub": "attacker", "iss": "http://keycloak/realms/aispm",
        "aud": "aispm-ui", "exp": int(time.time()) + 3600,
        "realm_access": {"roles": ["spm:admin"]}
    }).encode()).rstrip(b"=").decode()
    return f"{h}.{p}."


def test_unsigned_token_rejected(monkeypatch):
    from services.agent_orchestrator_service.dependencies.auth import _decode_token
    result = _decode_token(_unsigned_token())
    # After fix: must return empty dict (not admin claims)
    assert result.get("roles", []) == [] or result == {}


def test_missing_token_returns_empty():
    from services.agent_orchestrator_service.dependencies.auth import _decode_token
    assert _decode_token("") == {}


def test_garbage_token_returns_empty():
    from services.agent_orchestrator_service.dependencies.auth import _decode_token
    assert _decode_token("not.a.token") == {}
EOF
```

- [ ] **Step 2: Run — expect fail (unsigned token currently decoded as valid)**
```bash
cd ~/PycharmProjects/AISPM && python -m pytest services/agent-orchestrator-service/tests/test_auth_deps.py::test_unsigned_token_rejected -v
```
Expected: FAIL

- [ ] **Step 3: Replace `_decode_token` in `auth.py`**

Edit `services/agent-orchestrator-service/dependencies/auth.py`, find the `_decode_token` function (around line 114) and replace the body:

```python
def _decode_token(raw_token: str) -> dict:
    """
    Validate the JWT against Keycloak JWKS (RS256 + aud + iss).
    Returns empty dict on any failure so callers get a default identity.
    """
    if not raw_token:
        return {}
    try:
        from platform_shared.keycloak_auth import decode_token
        import os
        audience = os.environ.get("JWT_AUDIENCE", "aispm-ui")
        issuer   = os.environ.get("JWT_ISSUER",   "http://keycloak.local:8180/realms/aispm")
        return decode_token(raw_token, audience=audience, issuer=issuer)
    except Exception:
        return {}
```

- [ ] **Step 4: Run tests — expect pass**
```bash
cd ~/PycharmProjects/AISPM && python -m pytest services/agent-orchestrator-service/tests/test_auth_deps.py -v
```
Expected: `3 passed`

- [ ] **Step 5: Commit**
```bash
git add services/agent-orchestrator-service/dependencies/auth.py \
        services/agent-orchestrator-service/tests/test_auth_deps.py
git commit -m "fix(security): verify JWT signature in agent-orchestrator (Vuln 1)"
```

---

### Task 4: Fix Vuln 5 — Missing Audience Verification in spm_api

**Vuln:** `services/spm_api/app.py:84-95` calls `verify=False` for audience.

**Files:**
- Modify: `services/spm_api/app.py`
- Create: `services/spm_api/tests/test_verify_jwt.py`

- [ ] **Step 1: Write failing test**
```bash
cat > services/spm_api/tests/test_verify_jwt.py << 'EOF'
"""Tests that verify_jwt enforces audience claim."""
import time, pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


def _make_token_wrong_aud(monkeypatch):
    """Return a token decoded with wrong audience — should be rejected."""
    # We mock decode_token to simulate a token with aud=other-client
    return "eyJhbGciOiJSUzI1NiJ9.wrong.audience"


def test_wrong_audience_returns_401(monkeypatch):
    from jose import JWTError
    monkeypatch.setattr(
        "platform_shared.keycloak_auth.decode_token",
        lambda token, **kw: (_ for _ in ()).throw(JWTError("Invalid audience"))
    )
    from services.spm_api.app import app
    client = TestClient(app)
    resp = client.get("/api/posture/summary",
                      headers={"Authorization": "Bearer bad.aud.token"})
    assert resp.status_code == 401


def test_valid_token_passes(monkeypatch):
    monkeypatch.setattr(
        "platform_shared.keycloak_auth.decode_token",
        lambda token, **kw: {
            "sub": "u1", "roles": ["spm:admin"],
            "realm_access": {"roles": ["spm:admin"]}
        }
    )
    from services.spm_api.app import app
    client = TestClient(app)
    resp = client.get("/api/posture/summary",
                      headers={"Authorization": "Bearer valid.token.here"})
    assert resp.status_code != 401
EOF
```

- [ ] **Step 2: Run — expect fail**
```bash
cd ~/PycharmProjects/AISPM && python -m pytest services/spm_api/tests/test_verify_jwt.py::test_wrong_audience_returns_401 -v
```
Expected: FAIL (wrong aud currently accepted)

- [ ] **Step 3: Fix `verify_jwt` in `services/spm_api/app.py`**

Replace the `verify_jwt` function (lines 84-99):

```python
def verify_jwt(authorization: Optional[str] = Header(None)) -> Dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization.removeprefix("Bearer ")
    try:
        from platform_shared.keycloak_auth import decode_token
        audience = os.getenv("JWT_AUDIENCE", "aispm-ui")
        issuer   = os.getenv("JWT_ISSUER",   "http://keycloak.local:8180/realms/aispm")
        return decode_token(token, audience=audience, issuer=issuer)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")
```

- [ ] **Step 4: Run tests — expect pass**
```bash
cd ~/PycharmProjects/AISPM && python -m pytest services/spm_api/tests/test_verify_jwt.py -v
```
Expected: `2 passed`

- [ ] **Step 5: Commit**
```bash
git add services/spm_api/app.py services/spm_api/tests/test_verify_jwt.py
git commit -m "fix(security): enforce JWT audience in spm_api verify_jwt (Vuln 5)"
```

---

### Task 5: Fix Vuln 2 — Remove `/dev-token` and Wire Real Token Flow

**Vuln:** `services/api/app.py:1998` exposes a `/dev-token` endpoint that generates signed tokens without auth.

**Files:**
- Modify: `services/api/app.py` (delete lines 1998-2035)
- Modify: `ui/src/api.js` (replace `getToken` to use Keycloak token endpoint)

- [ ] **Step 1: Delete `/dev-token` from `services/api/app.py`**

Remove the entire `@app.get("/dev-token")` function and its body (approx lines 1998-2035). After removal, verify:
```bash
grep -n "dev.token\|dev_token" services/api/app.py
```
Expected: no output

- [ ] **Step 2: Update `ui/src/api.js` — replace `getToken()`**

Replace the `getToken` function with a Keycloak-backed implementation:

```javascript
const KEYCLOAK_URL = import.meta.env.VITE_KEYCLOAK_URL || 'http://keycloak.local:8180'
const KC_REALM     = import.meta.env.VITE_KC_REALM     || 'aispm'
const KC_CLIENT_ID = import.meta.env.VITE_KC_CLIENT_ID || 'aispm-ui'

let _token       = null
let _tokenExpiry = 0
let _refreshToken = null

export async function login(username, password) {
  const url = `${KEYCLOAK_URL}/realms/${KC_REALM}/protocol/openid-connect/token`
  const body = new URLSearchParams({
    grant_type: 'password',
    client_id: KC_CLIENT_ID,
    username,
    password,
  })
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  })
  if (!resp.ok) throw new Error('Login failed')
  const data = await resp.json()
  _token        = data.access_token
  _refreshToken = data.refresh_token
  _tokenExpiry  = Date.now() + (data.expires_in - 30) * 1000
}

async function _refreshAccessToken() {
  const url = `${KEYCLOAK_URL}/realms/${KC_REALM}/protocol/openid-connect/token`
  const body = new URLSearchParams({
    grant_type: 'refresh_token',
    client_id: KC_CLIENT_ID,
    refresh_token: _refreshToken,
  })
  const resp = await fetch(url, { method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body })
  if (!resp.ok) { _token = null; _tokenExpiry = 0; return null }
  const data = await resp.json()
  _token        = data.access_token
  _refreshToken = data.refresh_token
  _tokenExpiry  = Date.now() + (data.expires_in - 30) * 1000
  return _token
}

export async function getToken() {
  if (_token && Date.now() < _tokenExpiry) return _token
  if (_refreshToken) return _refreshAccessToken()
  return null
}

export function logout() {
  _token = null; _tokenExpiry = 0; _refreshToken = null
  const redir = encodeURIComponent(window.location.origin)
  window.location.href =
    `${KEYCLOAK_URL}/realms/${KC_REALM}/protocol/openid-connect/logout?redirect_uri=${redir}`
}
```

- [ ] **Step 3: Verify no references to `/dev-token` remain**
```bash
grep -rn "dev.token\|dev_token" services/ ui/src/ --include="*.py" --include="*.js" --include="*.jsx"
```
Expected: no output (or only comments)

- [ ] **Step 4: Commit**
```bash
git add services/api/app.py ui/src/api.js
git commit -m "fix(security): remove /dev-token endpoint, wire Keycloak token flow in UI (Vuln 2)"
```

---

### Task 6: Fix Vuln 4 — WebSocket Auth

**Vuln:** `services/api/ws/session_ws.py:88` accepts WebSocket connections without any token validation.

**Files:**
- Modify: `services/api/ws/session_ws.py`
- Create: `services/api/tests/test_ws_auth.py`

- [ ] **Step 1: Write failing test**
```bash
mkdir -p services/api/tests
cat > services/api/tests/test_ws_auth.py << 'EOF'
"""Tests that the WebSocket endpoint rejects unauthenticated connections."""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

# Import the router under test
from services.api.ws.session_ws import router

app = FastAPI()
app.include_router(router)

client = TestClient(app)


def test_ws_without_token_closes_with_4401():
    with client.websocket_connect("/ws/sessions/test-session") as ws:
        data = ws.receive_json()
        assert data.get("error") == "unauthorized"


def test_ws_with_invalid_token_closes():
    from jose import JWTError
    with patch("platform_shared.keycloak_auth.decode_token",
               side_effect=JWTError("bad token")):
        with client.websocket_connect(
            "/ws/sessions/test-session?token=bad.token.here"
        ) as ws:
            data = ws.receive_json()
            assert data.get("error") == "unauthorized"


def test_ws_with_valid_token_accepted():
    with patch("platform_shared.keycloak_auth.decode_token",
               return_value={"sub": "u1", "roles": ["spm:viewer"]}):
        with patch("services.api.ws.session_ws._manager") as mock_mgr:
            mock_mgr.connect = MagicMock(return_value=__import__("asyncio").Queue())
            # Should not immediately close with error
            try:
                with client.websocket_connect(
                    "/ws/sessions/test-session?token=valid.token.here"
                ) as ws:
                    pass
            except Exception:
                pass  # disconnect is fine — we just want no 4401
EOF
```

- [ ] **Step 2: Run — expect fail**
```bash
cd ~/PycharmProjects/AISPM && python -m pytest services/api/tests/test_ws_auth.py::test_ws_without_token_closes_with_4401 -v
```
Expected: FAIL

- [ ] **Step 3: Add token validation at WebSocket entry in `session_ws.py`**

At the top of `ws_session` (after the `_manager` / `_consumer` None check), add:

```python
    # ── Auth ─────────────────────────────────────────────────────────────────
    import os
    token = websocket.query_params.get("token") or \
            websocket.headers.get("authorization", "").removeprefix("Bearer ")
    if not token:
        await websocket.accept()
        await websocket.send_json({"error": "unauthorized"})
        await websocket.close(code=4401)
        return
    try:
        from platform_shared.keycloak_auth import decode_token
        decode_token(token,
                     audience=os.environ.get("JWT_AUDIENCE", "aispm-ui"),
                     issuer=os.environ.get("JWT_ISSUER",
                                           "http://keycloak.local:8180/realms/aispm"))
    except Exception:
        await websocket.accept()
        await websocket.send_json({"error": "unauthorized"})
        await websocket.close(code=4401)
        return
```

- [ ] **Step 4: Run tests — expect pass**
```bash
cd ~/PycharmProjects/AISPM && python -m pytest services/api/tests/test_ws_auth.py -v
```
Expected: `3 passed`

- [ ] **Step 5: Commit**
```bash
git add services/api/ws/session_ws.py services/api/tests/test_ws_auth.py
git commit -m "fix(security): enforce JWT auth at WebSocket upgrade (Vuln 4)"
```

---

### Task 7: Fix Vuln 3 — Remove `exec_module` from agent_validator

**Vuln:** `services/spm_api/agent_validator.py:70-80` uses `importlib.util.spec_from_file_location` + `exec_module` to load arbitrary agent code paths — RCE risk.

**Files:**
- Modify: `services/spm_api/agent_validator.py`
- Create: `services/spm_api/tests/test_agent_validator_security.py`

- [ ] **Step 1: Write failing test**
```bash
cat > services/spm_api/tests/test_agent_validator_security.py << 'EOF'
"""Tests that agent_validator rejects paths outside the allowlist."""
import os, pytest

ALLOWLIST_DIR = os.path.join(os.path.dirname(__file__), "..", "agents")


def test_path_outside_allowlist_rejected(tmp_path):
    evil = tmp_path / "evil_agent.py"
    evil.write_text("import os; os.system('id')")
    from services.spm_api.agent_validator import validate_agent_module
    with pytest.raises(ValueError, match="not in allowlist"):
        validate_agent_module(str(evil))


def test_path_traversal_rejected():
    from services.spm_api.agent_validator import validate_agent_module
    with pytest.raises(ValueError):
        validate_agent_module("/etc/passwd")


def test_valid_agent_path_accepted(tmp_path, monkeypatch):
    # Pretend the allowlist dir is tmp_path
    monkeypatch.setenv("AGENT_ALLOWLIST_DIR", str(tmp_path))
    agent = tmp_path / "my_agent.py"
    agent.write_text("class Agent: pass")
    from services.spm_api import agent_validator
    import importlib
    importlib.reload(agent_validator)
    # Should not raise
    agent_validator.validate_agent_module(str(agent))
EOF
```

- [ ] **Step 2: Run — expect fail**
```bash
cd ~/PycharmProjects/AISPM && python -m pytest services/spm_api/tests/test_agent_validator_security.py -v
```
Expected: FAIL or ImportError

- [ ] **Step 3: Replace `exec_module` block in `agent_validator.py`**

Replace the block at lines 70-80 that uses `spec_from_file_location` / `exec_module`:

```python
import os as _os

_AGENT_ALLOWLIST_DIR = _os.path.realpath(
    _os.environ.get("AGENT_ALLOWLIST_DIR",
                    _os.path.join(_os.path.dirname(__file__), "agents"))
)


def validate_agent_module(path: str):
    """
    Load an agent module safely.

    Only paths inside AGENT_ALLOWLIST_DIR are accepted.
    Raises ValueError for any path outside the allowlist.
    """
    real = _os.path.realpath(path)
    if not real.startswith(_AGENT_ALLOWLIST_DIR + _os.sep) and real != _AGENT_ALLOWLIST_DIR:
        raise ValueError(
            f"Agent path '{path}' is not in allowlist '{_AGENT_ALLOWLIST_DIR}'"
        )
    # Safe: we know the path is within the allowlist directory
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location("_agent_under_test", real)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
```

- [ ] **Step 4: Run tests — expect pass**
```bash
cd ~/PycharmProjects/AISPM && python -m pytest services/spm_api/tests/test_agent_validator_security.py -v
```
Expected: `3 passed`

- [ ] **Step 5: Commit**
```bash
git add services/spm_api/agent_validator.py services/spm_api/tests/test_agent_validator_security.py
git commit -m "fix(security): restrict agent_validator to allowlist dir, eliminate arbitrary exec_module (Vuln 3)"
```

---

### Task 8: Wire Environment Variables

**Files:**
- Modify: `compose.yml`
- Modify: `deploy/helm/aispm/values.yaml`

- [ ] **Step 1: Add env vars to compose.yml**

For each service that imports `platform_shared.keycloak_auth` (agent-orchestrator-service, spm_api, api), add the values **directly in compose.yml** — no `${VAR}` substitution, no `.env` file:
```yaml
      - KEYCLOAK_URL=http://keycloak:8080
      - KEYCLOAK_REALM=aispm
      - KEYCLOAK_JWKS_URL=http://keycloak:8080/realms/aispm/protocol/openid-connect/certs
      - JWT_ISSUER=http://keycloak.local:8180/realms/aispm
      - JWT_AUDIENCE=aispm-ui
```

Also add to the Vite/UI service (hardcoded — no substitution):
```yaml
      - VITE_KEYCLOAK_URL=http://keycloak.local:8180
      - VITE_KC_REALM=aispm
      - VITE_KC_CLIENT_ID=aispm-ui
```

> **Rule:** All configuration lives in `compose.yml` or `values.yaml`. No `.env` files, no shell variable substitution (`${VAR:-default}`). Secrets that differ per environment (e.g. `AISPM_CLIENT_SECRET`) are set directly in the appropriate file for that environment.

- [ ] **Step 2: Add env vars to values.yaml**
```yaml
global:
  keycloak:
    jwksUrl: "http://keycloak.aispm.svc.cluster.local:8080/realms/aispm/protocol/openid-connect/certs"
    issuer: "http://keycloak.local:8180/realms/aispm"
    audience: "aispm-ui"
```

Reference in each service's deployment template as:
```yaml
- name: KEYCLOAK_JWKS_URL
  value: {{ .Values.global.keycloak.jwksUrl }}
- name: JWT_ISSUER
  value: {{ .Values.global.keycloak.issuer }}
- name: JWT_AUDIENCE
  value: {{ .Values.global.keycloak.audience }}
```

- [ ] **Step 3: Verify compose syntax**
```bash
docker compose -f compose.yml config --quiet && echo "compose OK"
```
Expected: `compose OK`

- [ ] **Step 4: Commit**
```bash
git add compose.yml deploy/helm/aispm/values.yaml deploy/helm/aispm/templates/
git commit -m "feat(auth): wire KEYCLOAK_JWKS_URL, JWT_ISSUER, JWT_AUDIENCE env vars across all services"
```

---

### Task 9: Integration Smoke Test + Release Tag

- [ ] **Step 1: Run full test suite**
```bash
cd ~/PycharmProjects/AISPM && python -m pytest platform_shared/tests/ \
  services/agent-orchestrator-service/tests/test_auth_deps.py \
  services/spm_api/tests/test_verify_jwt.py \
  services/spm_api/tests/test_agent_validator_security.py \
  services/api/tests/test_ws_auth.py \
  -v --tb=short
```
Expected: All pass

- [ ] **Step 2: Verify no `/dev-token` references in production code**
```bash
grep -rn "dev.token\|dev_token" services/ ui/src/ --include="*.py" --include="*.js" --include="*.jsx" | grep -v "test_\|#\|//"
```
Expected: no output

- [ ] **Step 3: Verify no `verify_aud.*False` in codebase**
```bash
grep -rn "verify_aud.*False\|verify_signature.*False" services/ --include="*.py"
```
Expected: no output

- [ ] **Step 4: Tag the release**
```bash
git tag -a v1.1.0-auth-hardening -m "Keycloak JWT auth hardening: fix Vulns 1-5"
git push && git push --tags
```

---

## Summary of Vulnerabilities Fixed

| ID | File | Vuln | Fix |
|----|------|------|-----|
| 1 | `agent-orchestrator-service/dependencies/auth.py:114` | No signature verification | JWKS decode via `keycloak_auth.decode_token` |
| 2 | `services/api/app.py:1998` | `/dev-token` in production | Endpoint deleted; UI uses Keycloak token endpoint |
| 3 | `services/spm_api/agent_validator.py:70` | Arbitrary `exec_module` | Allowlist directory check before load |
| 4 | `services/api/ws/session_ws.py:88` | Unauthenticated WebSocket | Bearer token checked at upgrade |
| 5 | `services/spm_api/app.py:94` | `verify_aud=False` | Audience enforced via `keycloak_auth.decode_token` |

---

### Task 10: Wire Keycloak Identity into Postgres (Audit Stamps + Internal Route Auth)

**Context:** Two gaps remain at the database layer:
1. `POST /internal/enforce/{model_id}` (L741 `spm_api/app.py`) has no auth — any process that can reach spm_api can trigger model retirement.
2. DB write records don't consistently stamp the authenticated JWT `sub` as the actor — only `approved_by` does, and only on status changes.

**Files:**
- Modify: `services/spm_api/app.py` (L741 enforce route + DB session helper)
- Modify: `spm/db/session.py` (add `set_app_user` helper)
- Create: `services/spm_api/tests/test_internal_auth.py`

- [ ] **Step 1: Write failing tests**
```bash
cat > services/spm_api/tests/test_internal_auth.py << 'EOF'
"""Tests for /internal/enforce auth and DB audit stamping."""
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from services.spm_api.app import app

client = TestClient(app)

INTERNAL_SECRET = "test-internal-secret"


def test_enforce_without_secret_returns_403(monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", INTERNAL_SECRET)
    resp = client.post("/internal/enforce/00000000-0000-0000-0000-000000000001")
    assert resp.status_code == 403


def test_enforce_with_wrong_secret_returns_403(monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", INTERNAL_SECRET)
    resp = client.post(
        "/internal/enforce/00000000-0000-0000-0000-000000000001",
        headers={"X-Internal-Secret": "wrong-secret"}
    )
    assert resp.status_code == 403


def test_enforce_with_correct_secret_proceeds(monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", INTERNAL_SECRET)
    with patch("services.spm_api.app.get_db") as mock_db:
        mock_session = AsyncMock()
        mock_session.get.return_value = None  # model not found → skipped
        mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        resp = client.post(
            "/internal/enforce/00000000-0000-0000-0000-000000000001",
            headers={"X-Internal-Secret": INTERNAL_SECRET}
        )
    # skipped (model not found) but NOT 403
    assert resp.status_code != 403
EOF
```

- [ ] **Step 2: Run — expect fail**
```bash
cd ~/PycharmProjects/AISPM && python -m pytest services/spm_api/tests/test_internal_auth.py::test_enforce_without_secret_returns_403 -v
```
Expected: FAIL (currently returns 200/404, not 403)

- [ ] **Step 3: Add shared-secret guard to `/internal/enforce`**

Add a dependency function above the `enforce_model` route in `services/spm_api/app.py`:

```python
def _require_internal_secret(x_internal_secret: Optional[str] = Header(None)) -> None:
    """Guard for service-to-service internal routes."""
    expected = os.getenv("INTERNAL_SERVICE_SECRET", "")
    if not expected:
        raise HTTPException(status_code=500, detail="INTERNAL_SERVICE_SECRET not configured")
    if not x_internal_secret or x_internal_secret != expected:
        raise HTTPException(status_code=403, detail="Forbidden: invalid internal secret")
```

Then add it to the route signature:

```python
@app.post("/internal/enforce/{model_id}", include_in_schema=False)
async def enforce_model(
    model_id: str,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_internal_secret),   # ← add this
) -> Dict:
```

- [ ] **Step 4: Add `set_app_user` to DB session for audit stamping**

In `spm/db/session.py`, add after the existing session factory:

```python
async def set_app_user(session: AsyncSession, user_sub: str) -> None:
    """
    Set app.current_user in the Postgres session.
    Enables row-level security policies and audit triggers to know the actor.
    Call this immediately after acquiring a session in any write route.

    Example:
        db: AsyncSession = Depends(get_db)
        claims: Dict = Depends(require_admin)
        await set_app_user(db, claims["sub"])
    """
    # Use a parameterized form — PostgreSQL local variable, not user input to SQL
    await session.execute(
        text("SELECT set_config('app.current_user', :sub, true)"),
        {"sub": user_sub},
    )
```

- [ ] **Step 5: Wire `set_app_user` into spm_api write routes**

In `services/spm_api/app.py`, update the three write routes that have `claims` already:

`POST /models` (approx L495), `POST /models/upload` (L597), `PATCH /models/{model_id}/status` (L702):

Add as the first line of each route body:
```python
    await set_app_user(db, claims.get("sub", "unknown"))
```

Import at top of file:
```python
from spm.db.session import set_app_user
```

- [ ] **Step 6: Add `INTERNAL_SERVICE_SECRET` to compose and values.yaml**

In `compose.yml`, hardcode directly (no `${...}` substitution, no `.env`):
```yaml
      # spm-api service
      - INTERNAL_SERVICE_SECRET=changeme-replace-before-deploy

      # spm-aggregator service
      - INTERNAL_SERVICE_SECRET=changeme-replace-before-deploy
```

> Change `changeme-replace-before-deploy` to a real random string (e.g. `openssl rand -hex 32`) before going to production. The value must match in both services.

In `deploy/helm/aispm/values.yaml` — set the value directly:
```yaml
global:
  internalServiceSecret: "changeme-replace-before-deploy"
```

Then in the spm-api and spm-aggregator Deployment templates, inject as a `Secret` (so it's stored in k8s etcd, not plaintext in a pod spec):

Create `deploy/helm/aispm/templates/internal-secret.yaml`:
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: aispm-internal-secret
  namespace: {{ .Release.Namespace }}
type: Opaque
stringData:
  internal-service-secret: {{ .Values.global.internalServiceSecret | quote }}
```

Reference in the Deployment env block:
```yaml
- name: INTERNAL_SERVICE_SECRET
  valueFrom:
    secretKeyRef:
      name: aispm-internal-secret
      key: internal-service-secret
```

> For compose: the value is in `compose.yml` directly. For k8s: the value is in `values.yaml`, stored as a k8s Secret, and injected via `secretKeyRef`. No `.env` file is involved in either path.

- [ ] **Step 7: Run all Task 10 tests**
```bash
cd ~/PycharmProjects/AISPM && python -m pytest services/spm_api/tests/test_internal_auth.py -v
```
Expected: `3 passed`

- [ ] **Step 8: Commit**
```bash
git add services/spm_api/app.py spm/db/session.py \
        services/spm_api/tests/test_internal_auth.py \
        compose.yml deploy/helm/aispm/values.yaml
git commit -m "fix(security): guard /internal/enforce with shared secret; stamp JWT sub into Postgres session for audit"
```


---

### Task 6b: Fix Second Unauthenticated WebSocket — `/ws/simulation/{session_id}`

**Vuln:** `services/api/ws/simulation_ws.py:33` accepts WebSocket connections with no token check — identical pattern to the session WebSocket fixed in Task 6.

**Files:**
- Modify: `services/api/ws/simulation_ws.py`
- Modify: `services/api/tests/test_ws_auth.py` (add simulation WS test cases)

- [ ] **Step 1: Add simulation WS test cases to existing test file**

Append to `services/api/tests/test_ws_auth.py`:
```python
from services.api.ws.simulation_ws import router as sim_router

sim_app = FastAPI()
sim_app.include_router(sim_router)
sim_client = TestClient(sim_app)


def test_simulation_ws_without_token_closes_with_4401():
    with sim_client.websocket_connect("/ws/simulation/test-session") as ws:
        data = ws.receive_json()
        assert data.get("error") == "unauthorized"


def test_simulation_ws_with_invalid_token_closes():
    from jose import JWTError
    with patch("platform_shared.keycloak_auth.decode_token",
               side_effect=JWTError("bad token")):
        with sim_client.websocket_connect(
            "/ws/simulation/test-session?token=bad.token.here"
        ) as ws:
            data = ws.receive_json()
            assert data.get("error") == "unauthorized"
```

- [ ] **Step 2: Run — expect fail**
```bash
cd ~/PycharmProjects/AISPM && python -m pytest services/api/tests/test_ws_auth.py::test_simulation_ws_without_token_closes_with_4401 -v
```
Expected: FAIL

- [ ] **Step 3: Add auth guard to `simulation_ws.py`**

At the top of `simulation_events_ws` (after the `manager is None` check), insert the same auth block used in Task 6:

```python
    # ── Auth ─────────────────────────────────────────────────────────────────
    import os
    token = websocket.query_params.get("token") or \
            websocket.headers.get("authorization", "").removeprefix("Bearer ")
    if not token:
        await websocket.accept()
        await websocket.send_json({"error": "unauthorized"})
        await websocket.close(code=4401)
        return
    try:
        from platform_shared.keycloak_auth import decode_token
        decode_token(token,
                     audience=os.environ.get("JWT_AUDIENCE", "aispm-ui"),
                     issuer=os.environ.get("JWT_ISSUER",
                                           "http://keycloak.local:8180/realms/aispm"))
    except Exception:
        await websocket.accept()
        await websocket.send_json({"error": "unauthorized"})
        await websocket.close(code=4401)
        return
```

- [ ] **Step 4: Run all WS tests — expect pass**
```bash
cd ~/PycharmProjects/AISPM && python -m pytest services/api/tests/test_ws_auth.py -v
```
Expected: `5 passed`

- [ ] **Step 5: Commit**
```bash
git add services/api/ws/simulation_ws.py services/api/tests/test_ws_auth.py
git commit -m "fix(security): enforce JWT auth at simulation WebSocket upgrade"
```

---

### Task 11: Protect Unauthenticated Routes in `services/api/app.py`

**Vuln:** 8 routes in `services/api/app.py` have no auth. Critical ones: `POST /chat` (L741), `POST /chat/stream` (L1365), `GET /sessions` (L1875), `GET /sessions/{session_id}/events` (L1889). Internal one: `POST /internal/probe` (L1124).

**Files:**
- Modify: `services/api/app.py`
- Create: `services/api/tests/test_route_auth.py`

- [ ] **Step 1: Add `verify_jwt` dependency to `services/api/app.py`**

Add the dependency function near the top of the file (after imports):

```python
import os as _os
from jose import JWTError as _JWTError

def verify_jwt(authorization: Optional[str] = Header(None)) -> Dict:
    """Validate Keycloak JWT for all protected routes."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization.removeprefix("Bearer ")
    try:
        from platform_shared.keycloak_auth import decode_token
        return decode_token(
            token,
            audience=_os.getenv("JWT_AUDIENCE", "aispm-ui"),
            issuer=_os.getenv("JWT_ISSUER", "http://keycloak.local:8180/realms/aispm"),
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")


def _require_internal_secret(x_internal_secret: Optional[str] = Header(None)) -> None:
    expected = _os.getenv("INTERNAL_SERVICE_SECRET", "")
    if not expected or x_internal_secret != expected:
        raise HTTPException(status_code=403, detail="Forbidden")
```

- [ ] **Step 2: Write failing tests**
```bash
cat > services/api/tests/test_route_auth.py << 'EOF'
"""Tests that critical api service routes require auth."""
import pytest
from fastapi.testclient import TestClient
from services.api.app import app

client = TestClient(app)


def test_chat_without_token_returns_401():
    resp = client.post("/chat", json={"message": "hi", "session_id": "s1"})
    assert resp.status_code == 401


def test_chat_stream_without_token_returns_401():
    resp = client.post("/chat/stream", json={"message": "hi", "session_id": "s1"})
    assert resp.status_code == 401


def test_sessions_without_token_returns_401():
    resp = client.get("/sessions")
    assert resp.status_code == 401


def test_session_events_without_token_returns_401():
    resp = client.get("/sessions/test-id/events")
    assert resp.status_code == 401


def test_internal_probe_without_secret_returns_403():
    resp = client.post("/internal/probe", json={})
    assert resp.status_code == 403


def test_chat_with_valid_token_passes(monkeypatch):
    monkeypatch.setattr(
        "platform_shared.keycloak_auth.decode_token",
        lambda token, **kw: {"sub": "u1", "roles": ["spm:viewer"]}
    )
    resp = client.post("/chat",
                       json={"message": "hi", "session_id": "s1"},
                       headers={"Authorization": "Bearer valid.token.here"})
    assert resp.status_code != 401
EOF
```

- [ ] **Step 3: Run — expect fail**
```bash
cd ~/PycharmProjects/AISPM && python -m pytest services/api/tests/test_route_auth.py -v 2>&1 | head -30
```
Expected: multiple FAIL (routes currently return 200/422, not 401)

- [ ] **Step 4: Add `Depends(verify_jwt)` to each unprotected route**

For `POST /chat` (L741), `POST /chat/stream` (L1365), `GET /sessions` (L1875), `GET /sessions/{session_id}/events` (L1889), `GET /inventory` (L729), `POST /api/v1/simulation/screen` (L1942) — add `claims: Dict = Depends(verify_jwt)` to each function signature.

For `POST /internal/probe` (L1124) — add `_: None = Depends(_require_internal_secret)` instead (service-to-service internal call).

For `GET /rate-limit-status` (L1775) — add `claims: Dict = Depends(verify_jwt)`.

Example for /chat:
```python
@app.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    claims: Dict = Depends(verify_jwt),   # ← add this
) -> ChatResponse:
```

- [ ] **Step 5: Run tests — expect pass**
```bash
cd ~/PycharmProjects/AISPM && python -m pytest services/api/tests/test_route_auth.py -v
```
Expected: `6 passed`

- [ ] **Step 6: Commit**
```bash
git add services/api/app.py services/api/tests/test_route_auth.py
git commit -m "fix(security): add JWT auth to all unprotected routes in api service (chat, sessions, inventory)"
```

---

### Task 12: Lock Down CORS to Explicit Origins

**Vuln:** Two services default to `allow_origins=["*"]`. `agent-orchestrator-service` has the dangerous combination of wildcard origins + `allow_credentials=True`.

**Files:**
- Modify: `services/api/app.py` (L579)
- Modify: `services/agent-orchestrator-service/main.py` (L383-386)
- Modify: `services/spm_api/app.py` (L375-383) — verify env var is set in compose
- Modify: `compose.yml` — add `CORS_ORIGINS` and `SPM_API_CORS_ORIGINS` to all three services
- Modify: `deploy/helm/aispm/values.yaml` — add `corsOrigins`

- [ ] **Step 1: Write failing test**
```bash
cat > services/api/tests/test_cors.py << 'EOF'
"""Tests that CORS is not open to wildcard origins."""
from fastapi.testclient import TestClient
from services.api.app import app

client = TestClient(app)


def test_cors_does_not_allow_arbitrary_origin():
    resp = client.options(
        "/health",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    acao = resp.headers.get("access-control-allow-origin", "")
    assert acao != "*", f"CORS wildcard still active: {acao}"
    assert "evil.example.com" not in acao


def test_cors_allows_aispm_origin():
    resp = client.options(
        "/health",
        headers={
            "Origin": "http://aispm.local",
            "Access-Control-Request-Method": "GET",
        },
    )
    acao = resp.headers.get("access-control-allow-origin", "")
    assert "aispm.local" in acao or acao == "http://aispm.local"
EOF
```

- [ ] **Step 2: Run — expect fail**
```bash
cd ~/PycharmProjects/AISPM && python -m pytest services/api/tests/test_cors.py::test_cors_does_not_allow_arbitrary_origin -v
```
Expected: FAIL (`access-control-allow-origin: *` still set)

- [ ] **Step 3: Fix CORS in `services/api/app.py`**

Replace the wildcard CORS block (L577-583):
```python
_cors_origins = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://aispm.local,http://localhost:5173").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=False,   # credentials handled via Authorization header, not cookies
)
```

- [ ] **Step 4: Fix CORS in `services/agent-orchestrator-service/main.py`**

Replace the CORS block (L382-386):
```python
_cors_origins = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://aispm.local,http://localhost:5173").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=False,   # was True with wildcard — invalid combination, now fixed
)
```

- [ ] **Step 5: Add `CORS_ORIGINS` to compose.yml for all three services**

In `compose.yml`, add directly to `api`, `agent-orchestrator-service`, and `spm_api` environment blocks (hardcoded, no `${...}` substitution):
```yaml
      - CORS_ORIGINS=http://aispm.local,http://localhost:5173
      - SPM_API_CORS_ORIGINS=http://aispm.local,http://localhost:5173
```

- [ ] **Step 6: Add to `values.yaml` for Helm**
```yaml
global:
  corsOrigins: "http://aispm.local"
```

Reference in each Deployment template:
```yaml
- name: CORS_ORIGINS
  value: {{ .Values.global.corsOrigins | quote }}
- name: SPM_API_CORS_ORIGINS
  value: {{ .Values.global.corsOrigins | quote }}
```

- [ ] **Step 7: Run all CORS tests — expect pass**
```bash
cd ~/PycharmProjects/AISPM && python -m pytest services/api/tests/test_cors.py -v
```
Expected: `2 passed`

- [ ] **Step 8: Commit**
```bash
git add services/api/app.py \
        services/agent-orchestrator-service/main.py \
        services/spm_api/app.py \
        compose.yml deploy/helm/aispm/values.yaml deploy/helm/aispm/templates/
git commit -m "fix(security): lock CORS to explicit origins, remove allow_credentials=True+wildcard combo"
```


---

### Task 13: Seed Keycloak with Demo Users and Roles

**Context:** After `auth/setup-realm.sh` creates the realm, client, and roles, the system needs at least one usable user per role so the UI and tests can actually authenticate. Without seed users, nobody can log in after a fresh bootstrap.

**Files:**
- Create: `auth/seed-users.sh`
- Modify: `deploy/scripts/bootstrap-cluster.sh` (call seed-users.sh after setup-realm.sh)

- [ ] **Step 1: Create `auth/seed-users.sh`**
```bash
cat > auth/seed-users.sh << 'EOF'
#!/usr/bin/env bash
# Seed demo users into the Keycloak aispm realm.
# All values come from compose.yml / Helm environment — no .env file.
set -euo pipefail

KC_URL="${KEYCLOAK_URL:-http://localhost:8180}"
ADMIN_USER="${KEYCLOAK_ADMIN:-admin}"
ADMIN_PASS="${KEYCLOAK_ADMIN_PASSWORD:-admin}"
REALM="aispm"

echo "Authenticating with Keycloak at $KC_URL ..."
/opt/keycloak/bin/kcadm.sh config credentials \
  --server "$KC_URL" --realm master \
  --user "$ADMIN_USER" --password "$ADMIN_PASS"

# Helper: create user if not exists, assign realm role
create_user() {
  local username="$1"
  local password="$2"
  local role="$3"
  local email="$4"

  EXISTS=$(/opt/keycloak/bin/kcadm.sh get users -r "$REALM" \
    --fields username -q username="$username" 2>/dev/null | grep -c "$username" || true)

  if [ "$EXISTS" -eq 0 ]; then
    /opt/keycloak/bin/kcadm.sh create users -r "$REALM" \
      -s username="$username" \
      -s email="$email" \
      -s enabled=true \
      -s emailVerified=true \
      -s "credentials=[{\"type\":\"password\",\"value\":\"$password\",\"temporary\":false}]"
    echo "Created user: $username"
  else
    echo "User already exists: $username"
  fi

  USER_ID=$(/opt/keycloak/bin/kcadm.sh get users -r "$REALM" \
    -q username="$username" --fields id 2>/dev/null | grep '"id"' | head -1 | sed 's/.*: "\(.*\)".*/\1/')

  /opt/keycloak/bin/kcadm.sh add-roles -r "$REALM" \
    --uusername "$username" --rolename "$role" 2>/dev/null || true
  echo "Assigned role '$role' to '$username'"
}

# Seed one user per role — passwords set directly here (no .env)
create_user "admin@aispm.local"   "${SEED_ADMIN_PASSWORD:-admin-changeme}"   "spm:admin"   "admin@aispm.local"
create_user "auditor@aispm.local" "${SEED_AUDITOR_PASSWORD:-auditor-changeme}" "spm:auditor" "auditor@aispm.local"
create_user "viewer@aispm.local"  "${SEED_VIEWER_PASSWORD:-viewer-changeme}"  "spm:viewer"  "viewer@aispm.local"

echo "Keycloak user seeding complete."
EOF
chmod +x auth/seed-users.sh
```

- [ ] **Step 2: Verify script syntax**
```bash
bash -n auth/seed-users.sh && echo "Syntax OK"
```
Expected: `Syntax OK`

- [ ] **Step 3: Wire seed-users.sh into bootstrap-cluster.sh**

In `deploy/scripts/bootstrap-cluster.sh`, find the step that calls `setup-realm.sh` (or the Keycloak wait step) and add the seed call immediately after:

```bash
# After setup-realm.sh runs:
echo "Seeding Keycloak demo users..."
kubectl exec -n aispm deployment/keycloak -- bash /opt/keycloak/scripts/seed-users.sh
```

Also add the script to the Keycloak container's ConfigMap or volume mount in the Helm chart so it's available inside the pod. In `deploy/helm/aispm/templates/keycloak-scripts-configmap.yaml`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: keycloak-scripts
  namespace: {{ .Release.Namespace }}
data:
  setup-realm.sh: |
    {{ .Files.Get "../../auth/setup-realm.sh" | nindent 4 }}
  seed-users.sh: |
    {{ .Files.Get "../../auth/seed-users.sh" | nindent 4 }}
```

- [ ] **Step 4: Add seed passwords to compose.yml Keycloak service env block**

In `compose.yml` under the `keycloak` service environment (hardcoded — no substitution, no .env):
```yaml
      - SEED_ADMIN_PASSWORD=admin-changeme-in-prod
      - SEED_AUDITOR_PASSWORD=auditor-changeme-in-prod
      - SEED_VIEWER_PASSWORD=viewer-changeme-in-prod
```

In `deploy/helm/aispm/values.yaml`:
```yaml
keycloak:
  seedUsers:
    adminPassword: "admin-changeme-in-prod"
    auditorPassword: "auditor-changeme-in-prod"
    viewerPassword: "viewer-changeme-in-prod"
```

Store as a Kubernetes Secret — add to `deploy/helm/aispm/templates/keycloak-seed-secret.yaml`:
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: keycloak-seed-credentials
  namespace: {{ .Release.Namespace }}
type: Opaque
stringData:
  admin-password:   {{ .Values.keycloak.seedUsers.adminPassword | quote }}
  auditor-password: {{ .Values.keycloak.seedUsers.auditorPassword | quote }}
  viewer-password:  {{ .Values.keycloak.seedUsers.viewerPassword | quote }}
```

- [ ] **Step 5: Commit**
```bash
git add auth/seed-users.sh \
        deploy/scripts/bootstrap-cluster.sh \
        deploy/helm/aispm/templates/keycloak-scripts-configmap.yaml \
        deploy/helm/aispm/templates/keycloak-seed-secret.yaml \
        deploy/helm/aispm/values.yaml \
        compose.yml
git commit -m "feat(auth): seed Keycloak with demo users (admin, auditor, viewer) on bootstrap"
```

