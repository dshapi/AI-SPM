from __future__ import annotations
import json
import logging
import hashlib
from datetime import datetime, timezone
from uuid import uuid4
from typing import Optional, List

from cases.schemas import CaseRecord
from models.cases import CaseRepository
from threat_findings.schemas import CreateFindingRequest, FindingRecord, FindingFilter
from threat_findings.models import ThreatFindingRepository

logger = logging.getLogger(__name__)


def _finding_batch_hash(tenant_id: str, title: str, evidence: list) -> str:
    """Compute batch hash from tenant_id, title, and evidence."""
    canonical = json.dumps(
        {"tenant_id": tenant_id, "title": title, "evidence": evidence},
        sort_keys=True, default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


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
            reason=f"threat-hunt · {req.severity.upper()} · {req.title} · TTPs: {ttps_str}",
            summary=f"Threat finding raised by the Threat-hunter agent — {req.description}",
            risk_score=risk_score,
            decision=decision,
        )
        await case_repo.insert(case)
        logger.info(
            "Opened case case_id=%s for finding id=%s",
            case.case_id, rec.id,
        )

        return rec

    async def persist_finding_from_dict(
        self,
        finding_dict: dict,
        tenant_id: str,
        repo: ThreatFindingRepository,
    ) -> FindingRecord:
        """
        Persist a Finding dict (from run_hunt) without auto-opening a Case.
        Deduplicates by batch_hash. Returns the FindingRecord (new or existing).
        """
        title = finding_dict.get("title", "")
        evidence = finding_dict.get("evidence", [])
        batch_hash = _finding_batch_hash(tenant_id, title, evidence)

        existing = await repo.get_by_batch_hash(batch_hash)
        if existing:
            logger.info("Deduplicated finding batch_hash=%s", batch_hash)
            existing.deduplicated = True
            return existing

        rec = FindingRecord(
            id=finding_dict.get("finding_id", str(uuid4())),
            batch_hash=batch_hash,
            title=title,
            severity=finding_dict.get("severity", "low"),
            description=finding_dict.get("hypothesis", ""),
            evidence=evidence,
            ttps=finding_dict.get("triggered_policies", []),
            tenant_id=tenant_id,
            status="open",
            timestamp=finding_dict.get("timestamp"),
            confidence=finding_dict.get("confidence"),
            risk_score=finding_dict.get("risk_score"),
            hypothesis=finding_dict.get("hypothesis"),
            asset=finding_dict.get("asset"),
            environment=finding_dict.get("environment"),
            correlated_events=finding_dict.get("correlated_events"),
            correlated_findings=finding_dict.get("correlated_findings"),
            triggered_policies=finding_dict.get("triggered_policies"),
            policy_signals=finding_dict.get("policy_signals"),
            recommended_actions=finding_dict.get("recommended_actions"),
            should_open_case=bool(finding_dict.get("should_open_case", False)),
            source="threat-hunting-agent",
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        await repo.insert(rec)
        logger.info(
            "Persisted finding id=%s tenant=%s severity=%s should_open_case=%s",
            rec.id, rec.tenant_id, rec.severity, rec.should_open_case,
        )
        return rec

    async def link_case(
        self,
        finding_id: str,
        case_id: str,
        repo: ThreatFindingRepository,
    ) -> None:
        """Associate an existing Case with a Finding."""
        await repo.attach_case(finding_id, case_id)
        logger.info("Linked finding_id=%s to case_id=%s", finding_id, case_id)

    async def mark_status(
        self,
        finding_id: str,
        new_status: str,
        repo: ThreatFindingRepository,
    ) -> None:
        """Transition finding to open | investigating | resolved."""
        assert new_status in ("open", "investigating", "resolved"), \
            f"Invalid status: {new_status}"
        await repo.update_status(finding_id, new_status)
        logger.info("Finding %s -> status=%s", finding_id, new_status)

    async def get_finding_by_id(
        self,
        finding_id: str,
        repo: ThreatFindingRepository,
    ) -> Optional[FindingRecord]:
        """Return the FindingRecord for finding_id, or None if not found."""
        return await repo.get_by_id(finding_id)

    async def list_findings(
        self,
        filters: FindingFilter,
        repo: ThreatFindingRepository,
    ) -> List[FindingRecord]:
        """Return paginated findings matching filters."""
        return await repo.list_findings(filters)

    async def count_findings(
        self,
        filters: FindingFilter,
        repo: ThreatFindingRepository,
    ) -> int:
        """Return the total count matching filters (ignores limit/offset)."""
        return await repo.count_findings(filters)
