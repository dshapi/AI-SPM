"""
Tests for VersionRepository — all DB operations for PolicyVersionORM.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.base import Base
from db.models import AgentSessionORM, SessionEventORM, CaseORM  # noqa: F401
from policies.db_models import PolicyORM, PolicyVersionORM, PolicyLifecycleAuditORM  # noqa: F401
from policies.lifecycle import PolicyState, TransitionError
from policies.repository import VersionRepository


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", echo=False,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def repo(session):
    return VersionRepository(session)


def test_create_first_version(repo):
    v = repo.create_version("policy-1", logic_code="allow = true",
                             logic_language="rego", actor="test",
                             change_summary="Initial")
    assert v.version_number == 1
    assert v.version_str    == "v1"
    assert v.state          == PolicyState.DRAFT.value
    assert v.is_runtime_active == 0
    assert v.policy_id      == "policy-1"


def test_create_increments_version_number(repo):
    repo.create_version("policy-1", logic_code="a", actor="t")
    v2 = repo.create_version("policy-1", logic_code="b", actor="t")
    assert v2.version_number == 2
    assert v2.version_str    == "v2"


def test_create_audit_record_written(repo, session):
    repo.create_version("policy-1", logic_code="", actor="admin")
    audits = session.query(PolicyLifecycleAuditORM).all()
    assert len(audits) == 1
    assert audits[0].action   == "create_draft"
    assert audits[0].to_state == "draft"


def test_get_current_version_returns_latest(repo):
    repo.create_version("p", logic_code="v1", actor="t")
    repo.create_version("p", logic_code="v2", actor="t")
    current = repo.get_current_version("p")
    assert current.version_number == 2


def test_get_current_version_missing_returns_none(repo):
    assert repo.get_current_version("ghost") is None


def test_list_versions_returns_all(repo):
    repo.create_version("p", logic_code="a", actor="t")
    repo.create_version("p", logic_code="b", actor="t")
    repo.create_version("p", logic_code="c", actor="t")
    versions = repo.list_versions("p")
    assert len(versions) == 3
    assert [v.version_number for v in versions] == [1, 2, 3]


def test_list_versions_empty_policy(repo):
    assert repo.list_versions("ghost") == []


def test_promote_draft_to_monitor(repo):
    v = repo.create_version("p", logic_code="", actor="t")
    promoted = repo.promote_version("p", v.version_number,
                                     PolicyState.MONITOR, actor="t", reason="test")
    assert promoted.state == PolicyState.MONITOR.value


def test_promote_writes_audit_record(repo, session):
    v = repo.create_version("p", logic_code="", actor="t")
    repo.promote_version("p", v.version_number, PolicyState.MONITOR, actor="t", reason="r")
    audits = session.query(PolicyLifecycleAuditORM).filter_by(action="promote").all()
    assert len(audits) == 1
    assert audits[0].from_state == "draft"
    assert audits[0].to_state   == "monitor"


def test_promote_invalid_transition_raises(repo):
    v = repo.create_version("p", logic_code="", actor="t")
    repo.promote_version("p", v.version_number, PolicyState.DEPRECATED, actor="t", reason="")
    with pytest.raises(TransitionError):
        repo.promote_version("p", v.version_number, PolicyState.ENFORCED, actor="t", reason="")


def test_promote_missing_version_raises(repo):
    with pytest.raises(ValueError, match="not found"):
        repo.promote_version("p", 99, PolicyState.MONITOR, actor="t", reason="")


def test_set_runtime_active_sets_flag(repo):
    v = repo.create_version("p", logic_code="", actor="t")
    repo.promote_version("p", v.version_number, PolicyState.ENFORCED, actor="t", reason="")
    repo.set_runtime_active("p", v.version_number)
    current = repo.get_current_version("p")
    assert current.is_runtime_active == 1


def test_set_runtime_active_deactivates_old(repo):
    v1 = repo.create_version("p", logic_code="", actor="t")
    repo.promote_version("p", v1.version_number, PolicyState.ENFORCED, actor="t", reason="")
    repo.set_runtime_active("p", v1.version_number)
    v2 = repo.create_version("p", logic_code="v2", actor="t")
    repo.promote_version("p", v2.version_number, PolicyState.ENFORCED, actor="t", reason="")
    repo.set_runtime_active("p", v2.version_number)
    versions = repo.list_versions("p")
    active = [v for v in versions if v.is_runtime_active == 1]
    assert len(active) == 1
    assert active[0].version_number == 2


def test_set_active_draft_raises(repo):
    v = repo.create_version("p", logic_code="", actor="t")
    with pytest.raises(ValueError, match="cannot be runtime-active"):
        repo.set_runtime_active("p", v.version_number)


def test_restore_creates_new_version(repo):
    v1 = repo.create_version("p", logic_code="original", actor="t")
    repo.create_version("p", logic_code="updated", actor="t")  # v2
    restored = repo.restore_version("p", from_version_number=v1.version_number,
                                    actor="admin", reason="rollback")
    assert restored.version_number        == 3
    assert restored.logic_code            == "original"
    assert restored.state                 == PolicyState.DRAFT.value
    assert restored.restored_from_version == 1


def test_restore_missing_version_raises(repo):
    repo.create_version("p", logic_code="x", actor="t")
    with pytest.raises(ValueError, match="not found"):
        repo.restore_version("p", from_version_number=99, actor="t", reason="")


def test_get_runtime_policy_returns_active(repo):
    v = repo.create_version("p", logic_code="", actor="t")
    repo.promote_version("p", v.version_number, PolicyState.ENFORCED, actor="t", reason="")
    repo.set_runtime_active("p", v.version_number)
    result = repo.get_runtime_policy("p")
    assert result is not None
    assert result.is_runtime_active == 1


def test_get_runtime_policy_none_when_no_active(repo):
    repo.create_version("p", logic_code="", actor="t")
    assert repo.get_runtime_policy("p") is None


def test_list_audit_returns_all_actions(repo):
    v = repo.create_version("p", logic_code="", actor="admin")
    repo.promote_version("p", v.version_number, PolicyState.MONITOR, actor="admin", reason="go")
    audit = repo.list_audit("p")
    actions = [a["action"] for a in audit]
    assert "create_draft" in actions
    assert "promote"      in actions
