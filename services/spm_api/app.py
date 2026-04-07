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

import httpx
import requests
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from spm.db.models import (
    ComplianceEvidence, ModelRegistry,
    ModelStatus, ModelProvider, ModelRiskTier,
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


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ModelCreate(BaseModel):
    name: str
    version: str
    provider: str = "local"
    purpose: Optional[str] = None
    risk_tier: str = "limited"
    tenant_id: str = "global"
    status: str = "registered"
    approved_by: Optional[str] = None
    ai_sbom: Dict[str, Any] = {}


class ModelResponse(BaseModel):
    model_id: str
    name: str
    version: str
    provider: str
    purpose: Optional[str]
    risk_tier: str
    tenant_id: str
    status: str
    approved_by: Optional[str]
    approved_at: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]

    @classmethod
    def from_orm(cls, m: ModelRegistry) -> "ModelResponse":
        return cls(
            model_id=str(m.model_id),
            name=m.name, version=m.version,
            provider=m.provider.value if m.provider else "local",
            purpose=m.purpose,
            risk_tier=m.risk_tier.value if m.risk_tier else "limited",
            tenant_id=m.tenant_id,
            status=m.status.value if m.status else "registered",
            approved_by=m.approved_by,
            approved_at=m.approved_at.isoformat() if m.approved_at else None,
            created_at=m.created_at.isoformat() if m.created_at else None,
            updated_at=m.updated_at.isoformat() if m.updated_at else None,
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


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "spm-api", "ts": int(time.time())}


# ── Model Registry ─────────────────────────────────────────────────────────────

@app.post("/models", status_code=201)
async def register_model(
    body: ModelCreate,
    db: AsyncSession = Depends(get_db),
    _claims: Dict = Depends(verify_jwt),
) -> ModelResponse:
    """Register a model (upsert on name+version+tenant_id)."""
    status_val   = ModelStatus(body.status) if body.status else ModelStatus.registered
    provider_val = ModelProvider(body.provider) if body.provider else ModelProvider.local
    risk_val     = ModelRiskTier(body.risk_tier) if body.risk_tier else ModelRiskTier.limited

    stmt = pg_insert(ModelRegistry).values(
        name=body.name, version=body.version, provider=provider_val,
        purpose=body.purpose, risk_tier=risk_val, tenant_id=body.tenant_id,
        status=status_val, approved_by=body.approved_by,
        approved_at=datetime.now(tz=timezone.utc) if body.approved_by else None,
        ai_sbom=body.ai_sbom,
    ).on_conflict_do_update(
        constraint="uq_model_name_version_tenant",
        set_={"updated_at": datetime.now(tz=timezone.utc)},
    ).returning(ModelRegistry)

    result = await db.execute(stmt)
    await db.commit()
    row = result.scalar_one()
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
