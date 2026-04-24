"""
SPM API — AI Security Posture Management control plane.

Endpoints:
  POST   /models                    Register a model
  GET    /models                    List all models (optionally filter by tenant)
  GET    /models/{model_id}         Get model detail
  PATCH  /models/{model_id}/status  Lifecycle transition
  POST   /internal/enforce/{model_id}  Internal: enforcement trigger (from aggregator)
  GET    /compliance/nist-airm/report  NIST AI RMF compliance report
  GET    /sbom/refresh              Aggregate AI-SBOM from all CPM services
  GET    /health
  GET    /metrics
  GET    /jwks                      RS256 public key in JWKS format
"""
from __future__ import annotations
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import hashlib
import pathlib

import httpx
import requests
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from spm.db.models import (
    ComplianceEvidence, ModelRegistry,
    ModelStatus, ModelProvider, ModelRiskTier, ModelType, PolicyCoverage,
)
from spm.db.session import get_db, get_engine
from spm.db.models import Base

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("spm-api")

# ── Config ────────────────────────────────────────────────────────────────────

OPA_URL               = os.getenv("OPA_URL", "http://opa:8181")
FREEZE_CONTROLLER_URL = os.getenv("FREEZE_CONTROLLER_URL", "http://freeze-controller:8090")
JWT_PUBLIC_KEY_PATH   = os.getenv("JWT_PUBLIC_KEY_PATH", "/keys/public.pem")
KAFKA_BOOTSTRAP       = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka-broker:9092")
SPM_SERVICE_JWT       = os.getenv("SPM_SERVICE_JWT", "")
# Default upload dir lives under the spm_api service directory, e.g.
#   services/spm_api/models
# This keeps uploaded files co-located with the service code and avoids
# taking a dependency on /data/ mount points.  Override with MODEL_UPLOAD_DIR
# (absolute path) when running containerised with a volume mount.
# NOTE: this directory is listed in the repo's .gitignore so uploaded model
# artefacts never end up in git.
_SERVICE_DIR          = pathlib.Path(__file__).resolve().parent
MODEL_UPLOAD_DIR      = os.getenv(
    "MODEL_UPLOAD_DIR",
    str(_SERVICE_DIR / "models"),
)
MODEL_UPLOAD_MAX_MB   = int(os.getenv("MODEL_UPLOAD_MAX_MB", "8192"))  # 8 GB default cap


# ── JWT auth ─────────────────────────────────────────────────────────────────

def _load_public_key() -> str:
    try:
        with open(JWT_PUBLIC_KEY_PATH) as f:
            return f.read().strip()
    except FileNotFoundError:
        return os.getenv("JWT_PUBLIC_KEY", "")


def verify_jwt(authorization: Optional[str] = Header(None)) -> Dict:
    """Verify RS256 JWT and return claims. Raises 401 on failure."""
    import jwt as pyjwt
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1]
    pub_key = _load_public_key()
    if not pub_key:
        raise HTTPException(status_code=500, detail="JWT public key not configured")
    try:
        return pyjwt.decode(token, pub_key, algorithms=["RS256"],
                            options={"verify_aud": False})
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except pyjwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


def require_admin(claims: Dict = Depends(verify_jwt)) -> Dict:
    if "spm:admin" not in claims.get("roles", []):
        raise HTTPException(status_code=403, detail="spm:admin role required")
    return claims


def require_auditor(claims: Dict = Depends(verify_jwt)) -> Dict:
    roles = claims.get("roles", [])
    if "spm:admin" not in roles and "spm:auditor" not in roles:
        raise HTTPException(status_code=403, detail="spm:auditor or spm:admin role required")
    return claims


def _tenant_from_claims(claims: Dict, fallback: str = "global") -> str:
    """
    Resolve tenant_id from JWT claims.  System is single-tenant today, but we
    honour whatever the token carries so an org-aware token doesn't silently
    land rows in the wrong tenant.  Falls back to `fallback` when nothing is
    present.
    """
    return (
        claims.get("tenant_id")
        or claims.get("tenant")
        or claims.get("org_id")
        or fallback
    )


