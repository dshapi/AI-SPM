"""
tests/policies/test_router.py
──────────────────────────────
Regression tests for the policies HTTP layer.

These tests hit every endpoint through FastAPI's TestClient — verifying
status codes, response shape, and error handling for all 10 routes:

    GET    /api/v1/policies
    GET    /api/v1/policies/{id}
    POST   /api/v1/policies
    PUT    /api/v1/policies/{id}
    DELETE /api/v1/policies/{id}
    POST   /api/v1/policies/{id}/duplicate
    POST   /api/v1/policies/{id}/simulate
    POST   /api/v1/policies/{id}/validate
    POST   /api/v1/policies/{id}/restore       ← NEW
    GET    /api/v1/policies/{id}/restorable    ← NEW

Fixture strategy
────────────────
Each test gets a fresh in-memory SQLite DB via the `db_session` fixture
(defined in conftest.py) injected into the store via init_db_for_session().
A minimal FastAPI app is created with only the policies router — no Kafka,
no async engine, no auth middleware required.
"""
from __future__ import annotations

import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from policies import store as policy_store
from policies.router import router as policies_router

# ── Minimal test app fixture ──────────────────────────────────────────────────

@pytest.fixture()
def client():
    """
    Yield a TestClient backed by a fresh SQLite file DB per test.

    Why a temp file instead of :memory: + init_db_for_session:
    FastAPI runs synchronous route handlers in threadpool workers.
    A Session created on the test thread cannot be used from a worker
    thread (sqlite3 raises ProgrammingError: object created in thread X,
    used in thread Y).  A file-based SQLite DB sidesteps this — SQLAlchemy
    creates a new connection per thread from its pool, each backed by the
    same on-disk file.  Tests stay isolated because every fixture
    iteration gets its own temp file.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    db_url = f"sqlite:///{db_path}"
    policy_store.init_db(db_url, create_tables=True)

    app = FastAPI()
    app.include_router(policies_router)

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    # Reset module-level state so the next fixture gets a clean slate
    policy_store._SessionLocal = None  # type: ignore[attr-defined]
    try:
        os.unlink(db_path)
    except OSError:
        pass


# ── Helpers ───────────────────────────────────────────────────────────────────

_MINIMAL = {"name": "Test Policy", "type": "prompt-safety"}
_FULL = {
    "name": "Full Policy",
    "type": "tool-access",
    "mode": "Enforce",
    "status": "Active",
    "scope": "All agents",
    "owner": "ops",
    "description": "regression test policy",
    "logic_code": "allow = true",
    "logic_language": "rego",
    "agents": ["agent-1"],
    "tools": ["web-search"],
    "data_sources": [],
    "environments": ["prod"],
    "exceptions": [],
}

def _create(client: TestClient, body: dict = None) -> dict:
    """Create a policy and return the response JSON."""
    r = client.post("/api/v1/policies", json=body or _MINIMAL)
    assert r.status_code == 201, r.text
    return r.json()


# ── GET /api/v1/policies ──────────────────────────────────────────────────────

class TestListPolicies:
    def test_empty_list(self, client):
        r = client.get("/api/v1/policies")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_all_created(self, client):
        _create(client, {"name": "A", "type": "privacy"})
        _create(client, {"name": "B", "type": "data-access"})
        r = client.get("/api/v1/policies")
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_response_has_required_fields(self, client):
        _create(client)
        items = client.get("/api/v1/policies").json()
        p = items[0]
        for field in ("id", "name", "version", "type", "mode", "status"):
            assert field in p, f"missing field: {field}"


# ── GET /api/v1/policies/{id} ─────────────────────────────────────────────────

class TestGetPolicy:
    def test_get_existing(self, client):
        created = _create(client)
        r = client.get(f"/api/v1/policies/{created['id']}")
        assert r.status_code == 200
        assert r.json()["id"] == created["id"]

    def test_get_missing_returns_404(self, client):
        r = client.get("/api/v1/policies/does-not-exist")
        assert r.status_code == 404

    def test_response_shape(self, client):
        created = _create(client, _FULL)
        p = client.get(f"/api/v1/policies/{created['id']}").json()
        assert p["name"] == _FULL["name"]
        assert p["type"] == _FULL["type"]
        assert p["mode"] == _FULL["mode"]
        assert p["logic_code"] == _FULL["logic_code"]
        assert p["agents"] == _FULL["agents"]


# ── POST /api/v1/policies ─────────────────────────────────────────────────────

class TestCreatePolicy:
    def test_creates_with_minimal_fields(self, client):
        r = client.post("/api/v1/policies", json=_MINIMAL)
        assert r.status_code == 201
        data = r.json()
        assert data["name"] == _MINIMAL["name"]
        assert data["version"] == "v1"
        assert "id" in data

    def test_creates_with_all_fields(self, client):
        r = client.post("/api/v1/policies", json=_FULL)
        assert r.status_code == 201
        data = r.json()
        assert data["mode"] == "Enforce"
        assert data["agents"] == ["agent-1"]

    def test_missing_required_name_returns_422(self, client):
        r = client.post("/api/v1/policies", json={"type": "privacy"})
        assert r.status_code == 422

    def test_missing_required_type_returns_422(self, client):
        r = client.post("/api/v1/policies", json={"name": "No Type"})
        assert r.status_code == 422

    def test_empty_body_returns_422(self, client):
        r = client.post("/api/v1/policies", json={})
        assert r.status_code == 422

    def test_history_starts_with_one_entry(self, client):
        created = _create(client)
        assert len(created["history"]) == 1
        assert created["history"][0]["version"] == "v1"


# ── PUT /api/v1/policies/{id} ─────────────────────────────────────────────────

class TestUpdatePolicy:
    def test_update_mode(self, client):
        created = _create(client)
        r = client.put(f"/api/v1/policies/{created['id']}", json={"mode": "Block"})
        assert r.status_code == 200
        assert r.json()["mode"] == "Block"

    def test_update_bumps_version(self, client):
        created = _create(client)
        r = client.put(f"/api/v1/policies/{created['id']}", json={"mode": "Block"})
        assert r.json()["version"] == "v2"

    def test_update_appends_history(self, client):
        created = _create(client)
        r = client.put(f"/api/v1/policies/{created['id']}", json={"mode": "Monitor"})
        assert len(r.json()["history"]) == 2

    def test_update_missing_returns_404(self, client):
        r = client.put("/api/v1/policies/ghost", json={"mode": "Block"})
        assert r.status_code == 404

    def test_update_logic_code(self, client):
        created = _create(client, {**_MINIMAL, "logic_code": "allow = false"})
        r = client.put(
            f"/api/v1/policies/{created['id']}",
            json={"logic_code": "allow = true"},
        )
        assert r.status_code == 200
        assert r.json()["logic_code"] == "allow = true"

    def test_partial_update_preserves_other_fields(self, client):
        created = _create(client, _FULL)
        r = client.put(f"/api/v1/policies/{created['id']}", json={"mode": "Monitor"})
        updated = r.json()
        assert updated["name"] == _FULL["name"]         # untouched
        assert updated["agents"] == _FULL["agents"]     # untouched
        assert updated["mode"] == "Monitor"             # changed


# ── DELETE /api/v1/policies/{id} ──────────────────────────────────────────────

class TestDeletePolicy:
    def test_delete_existing_returns_204(self, client):
        created = _create(client)
        r = client.delete(f"/api/v1/policies/{created['id']}")
        assert r.status_code == 204

    def test_deleted_policy_not_found_afterwards(self, client):
        created = _create(client)
        client.delete(f"/api/v1/policies/{created['id']}")
        assert client.get(f"/api/v1/policies/{created['id']}").status_code == 404

    def test_delete_missing_returns_404(self, client):
        r = client.delete("/api/v1/policies/ghost")
        assert r.status_code == 404

    def test_delete_reduces_list_count(self, client):
        a = _create(client, {"name": "A", "type": "privacy"})
        _create(client, {"name": "B", "type": "privacy"})
        client.delete(f"/api/v1/policies/{a['id']}")
        assert len(client.get("/api/v1/policies").json()) == 1


# ── POST /api/v1/policies/{id}/duplicate ─────────────────────────────────────

class TestDuplicatePolicy:
    def test_duplicate_returns_201(self, client):
        created = _create(client)
        r = client.post(f"/api/v1/policies/{created['id']}/duplicate")
        assert r.status_code == 201

    def test_duplicate_has_copy_suffix(self, client):
        created = _create(client, {"name": "Original", "type": "privacy"})
        dup = client.post(f"/api/v1/policies/{created['id']}/duplicate").json()
        assert "Copy" in dup["name"]

    def test_duplicate_has_different_id(self, client):
        created = _create(client)
        dup = client.post(f"/api/v1/policies/{created['id']}/duplicate").json()
        assert dup["id"] != created["id"]

    def test_duplicate_starts_at_v1(self, client):
        created = _create(client)
        client.put(f"/api/v1/policies/{created['id']}", json={"mode": "Block"})  # bump to v2
        dup = client.post(f"/api/v1/policies/{created['id']}/duplicate").json()
        assert dup["version"] == "v1"

    def test_duplicate_copies_logic_code(self, client):
        created = _create(client, {**_MINIMAL, "logic_code": "deny = true"})
        dup = client.post(f"/api/v1/policies/{created['id']}/duplicate").json()
        assert dup["logic_code"] == "deny = true"

    def test_duplicate_missing_returns_404(self, client):
        r = client.post("/api/v1/policies/ghost/duplicate")
        assert r.status_code == 404

    def test_duplicate_appears_in_list(self, client):
        created = _create(client)
        client.post(f"/api/v1/policies/{created['id']}/duplicate")
        assert len(client.get("/api/v1/policies").json()) == 2


# ── POST /api/v1/policies/{id}/simulate ──────────────────────────────────────

class TestSimulatePolicy:
    def test_simulate_returns_200(self, client):
        created = _create(client)
        r = client.post(
            f"/api/v1/policies/{created['id']}/simulate",
            json={"input": {"prompt": "test"}},
        )
        assert r.status_code == 200

    def test_simulate_response_shape(self, client):
        created = _create(client)
        r = client.post(
            f"/api/v1/policies/{created['id']}/simulate",
            json={"input": {"prompt": "hello"}},
        )
        data = r.json()
        assert "decision" in data
        assert "reason" in data
        assert "policy_id" in data
        assert data["policy_id"] == created["id"]

    def test_simulate_default_input_works(self, client):
        """Omitting `input` uses the default from SimulateRequest."""
        created = _create(client)
        r = client.post(f"/api/v1/policies/{created['id']}/simulate", json={})
        assert r.status_code == 200

    def test_simulate_missing_policy_returns_404(self, client):
        r = client.post("/api/v1/policies/ghost/simulate", json={"input": {}})
        assert r.status_code == 404


# ── POST /api/v1/policies/{id}/validate ──────────────────────────────────────

class TestValidatePolicy:
    def test_validate_returns_200(self, client):
        created = _create(client)
        r = client.post(f"/api/v1/policies/{created['id']}/validate")
        assert r.status_code == 200

    def test_validate_response_shape(self, client):
        created = _create(client)
        data = client.post(f"/api/v1/policies/{created['id']}/validate").json()
        assert "valid" in data
        assert "errors" in data
        assert "warnings" in data
        assert "policy_id" in data

    def test_validate_empty_logic_is_invalid(self, client):
        created = _create(client, {**_MINIMAL, "logic_code": ""})
        data = client.post(f"/api/v1/policies/{created['id']}/validate").json()
        assert data["valid"] is False
        assert len(data["errors"]) > 0

    def test_validate_with_logic_code_is_valid(self, client):
        # Rego requires a `package` declaration to be considered valid
        valid_rego = "package policy\ndefault allow = false\nallow { input.ok }"
        created = _create(client, {**_MINIMAL, "logic_code": valid_rego})
        data = client.post(f"/api/v1/policies/{created['id']}/validate").json()
        assert data["valid"] is True

    def test_validate_missing_policy_returns_404(self, client):
        r = client.post("/api/v1/policies/ghost/validate")
        assert r.status_code == 404


# ── POST /api/v1/policies/{id}/restore  (NEW) ────────────────────────────────

class TestRestorePolicy:
    def _policy_with_history(self, client) -> tuple[dict, str]:
        """Create a policy, mutate it, return (current_policy, original_version)."""
        created = _create(client, {**_MINIMAL, "logic_code": "original"})
        v1 = created["version"]
        client.put(f"/api/v1/policies/{created['id']}", json={"logic_code": "updated"})
        return created, v1

    def test_restore_returns_200(self, client):
        created, v1 = self._policy_with_history(client)
        r = client.post(
            f"/api/v1/policies/{created['id']}/restore",
            json={"target_version": v1},
        )
        assert r.status_code == 200

    def test_restore_rolls_back_logic_code(self, client):
        created, v1 = self._policy_with_history(client)
        restored = client.post(
            f"/api/v1/policies/{created['id']}/restore",
            json={"target_version": v1},
        ).json()
        assert restored["logic_code"] == "original"

    def test_restore_bumps_version(self, client):
        created, v1 = self._policy_with_history(client)
        # At this point policy is at v2 after the update
        restored = client.post(
            f"/api/v1/policies/{created['id']}/restore",
            json={"target_version": v1},
        ).json()
        assert restored["version"] == "v3"

    def test_restore_appends_history_entry(self, client):
        created, v1 = self._policy_with_history(client)
        restored = client.post(
            f"/api/v1/policies/{created['id']}/restore",
            json={"target_version": v1},
        ).json()
        # v1 (create) + v2 (update) + v3 (restore) = 3 history entries
        assert len(restored["history"]) == 3

    def test_restore_missing_snapshot_returns_404(self, client):
        created = _create(client)
        r = client.post(
            f"/api/v1/policies/{created['id']}/restore",
            json={"target_version": "v99"},
        )
        assert r.status_code == 404

    def test_restore_missing_policy_returns_404(self, client):
        r = client.post(
            "/api/v1/policies/ghost/restore",
            json={"target_version": "v1"},
        )
        assert r.status_code == 404

    def test_restore_bad_body_returns_422(self, client):
        created = _create(client)
        r = client.post(f"/api/v1/policies/{created['id']}/restore", json={})
        assert r.status_code == 422

    def test_restore_preserved_in_list(self, client):
        """Restored policy should appear in list with updated version."""
        created, v1 = self._policy_with_history(client)
        client.post(
            f"/api/v1/policies/{created['id']}/restore",
            json={"target_version": v1},
        )
        policies = client.get("/api/v1/policies").json()
        match = next(p for p in policies if p["id"] == created["id"])
        assert match["version"] == "v3"


# ── GET /api/v1/policies/{id}/restorable  (NEW) ───────────────────────────────

class TestRestorableVersions:
    def test_no_history_returns_empty(self, client):
        created = _create(client)
        r = client.get(f"/api/v1/policies/{created['id']}/restorable")
        assert r.status_code == 200
        # v1 is current — no prior snapshots to restore to
        assert r.json()["versions"] == []

    def test_after_one_update_v1_is_restorable(self, client):
        created = _create(client)
        client.put(f"/api/v1/policies/{created['id']}", json={"mode": "Block"})
        r = client.get(f"/api/v1/policies/{created['id']}/restorable")
        assert r.status_code == 200
        assert "v1" in r.json()["versions"]

    def test_current_version_not_in_restorable(self, client):
        created = _create(client)
        client.put(f"/api/v1/policies/{created['id']}", json={"mode": "Block"})
        versions = client.get(f"/api/v1/policies/{created['id']}/restorable").json()["versions"]
        # current version is v2 — should not appear
        assert "v2" not in versions

    def test_multiple_updates_accumulate_snapshots(self, client):
        created = _create(client)
        client.put(f"/api/v1/policies/{created['id']}", json={"mode": "Block"})
        client.put(f"/api/v1/policies/{created['id']}", json={"mode": "Monitor"})
        versions = client.get(f"/api/v1/policies/{created['id']}/restorable").json()["versions"]
        assert "v1" in versions
        assert "v2" in versions

    def test_restorable_missing_policy_returns_404(self, client):
        r = client.get("/api/v1/policies/ghost/restorable")
        assert r.status_code == 404

    def test_response_has_versions_key(self, client):
        created = _create(client)
        r = client.get(f"/api/v1/policies/{created['id']}/restorable")
        assert "versions" in r.json()
        assert isinstance(r.json()["versions"], list)
