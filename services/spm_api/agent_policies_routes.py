"""HTTP endpoints for attaching/detaching CPM policies to/from agents.

Backed by the ``agent_policies`` join table (Phase 4, Alembic 006).

Surface
───────
  GET    /api/spm/agents/{id}/policies              → [{policy_id, attached_at, attached_by}, ...]
  PUT    /api/spm/agents/{id}/policies              → atomic replace, body: {policy_ids: [...]}
  POST   /api/spm/agents/{id}/policies/{policy_id}  → attach one
  DELETE /api/spm/agents/{id}/policies/{policy_id}  → detach

Reads use ``verify_jwt`` (any authenticated user); writes use
``require_admin`` so non-admins can't hand themselves additional
policy coverage. The ``attached_by`` column records the JWT ``sub``
on every write so the audit trail names the actor.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete as sa_delete, select

from spm.db.models  import Agent, AgentPolicy   # type: ignore
from spm.db.session import get_db               # type: ignore

# Re-use the auth wrappers in agent_routes (same lazy-resolution
# trick that handles the bare-vs-packaged import for the spm-api
# Dockerfile's flat layout).
try:
    from agent_routes import (                   # type: ignore
        require_admin, verify_jwt, _app_module,
    )
except ModuleNotFoundError:                      # pragma: no cover
    from services.spm_api.agent_routes import (
        require_admin, verify_jwt, _app_module,
    )


router = APIRouter(prefix="/agents", tags=["agents"])


# ─── Helpers ───────────────────────────────────────────────────────────────

async def _get_agent_or_404(db, agent_id: str) -> Agent:
    res = db.get(Agent, agent_id)
    if hasattr(res, "__await__"):
        res = await res
    if res is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return res


def _row_to_dict(row: AgentPolicy) -> Dict[str, Any]:
    return {
        "policy_id":   row.policy_id,
        "attached_at": row.attached_at.isoformat() if row.attached_at else None,
        "attached_by": row.attached_by,
    }


async def _list_rows(db, agent_id: str) -> List[AgentPolicy]:
    if hasattr(db, "execute"):
        result = await db.execute(
            select(AgentPolicy).where(AgentPolicy.agent_id == agent_id)
        )
        return list(result.scalars().all())
    # sync mock path
    return list(db.query(AgentPolicy)
                  .filter(AgentPolicy.agent_id == agent_id).all())


async def _commit(db) -> None:
    res = db.commit()
    if hasattr(res, "__await__"):
        await res


def _actor(claims: Dict[str, Any]) -> str:
    return (claims.get("sub") or claims.get("email")
             or claims.get("user") or "system")


# ─── GET — list current attachments ────────────────────────────────────────

@router.get("/{agent_id}/policies")
async def list_agent_policies(
    agent_id: str,
    db = Depends(get_db),
    _claims = Depends(verify_jwt),
) -> List[Dict[str, Any]]:
    await _get_agent_or_404(db, agent_id)
    rows = await _list_rows(db, agent_id)
    return [_row_to_dict(r) for r in rows]


# ─── PUT — atomic replace ──────────────────────────────────────────────────

@router.put("/{agent_id}/policies")
async def replace_agent_policies(
    agent_id: str,
    body: Dict[str, Any],
    db = Depends(get_db),
    claims = Depends(require_admin),
) -> List[Dict[str, Any]]:
    """Replace the agent's policy set atomically.

    Body: ``{"policy_ids": ["pol-001", "pol-002"]}``. Empty list clears.
    Returns the new full set so callers don't need a follow-up GET.
    """
    await _get_agent_or_404(db, agent_id)
    raw = body.get("policy_ids") if isinstance(body, dict) else None
    if not isinstance(raw, list):
        raise HTTPException(
            status_code=400,
            detail="`policy_ids` must be a list of strings",
        )
    desired = {str(p).strip() for p in raw if isinstance(p, (str, int))}

    # Wipe and re-insert. Cheap because the table has at most a few
    # rows per agent; saves us the diff complexity.
    if hasattr(db, "execute"):
        await db.execute(
            sa_delete(AgentPolicy).where(AgentPolicy.agent_id == agent_id)
        )
    else:
        for r in await _list_rows(db, agent_id):
            db.delete(r)

    actor = _actor(claims)
    for pid in sorted(desired):
        if not pid:
            continue
        db.add(AgentPolicy(
            agent_id=agent_id, policy_id=pid, attached_by=actor,
        ))
    await _commit(db)

    rows = await _list_rows(db, agent_id)
    return [_row_to_dict(r) for r in rows]


# ─── POST — attach one ─────────────────────────────────────────────────────

@router.post(
    "/{agent_id}/policies/{policy_id}",
    status_code=status.HTTP_201_CREATED,
)
async def attach_policy(
    agent_id: str,
    policy_id: str,
    db = Depends(get_db),
    claims = Depends(require_admin),
) -> Dict[str, Any]:
    await _get_agent_or_404(db, agent_id)
    pid = policy_id.strip()
    if not pid:
        raise HTTPException(status_code=400, detail="policy_id is empty")

    # Upsert-style — if it's already attached, return the existing
    # row instead of 409. Operators retry attach()/detach() in scripts
    # and getting a clean idempotent response is friendlier than a
    # constraint violation.
    if hasattr(db, "execute"):
        existing = (await db.execute(
            select(AgentPolicy)
            .where(AgentPolicy.agent_id == agent_id)
            .where(AgentPolicy.policy_id == pid)
        )).scalar_one_or_none()
    else:
        existing = next(
            (r for r in await _list_rows(db, agent_id) if r.policy_id == pid),
            None,
        )
    if existing is not None:
        return _row_to_dict(existing)

    row = AgentPolicy(agent_id=agent_id, policy_id=pid,
                      attached_by=_actor(claims))
    db.add(row)
    await _commit(db)
    return _row_to_dict(row)


# ─── DELETE — detach one ───────────────────────────────────────────────────

@router.delete(
    "/{agent_id}/policies/{policy_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def detach_policy(
    agent_id: str,
    policy_id: str,
    db = Depends(get_db),
    _claims = Depends(require_admin),
):
    await _get_agent_or_404(db, agent_id)
    pid = policy_id.strip()
    if hasattr(db, "execute"):
        await db.execute(
            sa_delete(AgentPolicy)
            .where(AgentPolicy.agent_id == agent_id)
            .where(AgentPolicy.policy_id == pid)
        )
    else:
        for r in await _list_rows(db, agent_id):
            if r.policy_id == pid:
                db.delete(r)
    await _commit(db)
    return None