# Risk tier thresholds keyed off alerts_count.  Matches the ladder the user
# defined for the Inventory UI: 0=Low, 1–2=Medium, 3–5=High, 6+=Critical.
def _risk_tier_from_alerts(alerts: int) -> ModelRiskTier:
    if alerts <= 0:
        return ModelRiskTier.low
    if alerts <= 2:
        return ModelRiskTier.medium
    if alerts <= 5:
        return ModelRiskTier.high
    return ModelRiskTier.critical


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ModelCreate(BaseModel):
    name: str
    version: str
    provider: str = "local"
    purpose: Optional[str] = None
    risk_tier: str = "limited"
    model_type: Optional[str] = None
    # Inventory-table fields
    owner: Optional[str] = None
    policy_status: Optional[str] = None
    alerts_count: int = 0
    tenant_id: Optional[str] = None   # derived from JWT when omitted
    status: str = "registered"
    approved_by: Optional[str] = None
    notes: Optional[str] = None
    ai_sbom: Dict[str, Any] = {}


class ModelResponse(BaseModel):
    model_id: str
    name: str
    version: str
    provider: str
    purpose: Optional[str]
    risk_tier: str
    model_type: Optional[str]
    # Inventory-table fields
    owner: Optional[str]
    policy_status: Optional[str]
    alerts_count: int
    last_seen_at: Optional[str]
    tenant_id: str
    status: str
    approved_by: Optional[str]
    approved_at: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]
    notes: Optional[str] = None
    ai_sbom: Dict[str, Any] = {}

    @classmethod
    def from_orm(cls, m: ModelRegistry) -> "ModelResponse":
        # Always derive risk_tier from the current alerts_count so the UI
        # chip stays in lockstep with alert volume — the stored `risk_tier`
        # enum value is treated as a floor that operators can raise, never
        # lower, but at registration time we report the computed tier.
        computed_risk = _risk_tier_from_alerts(m.alerts_count or 0)
        return cls(
            model_id=str(m.model_id),
            name=m.name, version=m.version,
            provider=m.provider.value if m.provider else "local",
            purpose=m.purpose,
            risk_tier=computed_risk.value,
            model_type=m.model_type.value if m.model_type else None,
            owner=m.owner,
            policy_status=m.policy_status.value if m.policy_status else None,
            alerts_count=m.alerts_count or 0,
            last_seen_at=m.last_seen_at.isoformat() if m.last_seen_at else None,
            tenant_id=m.tenant_id,
            status=m.status.value if m.status else "registered",
            approved_by=m.approved_by,
            approved_at=m.approved_at.isoformat() if m.approved_at else None,
            created_at=m.created_at.isoformat() if m.created_at else None,
            updated_at=m.updated_at.isoformat() if m.updated_at else None,
            notes=getattr(m, "notes", None),
            ai_sbom=m.ai_sbom or {},
        )


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables if they don't exist (fallback if migrations weren't run)
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Seed compliance evidence from mapping file
    await seed_compliance_evidence()
    log.info("spm-api started")
    yield
    await get_engine().dispose()


app = FastAPI(title="AI SPM API", version="1.0.0", lifespan=lifespan)

# CORS — allow the admin UI (vite dev server) to call this API directly if
# needed. In production, the UI routes through a proxy and this is a no-op.
_cors_origins = os.getenv(
    "SPM_API_CORS_ORIGINS",
    "http://localhost:3001,http://127.0.0.1:3001",
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "spm-api", "ts": int(time.time())}


# ── Model Registry ─────────────────────────────────────────────────────────────

def _coerce_enum(enum_cls, value, default):
    """Return enum_cls(value), or `default` if value is None/empty/invalid."""
    if value is None or value == "":
        return default
    try:
        return enum_cls(value)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {enum_cls.__name__} value: {value!r}",
        )


