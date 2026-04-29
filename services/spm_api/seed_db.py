#!/usr/bin/env python3
"""
seed_db.py — standalone DB seed script for the spm-api container.

Seeds:
  • ModelRegistry   — 12 diverse demo models (varied providers, risk tiers, statuses, types)
  • PostureSnapshot  — 30 days of daily snapshots for the platform

Idempotent: skips rows that already exist.

Run from the spm-api container (compose or k8s):
    python3 /app/seed_db.py

Or via kubectl:
    kubectl -n aispm exec <spm-api-pod> -- python3 /app/seed_db.py

Exits 0 on success, 1 on failure.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

# Allow running from /app (k8s image) or from repo root (dev)
_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _here)
sys.path.insert(0, os.path.join(_here, ".."))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [seed_db] %(levelname)s — %(message)s",
)
log = logging.getLogger("seed_db")

_NOW = datetime.now(timezone.utc)


def _ago(**kw) -> datetime:
    return _NOW - timedelta(**kw)


# ── Demo model registry data ──────────────────────────────────────────────────
# Single-tenant product — tenant_id "global" for platform-owned models.
# Covers: 4 providers × 3 risk tiers × 5 statuses × 6 model types.

DEMO_MODELS = [
    # ── Anthropic / production-approved ──────────────────────────────────────
    {
        "name": "claude-3-5-sonnet",
        "version": "20241022",
        "provider": "anthropic",
        "purpose": "Primary LLM for customer-facing agents. Instruction-following, tool use, long context.",
        "risk_tier": "high",
        "model_type": "llm",
        "owner": "platform-eng",
        "policy_status": "full",
        "alerts_count": 2,
        "status": "approved",
        "approved_by": "security-ops",
        "approved_at": _ago(days=14),
        "last_seen_at": _ago(minutes=5),
        "notes": "Primary production LLM. PII-Guard and Prompt-Guard policies enforced on all sessions.",
    },
    {
        "name": "claude-3-haiku",
        "version": "20240307",
        "provider": "anthropic",
        "purpose": "Low-latency routing and triage tasks. Not used for customer data.",
        "risk_tier": "limited",
        "model_type": "llm",
        "owner": "platform-eng",
        "policy_status": "partial",
        "alerts_count": 0,
        "status": "approved",
        "approved_by": "platform-eng",
        "approved_at": _ago(days=30),
        "last_seen_at": _ago(minutes=12),
        "notes": "Used for routing only. Does not receive user PII.",
    },
    # ── OpenAI / approved ────────────────────────────────────────────────────
    {
        "name": "gpt-4o",
        "version": "2024-11-20",
        "provider": "openai",
        "purpose": "Fallback LLM for complex multi-step reasoning tasks.",
        "risk_tier": "high",
        "model_type": "llm",
        "owner": "ml-team",
        "policy_status": "full",
        "alerts_count": 1,
        "status": "approved",
        "approved_by": "security-ops",
        "approved_at": _ago(days=21),
        "last_seen_at": _ago(hours=2),
        "notes": "Fallback model. Output-Filter v2 applied. Token budget capped at 4096 per session.",
    },
    {
        "name": "text-embedding-3-large",
        "version": "1",
        "provider": "openai",
        "purpose": "RAG pipeline embeddings — knowledge base and customer doc retrieval.",
        "risk_tier": "minimal",
        "model_type": "embedding_model",
        "owner": "ml-team",
        "policy_status": "full",
        "alerts_count": 0,
        "status": "approved",
        "approved_by": "ml-team",
        "approved_at": _ago(days=45),
        "last_seen_at": _ago(minutes=3),
        "notes": "Embedding model only — no generation capability. Low risk.",
    },
    {
        "name": "gpt-4o-mini",
        "version": "2024-07-18",
        "provider": "openai",
        "purpose": "Cost-optimised summarisation and classification tasks.",
        "risk_tier": "limited",
        "model_type": "llm",
        "owner": "ml-team",
        "policy_status": "partial",
        "alerts_count": 3,
        "status": "under_review",
        "approved_by": None,
        "approved_at": None,
        "last_seen_at": _ago(hours=6),
        "notes": "Under review — elevated alert count from summarisation tasks returning PII fragments.",
    },
    # ── Internal / local models ──────────────────────────────────────────────
    {
        "name": "llama-guard-3",
        "version": "3.0.0",
        "provider": "local",
        "purpose": "Content screening — prompt and output safety classification.",
        "risk_tier": "limited",
        "model_type": "llm",
        "owner": "security-ops",
        "policy_status": "full",
        "alerts_count": 0,
        "status": "approved",
        "approved_by": "startup-orchestrator",
        "approved_at": _ago(days=60),
        "last_seen_at": _ago(minutes=1),
        "notes": "Platform safety model. Always-on. Not exposed to external users.",
    },
    {
        "name": "output-guard-llm",
        "version": "2.1.0",
        "provider": "local",
        "purpose": "Output screening — PII redaction, secret detection, response validation.",
        "risk_tier": "limited",
        "model_type": "llm",
        "owner": "security-ops",
        "policy_status": "full",
        "alerts_count": 0,
        "status": "approved",
        "approved_by": "startup-orchestrator",
        "approved_at": _ago(days=60),
        "last_seen_at": _ago(minutes=1),
        "notes": "Inline output guard. Blocks delivery on credential pattern match.",
    },
    {
        "name": "all-MiniLM-L6-v2",
        "version": "1.0.0",
        "provider": "internal",
        "purpose": "Semantic similarity for deduplication and intent-drift detection.",
        "risk_tier": "minimal",
        "model_type": "embedding_model",
        "owner": "ml-team",
        "policy_status": "full",
        "alerts_count": 0,
        "status": "approved",
        "approved_by": "ml-team",
        "approved_at": _ago(days=90),
        "last_seen_at": _ago(hours=1),
        "notes": "Sentence-transformer. No generation. Purely internal signal pipeline.",
    },
    # ── AWS / Azure cloud provider models ────────────────────────────────────
    {
        "name": "amazon-titan-text-premier",
        "version": "v1:0",
        "provider": "aws",
        "purpose": "Data pipeline summarisation — used by DataPipeline-Orchestrator agent.",
        "risk_tier": "high",
        "model_type": "llm",
        "owner": "data-eng",
        "policy_status": "partial",
        "alerts_count": 5,
        "status": "under_review",
        "approved_by": None,
        "approved_at": None,
        "last_seen_at": _ago(hours=3),
        "notes": "Under review after anomalous bulk retrieval finding (find-002). Access frozen for DataPipeline-Orchestrator pending investigation.",
    },
    {
        "name": "azure-openai-gpt-4-turbo",
        "version": "2024-04-09",
        "provider": "azure",
        "purpose": "EU-region LLM for GDPR-scoped workloads (data residency compliance).",
        "risk_tier": "high",
        "model_type": "llm",
        "owner": "compliance-team",
        "policy_status": "full",
        "alerts_count": 0,
        "status": "approved",
        "approved_by": "security-ops",
        "approved_at": _ago(days=7),
        "last_seen_at": _ago(hours=8),
        "notes": "EU data residency — used for all EU-subject data processing. PII-Mask enforced.",
    },
    # ── Deprecated / retired — lifecycle diversity ────────────────────────────
    {
        "name": "gpt-3.5-turbo",
        "version": "0125",
        "provider": "openai",
        "purpose": "Legacy agent host — replaced by claude-3-haiku in Q1 2026.",
        "risk_tier": "limited",
        "model_type": "llm",
        "owner": "ml-team",
        "policy_status": "none",
        "alerts_count": 0,
        "status": "deprecated",
        "approved_by": "ml-team",
        "approved_at": _ago(days=120),
        "last_seen_at": _ago(days=35),
        "notes": "Deprecated Q1 2026. All agents migrated to claude-3-haiku. No active sessions.",
    },
    {
        "name": "whisper-large-v3",
        "version": "3.0.0",
        "provider": "internal",
        "purpose": "Voice-to-text transcription for audio-input agent workflows.",
        "risk_tier": "minimal",
        "model_type": "audio_model",
        "owner": "ml-team",
        "policy_status": "partial",
        "alerts_count": 0,
        "status": "registered",
        "approved_by": None,
        "approved_at": None,
        "last_seen_at": _ago(days=2),
        "notes": "Newly onboarded. Risk assessment in progress. Not yet approved for production use.",
    },
]


# ── Demo posture snapshots ────────────────────────────────────────────────────
# 30 daily snapshots for the platform (model_id=None = platform-wide aggregate).
# Simulates realistic trend: improving posture over the last month.

def _build_posture_snapshots() -> list[dict]:
    """Generate 30 days of daily platform-wide posture snapshots."""
    rows = []
    for days_ago in range(30, 0, -1):
        snap_at = _ago(days=days_ago).replace(hour=0, minute=0, second=0, microsecond=0)
        # Trend: risk was higher 30d ago, improving toward present
        trend = days_ago / 30.0          # 1.0 at start, ~0.03 at end
        base_requests = 180 + int(days_ago * 3)   # traffic increasing toward present
        avg_risk = round(0.28 + trend * 0.22, 3)  # 0.50 → 0.28
        max_risk = round(min(0.97, avg_risk + 0.35 + (trend * 0.1)), 3)
        rows.append({
            "model_id": None,
            "tenant_id": "global",
            "snapshot_at": snap_at,
            "request_count": base_requests,
            "block_count": max(0, int(base_requests * 0.03 * trend + 1)),
            "escalation_count": max(0, int(base_requests * 0.01 * trend)),
            "avg_risk_score": avg_risk,
            "max_risk_score": max_risk,
            "intent_drift_avg": round(0.05 + trend * 0.12, 3),
            "ttp_hit_count": max(0, int(3 * trend + 0.5)),
        })
    return rows


async def seed_models(db) -> int:
    """Seed ModelRegistry. Returns count of newly inserted rows."""
    from sqlalchemy import select
    from spm.db.models import ModelRegistry, ModelProvider, ModelRiskTier, ModelStatus, ModelType, PolicyCoverage

    _provider_map = {
        "anthropic": ModelProvider.anthropic,
        "openai":    ModelProvider.openai,
        "local":     ModelProvider.local,
        "internal":  ModelProvider.internal,
        "aws":       ModelProvider.aws,
        "azure":     ModelProvider.azure,
        "gcp":       ModelProvider.gcp,
    }
    _tier_map = {
        "minimal":      ModelRiskTier.minimal,
        "limited":      ModelRiskTier.limited,
        "high":         ModelRiskTier.high,
        "unacceptable": ModelRiskTier.unacceptable,
        "low":          ModelRiskTier.low,
        "medium":       ModelRiskTier.medium,
        "critical":     ModelRiskTier.critical,
    }
    _status_map = {
        "registered":   ModelStatus.registered,
        "under_review": ModelStatus.under_review,
        "approved":     ModelStatus.approved,
        "deprecated":   ModelStatus.deprecated,
        "retired":      ModelStatus.retired,
    }
    _type_map = {
        "llm":             ModelType.llm,
        "embedding_model": ModelType.embedding_model,
        "audio_model":     ModelType.audio_model,
        "vision_model":    ModelType.vision_model,
        "multimodal":      ModelType.multimodal,
        "other":           ModelType.other,
    }
    _policy_map = {
        "full":    PolicyCoverage.full,
        "partial": PolicyCoverage.partial,
        "none":    PolicyCoverage.none,
    }

    inserted = 0
    for m in DEMO_MODELS:
        # Idempotency: skip if name+version already exists (unique constraint)
        result = await db.execute(
            select(ModelRegistry).where(
                ModelRegistry.name == m["name"],
                ModelRegistry.version == m["version"],
            )
        )
        if result.scalar_one_or_none() is not None:
            log.info("  model already exists: %s %s — skipping", m["name"], m["version"])
            continue

        row = ModelRegistry(
            model_id=uuid.uuid4(),
            name=m["name"],
            version=m["version"],
            provider=_provider_map.get(m["provider"], ModelProvider.other),
            purpose=m.get("purpose"),
            risk_tier=_tier_map.get(m["risk_tier"], ModelRiskTier.limited),
            model_type=_type_map.get(m.get("model_type"), ModelType.llm),
            owner=m.get("owner"),
            policy_status=_policy_map.get(m.get("policy_status"), PolicyCoverage.none),
            alerts_count=m.get("alerts_count", 0),
            last_seen_at=m.get("last_seen_at"),
            tenant_id="global",
            status=_status_map.get(m["status"], ModelStatus.registered),
            approved_by=m.get("approved_by"),
            approved_at=m.get("approved_at"),
            notes=m.get("notes"),
        )
        db.add(row)
        inserted += 1
        log.info("  + model: %s %s (%s / %s)", m["name"], m["version"], m["provider"], m["status"])

    await db.commit()
    log.info("models: %d inserted, %d already existed", inserted, len(DEMO_MODELS) - inserted)
    return inserted


async def seed_posture_snapshots(db) -> int:
    """Seed 30 days of daily posture snapshots. Returns count inserted."""
    from sqlalchemy import select, func
    from spm.db.models import PostureSnapshot

    # Idempotency: skip if we already have ≥20 global snapshots
    result = await db.execute(
        select(func.count()).select_from(PostureSnapshot).where(
            PostureSnapshot.tenant_id == "global",
            PostureSnapshot.model_id.is_(None),
        )
    )
    existing = result.scalar() or 0
    if existing >= 20:
        log.info("posture_snapshots: %d rows already present — skipping", existing)
        return 0

    rows = _build_posture_snapshots()
    for r in rows:
        db.add(PostureSnapshot(**r))
    await db.commit()
    log.info("posture_snapshots: inserted %d daily snapshots (30 days)", len(rows))
    return len(rows)


async def ensure_schema() -> None:
    """Create all tables defined on `spm.db.models.Base` if they don't exist.

    The platform expects spm-api's lifespan to do `Base.metadata.create_all`
    on first boot, but several services (api, agent-orchestrator, garak,
    threat-hunting-agent, guard_model) call `hydrate_env_from_db()` at
    module-import time and SELECT FROM `integrations` before spm-api has
    ever started. In phased k8s rollouts that ordering breaks: db-seed
    runs in `data-init`, those services start in `platform`, and spm-api's
    lifespan only runs once spm-api itself is scheduled — which is too late.
    Creating the schema here ensures every dependent service can import.
    """
    from spm.db.session import get_engine
    from spm.db.models import Base

    log.info("── ensure_schema: creating tables (idempotent) ──")
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, checkfirst=True)
    log.info("✓ schema ready")


async def main() -> int:
    try:
        from spm.db.session import get_session_factory
    except ModuleNotFoundError:
        # Fallback: build a session factory directly from SPM_DB_URL
        import os
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
        db_url = os.getenv("SPM_DB_URL", "postgresql+asyncpg://spm_rw:spmpass@spm-db:5432/spm")
        # Swap sync driver prefix if present
        if db_url.startswith("postgresql://"):
            db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        engine = create_async_engine(db_url, echo=False)
        _factory = async_sessionmaker(engine, expire_on_commit=False)

        class _CtxMgr:
            async def __aenter__(self):
                self._sess = _factory()
                return await self._sess.__aenter__()
            async def __aexit__(self, *a):
                return await self._sess.__aexit__(*a)

        def get_session_factory():
            return _factory

    log.info("═══ spm-api DB seed ═══")
    errors = 0

    # Create the schema FIRST so platform-tier services that hydrate_env_from_db()
    # at import time find the `integrations` table they expect.
    try:
        await ensure_schema()
    except Exception as e:
        log.error("✗ ensure_schema failed: %s", e, exc_info=True)
        return 1

    factory = get_session_factory()
    async with factory() as db:
        try:
            n = await seed_models(db)
            log.info("✓ ModelRegistry: seeded %d models", n)
        except Exception as e:
            log.error("✗ seed_models failed: %s", e, exc_info=True)
            errors += 1

    async with factory() as db:
        try:
            n = await seed_posture_snapshots(db)
            log.info("✓ PostureSnapshot: seeded %d snapshots", n)
        except Exception as e:
            log.error("✗ seed_posture_snapshots failed: %s", e, exc_info=True)
            errors += 1

    if errors:
        log.error("✗ seed_db completed with %d error(s)", errors)
        return 1

    log.info("✓ Database seeded successfully")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
