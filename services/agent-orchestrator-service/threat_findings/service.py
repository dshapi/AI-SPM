from __future__ import annotations
import logging
from uuid import uuid4
from threat_findings.schemas import CreateFindingRequest, FindingRecord
from threat_findings.models import ThreatFindingRepository

logger = logging.getLogger(__name__)


class ThreatFindingsService:
    """Stateless — one shared instance on app.state."""

    async def create_finding(
        self,
        req: CreateFindingRequest,
        repo: ThreatFindingRepository,
    ) -> FindingRecord:
        existing = await repo.get_by_batch_hash(req.batch_hash)
        if existing:
            logger.info("Deduplicated finding batch_hash=%s", req.batch_hash)
            existing.deduplicated = True
            return existing

        rec = FindingRecord(
            id=str(uuid4()),
            batch_hash=req.batch_hash,
            title=req.title,
            severity=req.severity,
            description=req.description,
            evidence=req.evidence,
            ttps=req.ttps,
            tenant_id=req.tenant_id,
        )
        await repo.insert(rec)
        logger.info(
            "Created finding id=%s tenant=%s severity=%s",
            rec.id, rec.tenant_id, rec.severity,
        )
        return rec