async def _insert_model_row(
    db: AsyncSession,
    *,
    name: str,
    version: str,
    provider: ModelProvider,
    risk_tier: ModelRiskTier,
    status_val: ModelStatus,
    model_type: Optional[ModelType],
    purpose: Optional[str],
    owner: Optional[str],
    policy_status: Optional[PolicyCoverage],
    alerts_count: int,
    tenant_id: str,
    approved_by: Optional[str],
    notes: Optional[str],
    ai_sbom: Dict[str, Any],
) -> ModelRegistry:
    """
    Insert a new model row.  Raises HTTP 409 if (name, version, tenant_id) is
    already taken — the UI shows a "this model already exists, bump the
    version" dialog in that case.
    """
    # Explicit duplicate check first so we can return a structured 409
    # before hitting the DB-level unique constraint.
    existing = await db.execute(
        select(ModelRegistry).where(
            ModelRegistry.name == name,
            ModelRegistry.version == version,
            ModelRegistry.tenant_id == tenant_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "model_already_exists",
                "message": (
                    f"A model named {name!r} with version {version!r} is already "
                    f"registered in tenant {tenant_id!r}. Bump the version and try again."
                ),
                "name": name,
                "version": version,
                "tenant_id": tenant_id,
            },
        )

    now_ts = datetime.now(tz=timezone.utc)
    row = ModelRegistry(
        name=name, version=version, provider=provider,
        purpose=purpose, risk_tier=risk_tier, model_type=model_type,
        owner=owner, policy_status=policy_status,
        alerts_count=alerts_count or 0,
        last_seen_at=now_ts,            # registration is itself a "sighting"
        tenant_id=tenant_id, status=status_val,
        approved_by=approved_by,
        approved_at=now_ts if approved_by else None,
        ai_sbom=ai_sbom or {},
    )
    # `notes` column may not exist on older DBs that haven't run migration 005.
    if notes is not None and hasattr(ModelRegistry, "notes"):
        row.notes = notes
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        # Race: another writer inserted the same (name, version, tenant) between
        # our pre-check and commit.  Surface the same structured 409.
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "error": "model_already_exists",
                "message": (
                    f"A model named {name!r} with version {version!r} is already "
                    f"registered in tenant {tenant_id!r}. Bump the version and try again."
                ),
                "name": name,
                "version": version,
                "tenant_id": tenant_id,
            },
        )
    await db.refresh(row)
    return row


@app.post("/models", status_code=201)
async def register_model(
    body: ModelCreate,
    db: AsyncSession = Depends(get_db),
    claims: Dict = Depends(require_admin),
) -> ModelResponse:
    """Register a new model. Returns 409 on (name, version, tenant) collision."""
    tenant_id = body.tenant_id or _tenant_from_claims(claims)
    # Initial risk is derived from alerts_count; ignore anything the caller
    # sent so there's one source of truth.
    initial_risk = _risk_tier_from_alerts(body.alerts_count or 0)
    row = await _insert_model_row(
        db,
        name=body.name, version=body.version,
        provider=_coerce_enum(ModelProvider, body.provider, ModelProvider.local),
        risk_tier=initial_risk,
        status_val=_coerce_enum(ModelStatus, body.status, ModelStatus.registered),
        model_type=_coerce_enum(ModelType, body.model_type, None) if body.model_type else None,
        purpose=body.purpose,
        owner=body.owner,
        policy_status=_coerce_enum(PolicyCoverage, body.policy_status, None) if body.policy_status else None,
        alerts_count=body.alerts_count or 0,
        tenant_id=tenant_id,
        approved_by=body.approved_by,
        notes=body.notes,
        ai_sbom=body.ai_sbom,
    )
    return ModelResponse.from_orm(row)


# ── Upload endpoint (multipart: metadata + optional model artifact file) ──────

# Reasonable set of extensions for model artifacts; we don't enforce this, but
# we sanitise the filename against it so an attacker can't upload arbitrary
# executables with the same filename.
_ALLOWED_MODEL_EXTS = {
    ".safetensors", ".gguf", ".ggml", ".bin", ".onnx", ".pt", ".pth",
    ".ckpt", ".h5", ".tflite", ".pkl", ".tar", ".zip", ".npz", ".msgpack",
}


