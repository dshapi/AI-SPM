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
    return store.list_policies()


@router.get("/{policy_id}", summary="Get single policy")
def get_policy(policy_id: str):
    return _get_or_404(policy_id)


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
