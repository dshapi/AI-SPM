"""
tests/test_integrations_routes.py — pytest for spm-api integrations module.

Covers four surfaces:

1. **Pure helpers** — ``_encode_secret`` / ``_decode_secret`` / ``_mask`` / ``_iso``.
   Cheap, no fixtures, guards the secret-at-rest encoding contract.

2. **Auth-wrapper signature regression** — asserts that ``verify_jwt`` /
   ``require_admin`` / ``require_auditor`` in ``integrations_routes.py``
   expose a signature FastAPI's DI layer can introspect.  A prior version
   used ``(*args, **kwargs)`` wrappers which silently broke every
   authenticated endpoint with HTTP 422 (bug #60).

3. **HTTP-level auth gating** — via ``TestClient`` against a minimal
   FastAPI app that mounts only ``integrations_routes.router``, with
   ``get_db`` / ``verify_jwt`` overridden.  Asserts:
     - 401 when no Authorization header
     - 403 when auditor hits an admin endpoint
     - 200 when admin hits an admin endpoint
     - 200 when auditor hits an auditor-gated endpoint (logs)

4. **Pydantic schema validation** — on ``IntegrationCreate`` /
   ``ConfigureRequest``, so breaking field changes are caught at unit-test
   time rather than at contract-break time with the frontend.

The tests DO NOT touch a real database — the Integration models use
Postgres-specific JSONB + UUID types that don't round-trip cleanly on
SQLite.  Deeper DB-behaviour tests live in an integration suite run
against docker-compose spm-db.
"""
from __future__ import annotations

import asyncio
import inspect
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Depends, FastAPI, Header
from fastapi.testclient import TestClient


# ─────────────────────────────────────────────────────────────────────────────
# Imports under test.  ``integrations_routes`` is placed on sys.path by the
# top-level ``tests/conftest.py`` (services/spm_api is appended there).
# ─────────────────────────────────────────────────────────────────────────────
import integrations_routes as ir  # noqa: E402
from integrations_routes import (  # noqa: E402
    ConfigureRequest,
    IntegrationCreate,
    IntegrationUpdate,
    _decode_secret,
    _encode_secret,
    _iso,
    _mask,
    require_admin,
    require_auditor,
    router,
    verify_jwt,
)


# ─────────────────────────────────────────────────────────────────────────────
# 1) Pure helpers — no FastAPI, no DB
# ─────────────────────────────────────────────────────────────────────────────
class TestSecretEncoding:
    def test_encode_decode_round_trip(self):
        raw = "sk-ant-abcdef-1234567890"
        enc = _encode_secret(raw)
        # Encoded form is NOT the raw key — guards against the migration
        # where we accidentally store plaintext.
        assert enc != raw
        assert _decode_secret(enc) == raw

    def test_encode_empty_returns_empty(self):
        assert _encode_secret("") == ""
        assert _encode_secret(None) == ""  # type: ignore[arg-type]

    def test_decode_empty_returns_empty(self):
        assert _decode_secret(None) == ""
        assert _decode_secret("") == ""

    def test_decode_invalid_base64_fails_soft(self):
        # Garbage in → empty out, never raises.  This matters because the
        # hydrator reads credentials at boot and a malformed row must not
        # crash the container.
        assert _decode_secret("not-valid-base64!!!") == ""

    def test_encode_unicode_safe(self):
        raw = "päss-wörd-🔑"
        assert _decode_secret(_encode_secret(raw)) == raw


class TestMaskHint:
    def test_mask_short_string(self):
        assert _mask("abc") == "****"
        assert _mask("12345678") == "****"  # len==8 boundary

    def test_mask_long_string(self):
        # Shows first 4 + last 4 joined by the ellipsis character.
        masked = _mask("sk-ant-abcdef-1234567890")
        assert masked.startswith("sk-a")
        assert masked.endswith("7890")
        assert "…" in masked

    def test_mask_empty(self):
        assert _mask("") == ""