def _safe_filename(raw: str) -> str:
    """Strip any path components and normalise whitespace from an uploaded filename."""
    stem = pathlib.PurePosixPath(raw).name
    stem = stem.replace("\\", "").strip()
    # Drop characters that are never useful in a filename on common filesystems
    return "".join(c for c in stem if c.isalnum() or c in ("-", "_", ".", "+"))


async def _persist_upload(file: UploadFile) -> Dict[str, Any]:
    """
    Stream `file` to disk under MODEL_UPLOAD_DIR, enforce a size cap, and
    return a dict suitable for embedding into `ai_sbom["artifact"]`.
    """
    upload_dir = pathlib.Path(MODEL_UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)

    safe_name = _safe_filename(file.filename or "model.bin") or "model.bin"
    # Prefix with a UUID so two uploads with the same filename don't collide
    stored_name = f"{uuid.uuid4().hex}_{safe_name}"
    target = upload_dir / stored_name

    max_bytes = MODEL_UPLOAD_MAX_MB * 1024 * 1024
    hasher = hashlib.sha256()
    written = 0
    try:
        with target.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)  # 1 MiB
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    out.close()
                    target.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"Uploaded file exceeds {MODEL_UPLOAD_MAX_MB} MB limit",
                    )
                hasher.update(chunk)
                out.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        # Best-effort cleanup on any IO failure
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Failed to store upload: {e}")

    ext = pathlib.Path(safe_name).suffix.lower()
    return {
        "filename":      safe_name,
        "stored_name":   stored_name,
        "storage_path":  str(target),
        "size_bytes":    written,
        "sha256":        hasher.hexdigest(),
        "content_type":  file.content_type or "application/octet-stream",
        "extension":     ext,
        "extension_recognized": ext in _ALLOWED_MODEL_EXTS,
        "uploaded_at":   datetime.now(tz=timezone.utc).isoformat(),
    }


@app.post("/models/upload", status_code=201)
async def register_model_with_file(
    name:          str           = Form(...),
    version:       str           = Form("1.0.0"),
    provider:      str           = Form("local"),
    risk_tier:     str           = Form("limited"),  # accepted but ignored — derived from alerts
    model_type:    Optional[str] = Form(None),
    purpose:       Optional[str] = Form(None),
    owner:         Optional[str] = Form(None),
    policy_status: Optional[str] = Form(None),
    alerts_count:  int           = Form(0),
    tenant_id:     Optional[str] = Form(None),       # derived from JWT when omitted
    status:        str           = Form("registered"),
    approved_by:   Optional[str] = Form(None),
    notes:         Optional[str] = Form(None),
    linked_policies: Optional[str] = Form(None),     # JSON array of policy ids
    ai_sbom:       Optional[str] = Form(None),       # JSON string; optional extra metadata
    file:          Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    claims: Dict = Depends(require_admin),
) -> ModelResponse:
    """
    Register a model via multipart/form-data, with an optional model file.

    The file (if provided) is streamed to MODEL_UPLOAD_DIR (defaults to
    <service-dir>/models), sha256'd, and its metadata is embedded in
    the row's ai_sbom under the "artifact" key.  Returns 409 on duplicate.
    """
    effective_tenant = tenant_id or _tenant_from_claims(claims)

    # Parse optional ai_sbom JSON blob
    sbom: Dict[str, Any] = {}
    if ai_sbom:
        try:
            parsed = json.loads(ai_sbom)
            if isinstance(parsed, dict):
                sbom = parsed
            else:
                raise ValueError("ai_sbom must be a JSON object")
        except (ValueError, json.JSONDecodeError) as e:
            raise HTTPException(status_code=400, detail=f"Invalid ai_sbom JSON: {e}")

    # Parse linked_policies list (policy ids from CPM)
    if linked_policies:
        try:
            parsed_lp = json.loads(linked_policies)
            if not isinstance(parsed_lp, list):
                raise ValueError("linked_policies must be a JSON array")
            sbom["linked_policies"] = [str(p) for p in parsed_lp]
        except (ValueError, json.JSONDecodeError) as e:
            raise HTTPException(status_code=400, detail=f"Invalid linked_policies JSON: {e}")

    # Persist file first — if it fails we don't want a half-registered row
    if file is not None and file.filename:
        sbom["artifact"] = await _persist_upload(file)

    row = await _insert_model_row(
        db,
        name=name, version=version,
        provider=_coerce_enum(ModelProvider, provider, ModelProvider.local),
        risk_tier=_risk_tier_from_alerts(alerts_count or 0),
        status_val=_coerce_enum(ModelStatus, status, ModelStatus.registered),
        model_type=_coerce_enum(ModelType, model_type, None) if model_type else None,
        purpose=purpose,
        owner=owner,
        policy_status=_coerce_enum(PolicyCoverage, policy_status, None) if policy_status else None,
        alerts_count=alerts_count or 0,
        tenant_id=effective_tenant,
        approved_by=approved_by,
        notes=notes,
        ai_sbom=sbom,
    )
    return ModelResponse.from_orm(row)


