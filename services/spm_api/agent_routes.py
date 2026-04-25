"""HTTP endpoints for the agent runtime control plane.

Surface
───────
  POST   /api/spm/agents              — multipart upload + validate + (optionally) deploy
  GET    /api/spm/agents              — list (filter by tenant)
  GET    /api/spm/agents/{id}         — detail
  PATCH  /api/spm/agents/{id}         — partial update of safe fields
  DELETE /api/spm/agents/{id}         — retire (stop + delete topics + drop row)
  POST   /api/spm/agents/{id}/start   — async kick to spawn the container
  POST   /api/spm/agents/{id}/stop    — async kick to stop the container

Security
────────
* Reads  → ``verify_jwt`` (any authenticated user).
* Writes → ``require_admin`` (must carry ``spm:admin`` role).
* Tenant scoping is best-effort in V1: the JWT's tenant claim filters
  the list. Phase 2 enforces strict isolation across every endpoint.

Per the spec, ``mcp_token`` and ``llm_api_key`` are NEVER returned in
any response. The serializer in ``_to_dict`` strips them defensively.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Path as PathParam,
    UploadFile,
    status,
)

# Controller / validator — the spm_api service flattens its dir onto
# /app/ so siblings import bare; running tests from the repo root falls
# through to the packaged path.
try:
    from agent_controller import (                       # type: ignore
        deploy_agent, mint_agent_tokens,
        retire_agent, start_agent, stop_agent,
    )
    from agent_validator import validate_agent_code      # type: ignore
except ModuleNotFoundError:                              # pragma: no cover
    from services.spm_api.agent_controller import (
        deploy_agent, mint_agent_tokens,
        retire_agent, start_agent, stop_agent,
    )
    from services.spm_api.agent_validator import validate_agent_code

from spm.db.models  import Agent             # type: ignore
from spm.db.session import get_db            # type: ignore


# ─── Auth wrappers ─────────────────────────────────────────────────────────
#
# Defined locally (rather than imported from app) for two reasons:
#   1. Avoid the circular import — app.py imports our router at the
#      bottom; if we imported from app at module load we'd deadlock.
#   2. In the monorepo test env both ``services/api/app.py`` and
#      ``services/spm_api/app.py`` sit on sys.path; ``import app`` can
#      win whichever way and only one of them defines verify_jwt.
#      Same lazy-resolution dance integrations_routes.py uses.

def _app_module():
    """Lazily resolve the spm_api ``app`` module — the only one that
    defines ``verify_jwt`` / ``require_admin`` / ``_tenant_from_claims``."""
    try:
        import app as _m  # type: ignore
        if hasattr(_m, "verify_jwt"):
            return _m
    except ModuleNotFoundError:
        pass
    from services.spm_api import app as _m  # type: ignore
    return _m


def verify_jwt(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """Wrapper that delegates to ``app.verify_jwt`` after FastAPI has
    resolved the Header dependency (we pass the raw value through)."""
    return _app_module().verify_jwt(authorization=authorization)


def require_admin(claims: Dict[str, Any] = Depends(verify_jwt)) -> Dict[str, Any]:
    if "spm:admin" not in claims.get("roles", []):
        raise HTTPException(status_code=403, detail="spm:admin role required")
    return claims


def _tenant_from_claims(claims: Dict[str, Any], fallback: str = "t1") -> str:
    return _app_module()._tenant_from_claims(claims, fallback=fallback)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/spm/agents", tags=["agents"])


# ─── Disk layout for uploaded code ─────────────────────────────────────────

CODE_ROOT = Path("./DataVolums/agents")


# ─── Serializer ────────────────────────────────────────────────────────────

# Fields safe to PATCH. mcp_token / llm_api_key / runtime_state are
# managed by the controller; code_path / code_sha256 are managed by the
# upload pipeline; tenant_id never changes for a row.
ALLOWED_PATCH_FIELDS = {
    "description", "owner", "risk", "policy_status",
    "version", "agent_type", "name",
}


def _to_dict(a: Agent, *, warnings: Optional[List[str]] = None) -> Dict[str, Any]:
    """Public JSON shape. NEVER includes mcp_token / llm_api_key."""
    d: Dict[str, Any] = {
        "id":             str(a.id),
        "name":           a.name,
        "version":        a.version,
        "agent_type":     a.agent_type if not hasattr(a.agent_type, "value")
                          else a.agent_type.value,
        "provider":       a.provider if not hasattr(a.provider, "value")
                          else a.provider.value,
        "owner":          a.owner,
        "description":    a.description,
        "risk":           a.risk if not hasattr(a.risk, "value")
                          else a.risk.value,
        "policy_status":  a.policy_status if not hasattr(a.policy_status, "value")
                          else a.policy_status.value,
        "runtime_state":  a.runtime_state if not hasattr(a.runtime_state, "value")
                          else a.runtime_state.value,
        "code_path":      a.code_path,
        "code_sha256":    a.code_sha256,
        "tenant_id":      a.tenant_id,
        "created_at":     a.created_at.isoformat() if a.created_at else None,
        "updated_at":     a.updated_at.isoformat() if a.updated_at else None,
        "last_seen_at":   a.last_seen_at.isoformat() if a.last_seen_at else None,
    }
    if warnings is not None:
        d["warnings"] = warnings
    return d


# ─── POST /agents — upload + validate ──────────────────────────────────────

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_agent(
    name:         str        = Form(...),
    version:      str        = Form(...),
    agent_type:   str        = Form(...),
    owner:        Optional[str] = Form(None),
    description:  str        = Form(""),
    deploy_after: bool       = Form(True),
    code:         UploadFile = File(...),
    db = Depends(get_db),
    claims = Depends(require_admin),
):
    """Upload an ``agent.py``, validate it, persist the row, and
    optionally trigger deploy.

    Returns 201 + the agent JSON on success, 422 with the offending
    error list on validation failure.
    """
    raw = (await code.read()).decode("utf-8", errors="replace")
    res = validate_agent_code(raw)
    if not res.ok:
        raise HTTPException(status_code=422, detail=res.errors)

    agent_id  = uuid.uuid4()
    tenant_id = _tenant_from_claims(claims, fallback="t1")

    code_dir = CODE_ROOT / str(agent_id)
    code_dir.mkdir(parents=True, exist_ok=True)
    code_file = code_dir / "agent.py"
    code_file.write_text(raw)
    sha = hashlib.sha256(raw.encode()).hexdigest()

    mcp_t, llm_t = mint_agent_tokens()

    a = Agent(
        id=agent_id, name=name, version=version, agent_type=agent_type,
        provider="internal", owner=owner, description=description,
        code_path=str(code_file), code_sha256=sha,
        mcp_token=mcp_t, llm_api_key=llm_t,
        tenant_id=tenant_id, runtime_state="stopped",
    )
    db.add(a)
    await _maybe_async_commit(db)
    await _maybe_async_refresh(db, a)

    if deploy_after:
        try:
            await deploy_agent(db, agent_id)
        except Exception as e:                            # noqa: BLE001
            # Deploy failures shouldn't lose the row — the operator
            # can fix and retry via the start endpoint. Log and keep.
            log.warning("deploy after upload failed: %s", e)

    return _to_dict(a, warnings=res.warnings)


# ─── GET /agents — list ────────────────────────────────────────────────────

@router.get("")
async def list_agents(
    db = Depends(get_db),
    claims = Depends(verify_jwt),
):
    """List agents in the caller's tenant. V1 falls back to ``"t1"`` if
    the JWT lacks a tenant claim — matches the migration seed."""
    tenant_id = _tenant_from_claims(claims, fallback="t1")
    rows = await _list_agents_in_tenant(db, tenant_id)
    return [_to_dict(a) for a in rows]


# ─── GET /agents/{id} — detail ─────────────────────────────────────────────

@router.get("/{agent_id}")
async def get_agent(
    agent_id: str = PathParam(...),
    db = Depends(get_db),
    _claims = Depends(verify_jwt),
):
    a = await _get_agent_or_none(db, agent_id)
    if a is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return _to_dict(a)


# ─── PATCH /agents/{id} ────────────────────────────────────────────────────

@router.patch("/{agent_id}")
async def patch_agent(
    agent_id: str,
    body: Dict[str, Any],
    db = Depends(get_db),
    _claims = Depends(require_admin),
):
    a = await _get_agent_or_none(db, agent_id)
    if a is None:
        raise HTTPException(status_code=404, detail="agent not found")

    unknown = set(body.keys()) - ALLOWED_PATCH_FIELDS
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"unknown / disallowed fields: {sorted(unknown)}",
        )

    for k, v in body.items():
        setattr(a, k, v)
    await _maybe_async_commit(db)
    await _maybe_async_refresh(db, a)
    return _to_dict(a)


# ─── POST /agents/{id}/start | /stop ───────────────────────────────────────

@router.post("/{agent_id}/start", status_code=status.HTTP_202_ACCEPTED)
async def start_endpoint(
    agent_id: str,
    db = Depends(get_db),
    _claims = Depends(require_admin),
):
    await start_agent(db, agent_id)
    return {"status": "starting"}


@router.post("/{agent_id}/stop", status_code=status.HTTP_202_ACCEPTED)
async def stop_endpoint(
    agent_id: str,
    db = Depends(get_db),
    _claims = Depends(require_admin),
):
    await stop_agent(db, agent_id)
    return {"status": "stopping"}


# ─── DELETE /agents/{id} ───────────────────────────────────────────────────

@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_endpoint(
    agent_id: str,
    db = Depends(get_db),
    _claims = Depends(require_admin),
):
    await retire_agent(db, agent_id)
    # 204 — body must be empty.
    return None


# ─── DB helpers — async-vs-sync session compatibility ──────────────────────
#
# The dependency ``get_db`` yields an ``AsyncSession`` in production but
# tests sometimes hand in a sync ``MagicMock``. These helpers normalize
# the call sites so the route code reads cleanly either way.

async def _maybe_async_commit(db) -> None:
    fn = getattr(db, "commit", None)
    if fn is None:
        return
    res = fn()
    if hasattr(res, "__await__"):
        await res


async def _maybe_async_refresh(db, obj) -> None:
    fn = getattr(db, "refresh", None)
    if fn is None:
        return
    res = fn(obj)
    if hasattr(res, "__await__"):
        await res


async def _get_agent_or_none(db, agent_id) -> Optional[Agent]:
    res = db.get(Agent, agent_id)
    if hasattr(res, "__await__"):
        return await res
    return res


async def _list_agents_in_tenant(db, tenant_id: str) -> List[Agent]:
    """Return all agents in *tenant_id*. Works against both AsyncSession
    and sync mock sessions — the latter just returns from ``db.query()``.
    """
    # Real path: AsyncSession with execute(select).
    if hasattr(db, "execute"):
        from sqlalchemy import select  # type: ignore
        result = await db.execute(
            select(Agent).where(Agent.tenant_id == tenant_id)
        )
        return list(result.scalars().all())
    # Fallback for legacy / sync mocks.
    return list(db.query(Agent).filter(Agent.tenant_id == tenant_id).all())
