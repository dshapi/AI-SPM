from __future__ import annotations
import logging
from uuid import uuid4

from cases.schemas import CaseRecord
from models.cases import CaseRepository
from threat_findings.schemas import CreateFindingRequest, FindingRecord
from threat_findings.models import ThreatFindingRepository

logger = logging.getLogger(__name__)

# Severity → (risk_score, decision)
_SEVERITY_MAP = {
    "low":      (0.25, "allow"),
    "medium":   (0.55, "escalate"),
    "high":     (0.80, "escalate"),
    "critical": (0.95, "block"),
}


class ThreatFindingsService:
    """Stateless — one shared instance on app.state."""

    async def create_finding(
        self,
        req: CreateFindingRequest,
        repo: ThreatFindingRepository,
        case_repo: CaseRepository,
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

        # Open a case so the notification bell rings
        risk_score, decision = _SEVERITY_MAP.get(req.severity, (0.5, "escalate"))
        ttps_str = ", ".join(req.ttps) if req.ttps else "none"
        case = CaseRecord(
            case_id=str(uuid4()),
            session_id=f"threat-hunt:{rec.id}",   # synthetic; agent hunts have no real session
            reason=f"threat-hunt · {req.severity.upper()} · TTPs: {ttps_str}",
            summary=f"[{req.severity.upper()}] {req.title} — {req.description}",
            risk_score=risk_score,
            decision=decision,
        )
        await case_repo.insert(case)
        logger.info(
            "Opened case case_id=%s for finding id=%s",
            case.case_id, rec.id,
        )

        return rec