@app.get("/models")
async def list_models(
    tenant_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _claims: Dict = Depends(verify_jwt),
) -> List[ModelResponse]:
    stmt = select(ModelRegistry)
    if tenant_id:
        stmt = stmt.where(ModelRegistry.tenant_id == tenant_id)
    result = await db.execute(stmt)
    return [ModelResponse.from_orm(m) for m in result.scalars().all()]


@app.get("/models/{model_id}")
async def get_model(
    model_id: str,
    db: AsyncSession = Depends(get_db),
    _claims: Dict = Depends(verify_jwt),
) -> ModelResponse:
    result = await db.get(ModelRegistry, uuid.UUID(model_id))
    if not result:
        raise HTTPException(status_code=404, detail="Model not found")
    return ModelResponse.from_orm(result)


class StatusTransition(BaseModel):
    new_status: str
    approved_by: Optional[str] = None


@app.patch("/models/{model_id}/status")
async def transition_status(
    model_id: str,
    body: StatusTransition,
    db: AsyncSession = Depends(get_db),
    claims: Dict = Depends(require_admin),
) -> ModelResponse:
    """Transition model lifecycle status. Validates state machine."""
    model = await db.get(ModelRegistry, uuid.UUID(model_id))
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    new_status = ModelStatus(body.new_status)
    if not model.can_transition_to(new_status):
        raise HTTPException(
            status_code=409,
            detail=f"Invalid transition: {model.status.value} → {new_status.value}",
        )

    model.status = new_status
    if new_status == ModelStatus.approved:
        model.approved_by = body.approved_by or claims.get("sub")
        model.approved_at = datetime.now(tz=timezone.utc)

    await db.commit()
    await db.refresh(model)

    # Sync to OPA if retiring or deprecating
    if new_status in (ModelStatus.retired, ModelStatus.deprecated):
        await _push_blocked_models_to_opa(db)
    if new_status == ModelStatus.retired:
        await _call_freeze_controller(str(model.model_id), model.tenant_id)
        await _publish_model_event("model_blocked", str(model.model_id), model.tenant_id)

    return ModelResponse.from_orm(model)


# ── Internal: Enforcement ─────────────────────────────────────────────────────

@app.post("/internal/enforce/{model_id}", include_in_schema=False)
async def enforce_model(
    model_id: str,
    db: AsyncSession = Depends(get_db),
) -> Dict:
    """Called by spm-aggregator when risk threshold is exceeded. Idempotent."""
    model = await db.get(ModelRegistry, uuid.UUID(model_id))
    if not model:
        log.warning("Enforcement for unknown model_id=%s — skipping", model_id)
        return {"status": "skipped", "reason": "model_not_in_registry"}

    if model.status == ModelStatus.retired:
        return {"status": "already_enforced"}

    model.status = ModelStatus.retired
    model.approved_by = "spm-enforcement"
    await db.commit()

    await _push_blocked_models_to_opa(db)
    await _call_freeze_controller(model_id, model.tenant_id)
    await _publish_model_event("model_blocked", model_id, model.tenant_id)

    return {"status": "enforced", "model_id": model_id}


