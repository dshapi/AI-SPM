"""
tests/policies/test_store.py
Tests for the DB-backed policy store.
"""
import pytest
from policies import store
from policies.seed import seed_policies
from policies.models import PolicyCreate, PolicyUpdate


# ── Seed ─────────────────────────────────────────────────────────────────────

def test_seed_creates_nine_policies(db_session):
    store.init_db_for_session(db_session)
    seed_policies()
    assert len(store.list_policies()) == 9


def test_seed_idempotent(db_session):
    store.init_db_for_session(db_session)
    seed_policies()
    seed_policies()
    assert len(store.list_policies()) == 9


def test_seed_prompt_guard_present(db_session):
    store.init_db_for_session(db_session)
    seed_policies()
    names = [p["name"] for p in store.list_policies()]
    assert "Prompt-Guard" in names


# ── CRUD ─────────────────────────────────────────────────────────────────────

def test_create_and_get(db_session):
    store.init_db_for_session(db_session)
    p = store.create_policy(PolicyCreate(
        name="Test", type="prompt-safety", mode="Enforce",
        status="Active", scope="All", owner="ops",
        description="desc", logic_code="allow = true", logic_language="rego",
        agents=[], tools=[], data_sources=[], environments=[], exceptions=[],
    ), actor="test")
    assert p["name"] == "Test"
    assert p["version"] == "v1"
    fetched = store.get_policy(p["id"])
    assert fetched is not None
    assert fetched["id"] == p["id"]


def test_get_missing_returns_none(db_session):
    store.init_db_for_session(db_session)
    assert store.get_policy("no-such-id") is None


def test_list_policies(db_session):
    store.init_db_for_session(db_session)
    store.create_policy(PolicyCreate(name="A", type="privacy",    logic_code=""), actor="t")
    store.create_policy(PolicyCreate(name="B", type="data-access", logic_code=""), actor="t")
    assert len(store.list_policies()) == 2


def test_update_policy(db_session):
    store.init_db_for_session(db_session)
    p = store.create_policy(PolicyCreate(name="X", type="privacy", logic_code=""), actor="t")
    updated = store.update_policy(p["id"], PolicyUpdate(mode="Monitor"), actor="t")
    assert updated["mode"] == "Monitor"
    assert updated["version"] == "v2"
    assert len(updated["history"]) == 2


def test_update_missing_returns_none(db_session):
    store.init_db_for_session(db_session)
    assert store.update_policy("ghost", PolicyUpdate(mode="Monitor")) is None


def test_delete_policy(db_session):
    store.init_db_for_session(db_session)
    p = store.create_policy(PolicyCreate(name="Del", type="privacy", logic_code=""), actor="t")
    assert store.delete_policy(p["id"]) is True
    assert store.get_policy(p["id"]) is None


def test_delete_missing_returns_false(db_session):
    store.init_db_for_session(db_session)
    assert store.delete_policy("ghost") is False


def test_duplicate_policy(db_session):
    store.init_db_for_session(db_session)
    p = store.create_policy(PolicyCreate(name="Orig", type="privacy", logic_code="x = 1"), actor="t")
    dup = store.duplicate_policy(p["id"], actor="t")
    assert dup["name"] == "Orig (Copy)"
    assert dup["version"] == "v1"
    assert dup["id"] != p["id"]
    assert dup["logic_code"] == "x = 1"


def test_duplicate_missing_returns_none(db_session):
    store.init_db_for_session(db_session)
    assert store.duplicate_policy("ghost") is None


# ── Version restore ───────────────────────────────────────────────────────────

def test_restore_policy(db_session):
    store.init_db_for_session(db_session)
    p = store.create_policy(PolicyCreate(name="R", type="privacy", logic_code="original"), actor="t")
    v1 = p["version"]
    store.update_policy(p["id"], PolicyUpdate(logic_code="updated"), actor="t")
    restored = store.restore_policy(p["id"], v1)
    assert restored is not None
    assert restored["logic_code"] == "original"
    assert restored["version"] == "v3"


def test_restore_missing_version_returns_none(db_session):
    store.init_db_for_session(db_session)
    p = store.create_policy(PolicyCreate(name="R2", type="privacy", logic_code="x"), actor="t")
    assert store.restore_policy(p["id"], "v99") is None


def test_list_restorable_versions(db_session):
    store.init_db_for_session(db_session)
    p = store.create_policy(PolicyCreate(name="R3", type="privacy", logic_code="a"), actor="t")
    store.update_policy(p["id"], PolicyUpdate(logic_code="b"), actor="t")
    versions = store.list_restorable_versions(p["id"])
    assert "v1" in versions
    assert "v2" not in versions   # v2 is current — not restorable to itself