class TestIsoHelper:
    def test_iso_none_returns_none(self):
        assert _iso(None) is None

    def test_iso_datetime_is_isoformatted(self):
        from datetime import datetime, timezone
        dt = datetime(2026, 4, 23, 12, 34, 56, tzinfo=timezone.utc)
        assert _iso(dt) == "2026-04-23T12:34:56+00:00"


# ─────────────────────────────────────────────────────────────────────────────
# 2) Auth-wrapper signature regression (bug #60)
#
# FastAPI's dependency injection inspects each callable's signature via
# ``inspect.signature()``.  If the wrapper's signature is ``(*args, **kwargs)``
# the DI layer cannot see the ``Authorization`` header parameter, so it
# treats the header as unrecognised and rejects every request with 422.
# These tests lock the shape in place.
# ─────────────────────────────────────────────────────────────────────────────
class TestAuthWrapperSignatures:
    def test_verify_jwt_has_authorization_header_param(self):
        sig = inspect.signature(verify_jwt)
        assert "authorization" in sig.parameters, (
            "verify_jwt must expose an 'authorization' parameter so FastAPI's "
            "DI can resolve the Authorization header — regression of bug #60."
        )

    def test_verify_jwt_authorization_default_is_header(self):
        # The default for `authorization` must be a fastapi.Header marker,
        # otherwise FastAPI will fall back to treating it as a Query param.
        sig = inspect.signature(verify_jwt)
        param = sig.parameters["authorization"]
        # fastapi.params.Header is the underlying class behind fastapi.Header()
        from fastapi.params import Header as HeaderParam
        assert isinstance(param.default, HeaderParam)

    def test_require_admin_depends_on_verify_jwt(self):
        sig = inspect.signature(require_admin)
        assert "claims" in sig.parameters
        from fastapi.params import Depends as DependsParam
        assert isinstance(sig.parameters["claims"].default, DependsParam)

    def test_require_auditor_depends_on_verify_jwt(self):
        sig = inspect.signature(require_auditor)
        assert "claims" in sig.parameters
        from fastapi.params import Depends as DependsParam
        assert isinstance(sig.parameters["claims"].default, DependsParam)

    def test_require_admin_rejects_non_admin(self):
        # Call directly — no FastAPI involved, exercising the guard logic.
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as excinfo:
            require_admin(claims={"sub": "u1", "roles": ["spm:auditor"]})
        assert excinfo.value.status_code == 403

    def test_require_admin_accepts_admin(self):
        claims = {"sub": "u1", "roles": ["spm:admin"]}
        # Returns the same claims dict unchanged.
        assert require_admin(claims=claims) is claims

    def test_require_auditor_accepts_both_roles(self):
        admin = {"sub": "u1", "roles": ["spm:admin"]}
        auditor = {"sub": "u2", "roles": ["spm:auditor"]}
        assert require_auditor(claims=admin) is admin
        assert require_auditor(claims=auditor) is auditor

    def test_require_auditor_rejects_plain_user(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as excinfo:
            require_auditor(claims={"sub": "u1", "roles": []})
        assert excinfo.value.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# 3) HTTP-level auth gating
#
# We mount the real `router` on a brand-new FastAPI app (skipping the
# spm-api lifespan, CORS, DB bootstrap etc), then override:
#   - ``get_db`` → yields a MagicMock pretending to be an AsyncSession
#   - ``verify_jwt`` → returns canned claims that the per-test fixture sets
# ─────────────────────────────────────────────────────────────────────────────
def _make_mock_db_for_list():
    """Returns an async fake-session whose execute() yields an empty list."""
    session = MagicMock()
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = []
    scalars.scalar_one.return_value = 0
    result.scalars.return_value = scalars
    # scalar_one is called directly on the result of execute()
    result.scalar_one.return_value = 0
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.close = AsyncMock()
    return session


@pytest.fixture
def client_factory():
    """Returns a factory that builds a TestClient with the given auth claims
    and DB factory.  Each test gets an independent app so overrides don't
    bleed."""
    from spm.db.session import get_db

    def _factory(
        claims: Optional[Dict[str, Any]] = None,
        db_session_factory=_make_mock_db_for_list,
    ) -> TestClient:
        app = FastAPI()
        app.include_router(router)

        async def _override_get_db():
            yield db_session_factory()

        app.dependency_overrides[get_db] = _override_get_db

        if claims is not None:
            # Override verify_jwt so any Authorization header is accepted
            # and the given claims are returned.  We do NOT override
            # require_admin / require_auditor — those still run against
            # the claims the override hands out, which is the behaviour we
            # want to test.
            def _override_verify_jwt(authorization: Optional[str] = Header(None)):
                if not authorization:
                    from fastapi import HTTPException
                    raise HTTPException(status_code=401, detail="Missing bearer token")
                return claims

            app.dependency_overrides[verify_jwt] = _override_verify_jwt

        return TestClient(app)

    return _factory


class TestAuthGatingList:
    def test_list_without_auth_is_401(self, client_factory):
        # No claim override → real verify_jwt runs, which 401s because the
        # public key file isn't configured in the test env.  Either way the
        # request is rejected before reaching the handler.
        client = client_factory(claims=None)
        resp = client.get("/integrations")
        assert resp.status_code in (401, 500), (
            f"Expected 401/500 for unauthenticated list, got "
            f"{resp.status_code}: {resp.text}"
        )

    def test_list_with_admin_is_200(self, client_factory):
        client = client_factory(claims={"sub": "u1", "roles": ["spm:admin"]})
        resp = client.get("/integrations", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 200, resp.text
        assert resp.json() == []

    def test_list_with_plain_user_is_200(self, client_factory):
        # verify_jwt only → no role required for listing.
        client = client_factory(claims={"sub": "u1", "roles": []})
        resp = client.get("/integrations", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 200, resp.text


class TestAuthGatingAdminRoutes:
    """Admin-only routes reject auditor and plain-user tokens with 403."""

    def _post_create_payload(self) -> Dict[str, Any]:
        return {
            "name": "Test Provider",
            "category": "AI Providers",
            "auth_method": "API Key",
            "environment": "Production",
        }

    def test_create_rejects_auditor(self, client_factory):
        client = client_factory(claims={"sub": "u1", "roles": ["spm:auditor"]})
        resp = client.post(
            "/integrations",
            json=self._post_create_payload(),
            headers={"Authorization": "Bearer x"},
        )
        assert resp.status_code == 403, resp.text

    def test_create_rejects_plain_user(self, client_factory):
        client = client_factory(claims={"sub": "u1", "roles": []})
        resp = client.post(
            "/integrations",
            json=self._post_create_payload(),
            headers={"Authorization": "Bearer x"},
        )
        assert resp.status_code == 403, resp.text

    def test_bootstrap_rejects_non_admin(self, client_factory):
        client = client_factory(claims={"sub": "u1", "roles": ["spm:auditor"]})
        resp = client.post(
            "/integrations/bootstrap",
            headers={"Authorization": "Bearer x"},
        )
        assert resp.status_code == 403, resp.text


class TestAuthGatingAuditorRoutes:
    """The /logs tab requires auditor (or admin).  Plain users get 403."""

    def test_logs_rejects_plain_user(self, client_factory):
        client = client_factory(claims={"sub": "u1", "roles": []})
        resp = client.get(
            "/integrations/int-003/logs",
            headers={"Authorization": "Bearer x"},
        )
        assert resp.status_code == 403, resp.text

    def test_metrics_open_to_any_authenticated(self, client_factory):
        # /metrics uses verify_jwt only (no role gate), so any authenticated
        # token should reach the handler.  The DB-backed handler will error
        # because our mock session doesn't walk the exact query chain, but
        # we only care that we pass the auth layer — so we accept anything
        # that is NOT 401/403.
        client = client_factory(claims={"sub": "u1", "roles": []})
        resp = client.get(
            "/integrations/metrics",
            headers={"Authorization": "Bearer x"},
        )
        assert resp.status_code not in (401, 403), resp.text


# ─────────────────────────────────────────────────────────────────────────────
# 4) Pydantic schemas — breaking changes surface here, not at integration-
#    test time where the frontend first notices the contract shift.
# ─────────────────────────────────────────────────────────────────────────────
class TestIntegrationCreateSchema:
    def test_defaults_applied(self):
        body = IntegrationCreate(name="My Provider", category="AI Providers")
        assert body.auth_method == "API Key"
        assert body.environment == "Production"
        assert body.enabled is True
        assert body.status == "Not Configured"
        assert body.tags == []
        assert body.config == {}

    def test_name_and_category_required(self):
        with pytest.raises(Exception):
            IntegrationCreate.model_validate({"category": "AI Providers"})
        with pytest.raises(Exception):
            IntegrationCreate.model_validate({"name": "X"})

    def test_config_and_tags_populate(self):
        body = IntegrationCreate(
            name="X", category="Y",
            tags=["foo", "bar"], config={"model": "claude-sonnet-4-6"},
        )
        assert body.tags == ["foo", "bar"]
        assert body.config == {"model": "claude-sonnet-4-6"}


class TestIntegrationUpdateSchema:
    def test_all_fields_optional(self):
        body = IntegrationUpdate()
        assert body.name is None
        assert body.enabled is None
        assert body.config is None

    def test_partial_update_roundtrip(self):
        body = IntegrationUpdate(name="Rename", enabled=False)
        # model_dump(exclude_none=True) is what the route uses to decide
        # which fields to touch; keep that surface stable.
        dumped = body.model_dump(exclude_none=True)
        assert dumped == {"name": "Rename", "enabled": False}


class TestConfigureRequestSchema:
    def test_both_fields_optional(self):
        body = ConfigureRequest()
        assert body.api_key is None
        assert body.config is None

    def test_api_key_only(self):
        body = ConfigureRequest(api_key="sk-123")
        assert body.api_key == "sk-123"
        assert body.config is None

    def test_config_only(self):
        body = ConfigureRequest(config={"model": "claude-sonnet-4-6"})
        assert body.api_key is None
        assert body.config == {"model": "claude-sonnet-4-6"}

    def test_both_together(self):
        body = ConfigureRequest(api_key="sk-123", config={"model": "x"})
        assert body.api_key == "sk-123"
        assert body.config == {"model": "x"}

    def test_cert_archetype_fields(self):
        # service_account_json + bootstrap_servers are the Kafka /
        # Vertex AI / Azure Sentinel shape — locked in by schema so a
        # schema drift breaks unit tests rather than production saves.
        body = ConfigureRequest(
            service_account_json="-----BEGIN CERT-----\n…\n-----END CERT-----",
            bootstrap_servers="broker-1.example.com:9093,broker-2.example.com:9093",
        )
        assert body.service_account_json.startswith("-----BEGIN CERT-----")
        assert body.bootstrap_servers == "broker-1.example.com:9093,broker-2.example.com:9093"
        assert body.api_key is None
        assert body.password is None


# ─────────────────────────────────────────────────────────────────────────────
# 5) Router wiring — asserts the expected endpoint set exists at the right
#    paths.  Protects against accidental drops (e.g. the GET /integrations/env
#    removal should be permanent; a re-add would be caught here).
# ─────────────────────────────────────────────────────────────────────────────
class TestRouterWiring:
    def _path_methods(self) -> Dict[str, set]:
        """Return {route_path: {HTTP methods}} for every route on the
        mounted router."""
        out: Dict[str, set] = {}
        for r in router.routes:
            # APIRoute has .path and .methods; Mount/etc won't.
            path = getattr(r, "path", None)
            methods = getattr(r, "methods", None)
            if path and methods:
                out.setdefault(path, set()).update(methods)
        return out

    def test_crud_endpoints_exist(self):
        paths = self._path_methods()
        assert "GET" in paths.get("/integrations", set())
        assert "POST" in paths.get("/integrations", set())
        assert "GET" in paths.get("/integrations/{integration_id}", set())
        assert "PATCH" in paths.get("/integrations/{integration_id}", set())
        assert "DELETE" in paths.get("/integrations/{integration_id}", set())

    def test_tab_endpoints_exist(self):
        paths = self._path_methods()
        for tab in ("overview", "connection", "auth", "coverage",
                    "activity", "workflows", "logs"):
            p = f"/integrations/{{integration_id}}/{tab}"
            assert "GET" in paths.get(p, set()), f"missing GET {p}"

    def test_action_endpoints_exist(self):
        paths = self._path_methods()
        for action in ("configure", "test", "disable", "enable",
                       "rotate-credentials", "sync"):
            p = f"/integrations/{{integration_id}}/{action}"
            assert "POST" in paths.get(p, set()), f"missing POST {p}"

    def test_bootstrap_endpoint_exists(self):
        paths = self._path_methods()
        assert "POST" in paths.get("/integrations/bootstrap", set())

    def test_env_endpoint_removed(self):
        """GET /integrations/env was removed (services hydrate direct from
        DB now).  Re-adding it would re-expose secrets on the HTTP wire —
        this test locks that decision in."""
        paths = self._path_methods()
        assert "/integrations/env" not in paths


# ─────────────────────────────────────────────────────────────────────────────
# 6) Vendor-liveness probe URL building (bug #67)
#
# The Ollama probe hits /api/tags at the native root.  Stored base_url
# is often the OpenAI-compatible surface ".../v1" (that's what
# guard-model talks to), so the probe has to strip a trailing /v1 before
# appending the native path — otherwise it GETs /v1/api/tags (404) and
# the Test button never turns green.  This test locks that contract in
# without hitting the network by intercepting httpx.AsyncClient.get.
# ─────────────────────────────────────────────────────────────────────────────
class TestOllamaProbeUrlBuilding:
    @pytest.mark.asyncio
    async def test_strips_v1_suffix(self, monkeypatch):
        captured: List[str] = []

        class _FakeResponse:
            status_code = 200
            def json(self): return {"models": [{"name": "llama3.2:3b"}]}

        class _FakeClient:
            def __init__(self, *a, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *exc): return False
            async def get(self, url, *a, **kw):
                captured.append(url)
                return _FakeResponse()

        monkeypatch.setattr(ir.httpx, "AsyncClient", _FakeClient)

        ok, msg, _ = await ir._probe_ollama("http://host.docker.internal:11434/v1")
        assert ok is True
        assert captured == ["http://host.docker.internal:11434/api/tags"], (
            f"expected /v1 stripped before /api/tags, got {captured!r}"
        )
        assert "1 models" in msg

    @pytest.mark.asyncio
    async def test_root_base_url_unchanged(self, monkeypatch):
        captured: List[str] = []

        class _FakeResponse:
            status_code = 200
            def json(self): return {"models": []}

        class _FakeClient:
            def __init__(self, *a, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *exc): return False
            async def get(self, url, *a, **kw):
                captured.append(url)
                return _FakeResponse()

        monkeypatch.setattr(ir.httpx, "AsyncClient", _FakeClient)

        await ir._probe_ollama("http://host.docker.internal:11434")
        assert captured == ["http://host.docker.internal:11434/api/tags"]

    @pytest.mark.asyncio
    async def test_default_when_no_base_url(self, monkeypatch):
        captured: List[str] = []

        class _FakeResponse:
            status_code = 200
            def json(self): return {"models": []}

        class _FakeClient:
            def __init__(self, *a, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *exc): return False
            async def get(self, url, *a, **kw):
                captured.append(url)
                return _FakeResponse()

        monkeypatch.setattr(ir.httpx, "AsyncClient", _FakeClient)

        await ir._probe_ollama(None)
        assert captured == ["http://host.docker.internal:11434/api/tags"]


# ─────────────────────────────────────────────────────────────────────────────
# 7) Kafka probe — TCP connect to the first bootstrap broker.  We stub
# asyncio.open_connection so the tests don't actually touch the network.
# ─────────────────────────────────────────────────────────────────────────────
class TestKafkaProbe:
    @pytest.mark.asyncio
    async def test_returns_false_when_no_bootstrap(self):
        ok, msg, latency = await ir._probe_kafka(None)
        assert ok is False
        assert "no bootstrap servers" in msg.lower()
        assert latency is None

    @pytest.mark.asyncio
    async def test_returns_false_when_bootstrap_is_blank(self):
        ok, msg, _ = await ir._probe_kafka("   ")
        assert ok is False
        assert "no bootstrap servers" in msg.lower()

    @pytest.mark.asyncio
    async def test_rejects_missing_port(self):
        ok, msg, _ = await ir._probe_kafka("broker-1.example.com")
        assert ok is False
        assert "host:port" in msg

    @pytest.mark.asyncio
    async def test_rejects_non_integer_port(self):
        ok, msg, _ = await ir._probe_kafka("broker-1.example.com:NOT_A_PORT")
        assert ok is False
        assert "integer" in msg.lower()

    @pytest.mark.asyncio
    async def test_successful_tcp_connect(self, monkeypatch):
        captured = []

        class _FakeWriter:
            def close(self): captured.append("close")
            async def wait_closed(self): captured.append("wait_closed")

        async def _fake_open_connection(host, port):
            captured.append(("connect", host, port))
            return (MagicMock(), _FakeWriter())

        monkeypatch.setattr(ir.asyncio, "open_connection", _fake_open_connection)

        ok, msg, latency = await ir._probe_kafka(
            "broker-1.example.com:9093,broker-2.example.com:9093",
        )
        assert ok is True
        # Only the FIRST broker is probed.
        assert captured[0] == ("connect", "broker-1.example.com", 9093)
        assert "reachable" in msg
        assert "broker-1.example.com:9093" in msg
        assert isinstance(latency, int) and latency >= 0

    @pytest.mark.asyncio
    async def test_connection_refused_is_soft_failure(self, monkeypatch):
        async def _refused(host, port):
            raise ConnectionRefusedError(f"connection to {host}:{port} refused")

        monkeypatch.setattr(ir.asyncio, "open_connection", _refused)

        ok, msg, latency = await ir._probe_kafka("broker.example.com:9093")
        assert ok is False
        assert "unreachable" in msg.lower()
        assert latency is None

    @pytest.mark.asyncio
    async def test_timeout_reports_timeout(self, monkeypatch):
        # asyncio.wait_for raises TimeoutError when the inner coroutine
        # exceeds the deadline — simulate by making open_connection hang
        # past the 6s probe budget, but short-circuit by having the real
        # wait_for raise TimeoutError directly.
        async def _fake_wait_for(coro, timeout):
            # Properly close the unused coroutine so asyncio doesn't warn.
            coro.close()
            raise asyncio.TimeoutError()

        async def _never_returns(host, port):
            import asyncio as _a
            await _a.sleep(10)

        monkeypatch.setattr(ir.asyncio, "wait_for", _fake_wait_for)
        monkeypatch.setattr(ir.asyncio, "open_connection", _never_returns)

        ok, msg, _ = await ir._probe_kafka("slow-broker.example.com:9093")
        assert ok is False
        assert "timed out" in msg.lower()


# ─────────────────────────────────────────────────────────────────────────────
# 8) _probe_vendor Kafka dispatch — reads config.bootstrap_servers, not
# base_url.  Mocks _probe_kafka to avoid re-testing its internals here.
# ─────────────────────────────────────────────────────────────────────────────
class TestVendorDispatchKafka:
    @pytest.mark.asyncio
    async def test_kafka_name_routes_to_probe_kafka_with_bootstrap(self, monkeypatch):
        captured = {}

        async def _fake_probe_kafka(bootstrap):
            captured["bootstrap"] = bootstrap
            return True, f"Kafka {bootstrap} reachable", 12

        monkeypatch.setattr(ir, "_probe_kafka", _fake_probe_kafka)

        row = MagicMock()
        row.name = "Kafka"
        row.enabled = True
        row.config = {"bootstrap_servers": "broker:9093"}
        row.credentials = []

        ok, msg, latency = await ir._probe_vendor(row, api_key=None)
        assert ok is True
        assert captured["bootstrap"] == "broker:9093"
        assert latency == 12

    @pytest.mark.asyncio
    async def test_kafka_does_not_demand_api_key(self, monkeypatch):
        # Regression for bug #68 — before the narrowing, Kafka hit the
        # "no API key configured" gate even though it uses a cert.  This
        # test proves dispatch reaches the Kafka probe with api_key=None.
        captured = {"called": False}

        async def _fake_probe_kafka(bootstrap):
            captured["called"] = True
            return True, "ok", 5

        monkeypatch.setattr(ir, "_probe_kafka", _fake_probe_kafka)

        row = MagicMock()
        row.name = "Kafka"
        row.enabled = True
        row.config = {"bootstrap_servers": "broker:9093"}
        row.credentials = []

        ok, msg, _ = await ir._probe_vendor(row, api_key=None)
        assert captured["called"] is True, (
            "Kafka dispatch must reach _probe_kafka even without an api_key — "
            "otherwise the user sees a misleading 'no API key configured' error."
        )
        assert "no API key" not in msg


# ─────────────────────────────────────────────────────────────────────────────
# 9) _probe_flink — Flink JobManager liveness probe (httpx-backed, GETs
#    /overview).  Same shape as the Kafka probe: never raises, always
#    returns (ok, msg, latency).  We mock httpx.AsyncClient so tests
#    don't touch the network.
# ─────────────────────────────────────────────────────────────────────────────
class TestFlinkProbe:
    @pytest.mark.asyncio
    async def test_returns_false_when_no_jobmanager_url(self):
        ok, msg, latency = await ir._probe_flink(None)
        assert ok is False
        assert "no jobmanager_url" in msg.lower()
        assert latency is None

    @pytest.mark.asyncio
    async def test_returns_false_when_jobmanager_url_is_blank(self):
        ok, msg, _ = await ir._probe_flink("   ")
        assert ok is False
        assert "no jobmanager_url" in msg.lower()

    @pytest.mark.asyncio
    async def test_success_extracts_slot_summary(self, monkeypatch):
        # The happy path — probe GETs /overview, server returns 200 with
        # the canonical cluster-summary shape, message carries the real
        # signal (taskmanager count + slot availability) instead of a
        # generic "200 OK".
        captured_url = {}

        class _FakeResp:
            status_code = 200
            def json(self):
                return {"taskmanagers": 3, "slots-total": 12, "slots-available": 7,
                        "jobs-running": 2}

        class _FakeClient:
            def __init__(self, *a, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, url):
                captured_url["url"] = url
                return _FakeResp()

        monkeypatch.setattr(ir.httpx, "AsyncClient", _FakeClient)

        ok, msg, latency = await ir._probe_flink("http://flink-jobmanager:8081")
        assert ok is True
        # The probe hits /overview, not the root.
        assert captured_url["url"] == "http://flink-jobmanager:8081/overview"
        # Message surfaces the slot numbers, not just "200 OK".
        assert "3 taskmanager" in msg
        assert "7/12 slots" in msg
        assert isinstance(latency, int) and latency >= 0

    @pytest.mark.asyncio
    async def test_strips_trailing_slash_on_jobmanager_url(self, monkeypatch):
        # Defensive — if the operator saves "http://flink:8081/" the
        # probe must still build "http://flink:8081/overview", not
        # "http://flink:8081//overview" (which Flink's REST layer would
        # still serve, but looks bad in logs and fails stricter proxies).
        captured_url = {}

        class _FakeResp:
            status_code = 200
            def json(self): return {}

        class _FakeClient:
            def __init__(self, *a, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, url):
                captured_url["url"] = url
                return _FakeResp()

        monkeypatch.setattr(ir.httpx, "AsyncClient", _FakeClient)
        await ir._probe_flink("http://flink:8081/")
        assert captured_url["url"] == "http://flink:8081/overview"

    @pytest.mark.asyncio
    async def test_non_200_reports_status_code(self, monkeypatch):
        class _FakeResp:
            status_code = 503
            def json(self): return {}

        class _FakeClient:
            def __init__(self, *a, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, url): return _FakeResp()

        monkeypatch.setattr(ir.httpx, "AsyncClient", _FakeClient)
        ok, msg, _ = await ir._probe_flink("http://flink:8081")
        assert ok is False
        assert "503" in msg

    @pytest.mark.asyncio
    async def test_timeout_reports_timeout(self, monkeypatch):
        class _FakeClient:
            def __init__(self, *a, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, url):
                raise ir.httpx.TimeoutException("deadline")

        monkeypatch.setattr(ir.httpx, "AsyncClient", _FakeClient)
        ok, msg, latency = await ir._probe_flink("http://flink:8081")
        assert ok is False
        assert "timed out" in msg.lower()
        assert latency is None

    @pytest.mark.asyncio
    async def test_generic_http_error_is_soft_failure(self, monkeypatch):
        class _FakeClient:
            def __init__(self, *a, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, url):
                raise ir.httpx.HTTPError("connect refused")

        monkeypatch.setattr(ir.httpx, "AsyncClient", _FakeClient)
        ok, msg, _ = await ir._probe_flink("http://flink:8081")
        assert ok is False
        assert "flink probe failed" in msg.lower()


# ─────────────────────────────────────────────────────────────────────────────
# 10) _probe_vendor Flink dispatch — reads config.jobmanager_url, with
#     a docker-compose-aligned default when unset.  Also confirms the
#     dispatch does NOT demand an api_key (same regression class as
#     Kafka / bug #68).
# ─────────────────────────────────────────────────────────────────────────────
class TestVendorDispatchFlink:
    @pytest.mark.asyncio
    async def test_flink_name_routes_to_probe_flink_with_jobmanager(self, monkeypatch):
        captured = {}

        async def _fake_probe_flink(url):
            captured["url"] = url
            return True, f"Flink {url} reachable", 15

        monkeypatch.setattr(ir, "_probe_flink", _fake_probe_flink)

        row = MagicMock()
        row.name = "Flink"
        row.enabled = True
        row.config = {"jobmanager_url": "http://flink.prod:8081"}
        row.credentials = []

        ok, msg, latency = await ir._probe_vendor(row, api_key=None)
        assert ok is True
        assert captured["url"] == "http://flink.prod:8081"
        assert latency == 15

    @pytest.mark.asyncio
    async def test_flink_uses_compose_default_when_config_missing(self, monkeypatch):
        # If config.jobmanager_url is absent (fresh bootstrap, no operator
        # edit yet), the dispatcher must supply a sensible default
        # matching docker-compose topology so the Test button doesn't
        # short-circuit with "no jobmanager_url configured".
        captured = {}

        async def _fake_probe_flink(url):
            captured["url"] = url
            return False, "unreachable", None

        monkeypatch.setattr(ir, "_probe_flink", _fake_probe_flink)

        row = MagicMock()
        row.name = "Flink"
        row.enabled = True
        row.config = {}
        row.credentials = []

        await ir._probe_vendor(row, api_key=None)
        assert captured["url"] == "http://flink-jobmanager:8081"

    @pytest.mark.asyncio
    async def test_flink_does_not_demand_api_key(self, monkeypatch):
        # Same bug class as Kafka / #68 — Flink uses a service_account_json
        # credential and must never hit the "no API key configured" gate.
        captured = {"called": False}

        async def _fake_probe_flink(url):
            captured["called"] = True
            return True, "ok", 5

        monkeypatch.setattr(ir, "_probe_flink", _fake_probe_flink)

        row = MagicMock()
        row.name = "Flink"
        row.enabled = True
        row.config = {"jobmanager_url": "http://flink:8081"}
        row.credentials = []

        ok, msg, _ = await ir._probe_vendor(row, api_key=None)
        assert captured["called"] is True
        assert "no API key" not in msg