async def _push_blocked_models_to_opa(db: AsyncSession) -> None:
    """Push blocked_models (retired) and deprecated_models sets to OPA."""
    retired_result = await db.execute(
        select(ModelRegistry.model_id).where(ModelRegistry.status == ModelStatus.retired)
    )
    blocked = [str(r) for r in retired_result.scalars().all()]

    deprecated_result = await db.execute(
        select(ModelRegistry.model_id).where(ModelRegistry.status == ModelStatus.deprecated)
    )
    deprecated = [str(r) for r in deprecated_result.scalars().all()]

    for path, data in [("/v1/data/blocked_models", blocked),
                       ("/v1/data/deprecated_models", deprecated)]:
        try:
            resp = requests.put(f"{OPA_URL}{path}", json=data, timeout=5.0)
            if resp.status_code not in (200, 204):
                log.warning("OPA push to %s returned %d", path, resp.status_code)
        except Exception as e:
            log.error("OPA push to %s failed: %s", path, e)


async def _call_freeze_controller(model_id: str, tenant_id: str) -> None:
    """Call Freeze Controller to freeze access for this model's tenant."""
    try:
        resp = requests.post(
            f"{FREEZE_CONTROLLER_URL}/freeze",
            json={
                "scope": "tenant", "tenant_id": tenant_id,
                "actor": "spm-enforcement",
                "reason": "model_risk_threshold_exceeded",
                "model_id": model_id,
            },
            headers={"Authorization": f"Bearer {SPM_SERVICE_JWT}"},
            timeout=10.0,
        )
        if resp.status_code not in (200, 201, 409):
            log.warning("Freeze Controller returned %d", resp.status_code)
    except Exception as e:
        log.error("Freeze Controller call failed: %s", e)


async def _publish_model_event(event: str, model_id: str, tenant_id: str) -> None:
    """Publish to cpm.global.model_events Kafka topic."""
    try:
        from kafka import KafkaProducer
        from platform_shared.topics import GlobalTopics
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            value_serializer=lambda v: json.dumps(v).encode(),
        )
        producer.send(GlobalTopics().MODEL_EVENTS, {
            "event": event, "model_id": model_id,
            "tenant_id": tenant_id,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        })
        producer.flush()
        producer.close()
    except Exception as e:
        log.error("Failed to publish model event: %s", e)


# ── JWKS endpoint for Grafana ─────────────────────────────────────────────────

@app.get("/jwks")
async def jwks():
    """Return RS256 public key in JWKS format for Grafana JWT auth."""
    import base64
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    pub_key_pem = _load_public_key()
    if not pub_key_pem:
        raise HTTPException(status_code=503, detail="Public key not available")
    try:
        pub = load_pem_public_key(pub_key_pem.encode())
        pub_numbers = pub.public_numbers()
        def to_b64url(n: int) -> str:
            length = (n.bit_length() + 7) // 8
            return base64.urlsafe_b64encode(n.to_bytes(length, "big")).rstrip(b"=").decode()
        return {
            "keys": [{
                "kty": "RSA", "use": "sig", "alg": "RS256", "kid": "cpm-key-1",
                "n": to_b64url(pub_numbers.n),
                "e": to_b64url(pub_numbers.e),
            }]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"JWKS generation failed: {e}")


# ── Compliance ─────────────────────────────────────────────────────────────────

async def seed_compliance_evidence():
    """Seed compliance_evidence from nist_airm_mapping.json if table is empty."""
    mapping_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "spm", "compliance", "nist_airm_mapping.json")
    if not os.path.exists(mapping_path):
        log.warning("NIST AI RMF mapping file not found at %s", mapping_path)
        return
    with open(mapping_path) as f:
        controls = json.load(f)
    from spm.db.session import get_session_factory
    factory = get_session_factory()
    async with factory() as db:
        result = await db.execute(select(ComplianceEvidence).limit(1))
        if result.scalar_one_or_none():
            return  # already seeded
        for c in controls:
            db.add(ComplianceEvidence(
                framework=c["framework"], function=c["function"],
                category=c["category"], subcategory=c.get("subcategory"),
                cpm_control=c["cpm_control"], status="not_satisfied",
            ))
        await db.commit()
    log.info("Seeded %d compliance controls", len(controls))


