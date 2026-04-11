"""
policies/router.py
───────────────────
FastAPI router — all Policy CRUD + simulate/validate endpoints.
Mounted at /api/v1/policies in main.py.

Endpoints
─────────
GET    /api/v1/policies             → list all policies
GET    /api/v1/policies/{id}        → single policy
POST   /api/v1/policies             → create policy
PUT    /api/v1/policies/{id}        → update policy (mode, logic, etc.)
DELETE /api/v1/policies/{id}        → delete policy
POST   /api/v1/policies/{id}/duplicate        → copy a policy
POST   /api/v1/policies/{id}/simulate         → simulate on sample input
POST   /api/v1/policies/{id}/validate         → static analysis of logic code
POST   /api/v1/policies/{id}/restore          → restore to a prior version snapshot
GET    /api/v1/policies/{id}/restorable       → list versions with available snapshots
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .models import PolicyCreate, PolicyUpdate, SimulateRequest
from .service import simulate_policy, validate_policy
from .lifecycle import PolicyState, TransitionError, can_be_runtime_active, map_mode_to_state
from .repository import VersionRepository
from . import store

router = APIRouter(prefix="/api/v1/policies", tags=["policies"])


# ── Helper ────────────────────────────────────────────────────────────────────

def _get_or_404(policy_id: str) -> dict:
    p = store.get_policy(policy_id)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Policy '{policy_id}' not found.")
    return p


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("", summary="List all policies")
def list_policies():
    return [_enrich(p) for p in store.list_policies()]


@router.get("/{policy_id}", summary="Get single policy")
def get_policy(policy_id: str):
    return _enrich(_get_or_404(policy_id))


@router.post("", status_code=201, summary="Create policy")
def create_policy(body: PolicyCreate):
    return store.create_policy(body, actor="api-user")


@router.put("/{policy_id}", summary="Update policy")
def update_policy(policy_id: str, body: PolicyUpdate):
    _get_or_404(policy_id)
    updated = store.update_policy(policy_id, body, actor="api-user")
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Policy '{policy_id}' not found.")
    return updated


@router.delete("/{policy_id}", status_code=204, summary="Delete policy")
def delete_policy(policy_id: str):
    _get_or_404(policy_id)
    store.delete_policy(policy_id)
    return None


# ── Special actions ───────────────────────────────────────────────────────────

@router.post("/{policy_id}/duplicate", status_code=201, summary="Duplicate a policy")
def duplicate_policy(policy_id: str):
    _get_or_404(policy_id)
    copy = store.duplicate_policy(policy_id, actor="api-user")
    if copy is None:
        raise HTTPException(status_code=500, detail="Duplication failed.")
    return copy


@router.post("/{policy_id}/simulate", summary="Simulate policy on sample input")
def simulate(policy_id: str, body: SimulateRequest):
    policy = _get_or_404(policy_id)
    return simulate_policy(policy, body.input)


@router.post("/{policy_id}/validate", summary="Validate policy logic (static analysis)")
def validate(policy_id: str):
    policy = _get_or_404(policy_id)
    return validate_policy(policy)


class RestoreRequest(BaseModel):
    target_version: str


@router.post("/{policy_id}/restore", summary="Restore policy to a prior version snapshot")
def restore_policy(policy_id: str, body: RestoreRequest):
    _get_or_404(policy_id)
    restored = store.restore_policy(policy_id, body.target_version, actor="api-user")
    if restored is None:
        raise HTTPException(
            status_code=404,
            detail=f"No snapshot available for version '{body.target_version}' of policy '{policy_id}'.",
        )
    return restored


@router.get("/{policy_id}/restorable", summary="List versions with available snapshots")
def list_restorable(policy_id: str):
    _get_or_404(policy_id)
    versions = store.list_restorable_versions(policy_id)
    return {"versions": versions}


# ── Lifecycle helpers ─────────────────────────────────────────────────────────

def _version_repo() -> VersionRepository:
    """Create a VersionRepository backed by the current store session factory."""
    sess = store._get_or_new_session()
    return VersionRepository(sess)


def _to_version_dict(v) -> dict:
    """Serialise a PolicyVersionORM to a JSON-safe dict."""
    return {
        "id":                    v.id,
        "policy_id":             v.policy_id,
        "version_number":        v.version_number,
        "version_str":           v.version_str,
        "state":                 v.state,
        "is_active":             bool(v.is_runtime_active),
        "is_runtime_active":     bool(v.is_runtime_active),
        "created_by":            v.created_by,
        "created_at":            v.created_at.isoformat() if v.created_at else None,
        "change_summary":        v.change_summary,
        "restored_from_version": v.restored_from_version,
        "logic_code":            v.logic_code,
        "logic_language":        v.logic_language,
    }


def _enrich(policy_dict: dict) -> dict:
    """
    Add `state` and `is_active` to an existing policy dict using the
    PolicyVersionORM table if available, falling back to legacy mode mapping.
    """
    pid = policy_dict.get("id")
    if pid:
        try:
            repo = _version_repo()
            current = repo.get_current_version(pid)
            if current:
                policy_dict["state"]     = current.state
                policy_dict["is_active"] = bool(current.is_runtime_active)
                return policy_dict
        except Exception:
            pass
    # Fallback: derive state from legacy mode field
    mode = policy_dict.get("mode", "Draft")
    policy_dict["state"]     = map_mode_to_state(mode).value
    policy_dict["is_active"] = (mode.lower() in ("enforce", "active"))
    return policy_dict


# ── Request models ────────────────────────────────────────────────────────────

class PromoteRequest(BaseModel):
    target_state: str
    actor: str = "api-user"
    reason: str = ""


class RestoreVersionRequest(BaseModel):
    actor: str = "api-user"
    reason: str = ""


# ── New lifecycle endpoints ───────────────────────────────────────────────────

@router.get("/{policy_id}/versions", summary="List all versions for a policy")
def list_versions(policy_id: str):
    _get_or_404(policy_id)
    repo = _version_repo()
    versions = repo.list_versions(policy_id)
    return {"policy_id": policy_id, "versions": [_to_version_dict(v) for v in versions]}


@router.post("/{policy_id}/versions/{version_number}/promote",
             summary="Promote a version to a new lifecycle state")
def promote_version(policy_id: str, version_number: int, body: PromoteRequest):
    _get_or_404(policy_id)
    try:
        target = PolicyState(body.target_state)
    except ValueError:
        valid_values = [s.value for s in PolicyState]
        detail_msg = "Invalid target_state " + repr(body.target_state) + ". Valid values: " + str(valid_values)
        raise HTTPException(
            status_code=422,
            detail=detail_msg,
        )
    repo = _version_repo()
    try:
        promoted = repo.promote_version(
            policy_id, version_number, target,
            actor=body.actor, reason=body.reason,
        )
    except TransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Auto-activate when promoting to enforced or monitor
    if can_be_runtime_active(target):
        try:
            repo.set_runtime_active(policy_id, version_number, actor=body.actor)
            latest = repo.get_current_version(policy_id)
            if latest and latest.version_number == version_number:
                promoted = latest
        except Exception:
            pass   # activation failure is not fatal — state was already changed

    return _to_version_dict(promoted)


@router.post("/{policy_id}/versions/{version_number}/restore",
             status_code=201,
             summary="Restore a prior version as a new draft")
def restore_version_lifecycle(policy_id: str, version_number: int, body: RestoreVersionRequest):
    _get_or_404(policy_id)
    repo = _version_repo()
    try:
        restored = repo.restore_version(
            policy_id,
            from_version_number=version_number,
            actor=body.actor,
            reason=body.reason,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _to_version_dict(restored)


@router.get("/{policy_id}/audit", summary="Audit log for lifecycle transitions")
def get_audit(policy_id: str):
    _get_or_404(policy_id)
    repo = _version_repo()
    return {"policy_id": policy_id, "audit": repo.list_audit(policy_id)}


@router.get("/{policy_id}/runtime", summary="Get the runtime-active version")
def get_runtime(policy_id: str):
    _get_or_404(policy_id)
    repo = _version_repo()
    active = repo.get_runtime_policy(policy_id)
    return {
        "policy_id":      policy_id,
        "runtime_active": _to_version_dict(active) if active else None,
    }