@app.get("/compliance/nist-airm/report")
async def compliance_report(
    format: str = "json",
    db: AsyncSession = Depends(get_db),
    _claims: Dict = Depends(require_auditor),
):
    """Generate NIST AI RMF compliance report."""
    from spm.compliance.evaluator import evaluate_all_controls
    await evaluate_all_controls(db)

    result = await db.execute(select(ComplianceEvidence))
    controls = result.scalars().all()

    functions: Dict[str, Dict] = {}
    for c in controls:
        fn = c.function
        if fn not in functions:
            functions[fn] = {"function": fn, "controls": [], "gaps": [],
                             "satisfied": 0, "total": 0}
        functions[fn]["total"] += 1
        if c.status and c.status.value == "satisfied":
            functions[fn]["satisfied"] += 1
        else:
            functions[fn]["gaps"].append({
                "category": c.category, "control": c.cpm_control,
                "status": c.status.value if c.status else "not_satisfied",
            })
        functions[fn]["controls"].append({
            "category": c.category, "cpm_control": c.cpm_control,
            "status": c.status.value if c.status else "not_satisfied",
        })

    total_satisfied = sum(f["satisfied"] for f in functions.values())
    total_controls  = sum(f["total"] for f in functions.values())
    coverage = round(total_satisfied / total_controls * 100, 1) if total_controls else 0

    for fn in functions.values():
        fn["coverage_pct"] = round(fn["satisfied"] / fn["total"] * 100, 1) if fn["total"] else 0

    report = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "framework": "NIST_AI_RMF",
        "overall_coverage_pct": coverage,
        "functions": list(functions.values()),
    }

    if format == "pdf":
        from spm.compliance.evaluator import render_pdf
        pdf_bytes = render_pdf(report)
        return Response(content=pdf_bytes, media_type="application/pdf",
                        headers={"Content-Disposition": "attachment; filename=nist-airm-report.pdf"})

    return JSONResponse(report)


# ── AI-SBOM ────────────────────────────────────────────────────────────────────

CPM_INVENTORY_ENDPOINTS = [
    os.getenv("CPM_API_URL", "http://api:8080") + "/inventory",
    os.getenv("GUARD_MODEL_URL", "http://guard-model:8200") + "/inventory",
    os.getenv("FREEZE_CONTROLLER_URL", "http://freeze-controller:8090") + "/inventory",
    os.getenv("POLICY_SIMULATOR_URL", "http://policy-simulator:8091") + "/inventory",
]


@app.get("/sbom/refresh")
async def refresh_sbom(
    db: AsyncSession = Depends(get_db),
    _claims: Dict = Depends(require_admin),
) -> Dict:
    """Aggregate AI-SBOM from all CPM service /inventory endpoints."""
    components = []
    unavailable = []
    async with httpx.AsyncClient(timeout=5.0) as client:
        for endpoint in CPM_INVENTORY_ENDPOINTS:
            try:
                resp = await client.get(endpoint)
                if resp.status_code == 200:
                    components.append(resp.json())
                else:
                    unavailable.append({"endpoint": endpoint, "status": resp.status_code})
            except Exception as e:
                unavailable.append({"endpoint": endpoint, "error": str(e)})

    sbom = {
        "schema_version": "1.0",
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "components": components,
        "unavailable_services": unavailable,
    }
    return sbom


# ── Prometheus metrics ─────────────────────────────────────────────────────────

from prometheus_fastapi_instrumentator import Instrumentator  # noqa: E402
Instrumentator().instrument(app).expose(app)


# ── Integrations module ───────────────────────────────────────────────────────
# Routes live in a sibling module because the 15+ endpoints + 8-table
# serialization surface would bloat this file.  See integrations_routes.py.
# The Dockerfile flattens the service dir onto /app/, so the sibling is
# importable by its bare name at runtime.  When running tests from the repo
# root we fall through to the packaged path under services/spm_api/.
try:
    from integrations_routes import router as integrations_router  # type: ignore  # noqa: E402
except ModuleNotFoundError:
    from services.spm_api.integrations_routes import router as integrations_router  # noqa: E402
app.include_router(integrations_router)
