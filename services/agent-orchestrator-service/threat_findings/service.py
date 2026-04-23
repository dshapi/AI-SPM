from __future__ import annotations
import json
import logging
import hashlib
from datetime import datetime, timezone
from uuid import uuid4
from typing import TYPE_CHECKING, Optional, List

from cases.schemas import CaseRecord
from models.cases import CaseRepository
from threat_findings.schemas import CreateFindingRequest, FindingRecord, FindingFilter
from threat_findings.models import ThreatFindingRepository
from threat_findings.prioritization.engine import PrioritizationEngine

if TYPE_CHECKING:
    from events.publisher import EventPublisher

logger = logging.getLogger(__name__)

# Minimum priority_score required to auto-open a case.
CASE_OPEN_PRIORITY_THRESHOLD: float = 0.40


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

    # ── Lineage events for agent-opened (threat-hunt) cases ───────────────────
    #
    # Threat-hunt cases use a session_id of the form ``threat-hunt:{rec.id}``.
    # The hunt was not a chat session, but the threat-hunting agent really
    # did perform steps that map onto the lineage event vocabulary:
    #
    #   • collected evidence            → context.retrieved
    #   • scored risk / severity        → risk.calculated
    #   • triggered detection policies  → policy.allowed/escalated/blocked
    #   • produced finding + recs       → output.generated
    #
    # Every value below is read straight off the FindingRecord — hypothesis,
    # risk_score, severity, ttps, triggered_policies, asset, evidence,
    # recommended_actions. We project the agent's hunt into the same
    # session_events shape every other run uses, so the Lineage page renders it.
    #
    # Transport: Kafka (GlobalTopics.LINEAGE_EVENTS) — same path the api
    # service uses. The orchestrator's own LineageEventConsumer drains the
    # topic and writes the rows into session_events via the shared
    # persist_lineage_event service. Same wire envelope as
    # platform_shared/lineage_events.py, just emitted with the orchestrator's
    # async producer.
    @staticmethod
    def _build_threat_hunt_lineage_events(
        *,
        session_id: str,
        finding:    FindingRecord,
        decision:   str,
    ) -> list[dict]:
        """
        Build the canonical 5-event lineage track for a threat-hunt session
        from a FindingRecord. Returns a list of dicts each with keys:
          session_id, event_type, payload, timestamp, correlation_id,
          agent_id, user_id (optional), tenant_id, source

        Pure function — no I/O. Shared by:
          • _emit_threat_hunt_lineage       — publishes them via Kafka on
                                               case creation.
          • backfill_threat_hunt_lineage    — persists them in-process the
                                               first time the Lineage page
                                               asks for events of an
                                               existing threat-hunt session.
        """
        now_iso        = datetime.now(timezone.utc).isoformat()
        correlation_id = str(uuid4())
        tenant_id      = finding.tenant_id
        asset          = finding.asset or None
        hypothesis     = finding.hypothesis or finding.title or "(no hypothesis)"
        risk_score     = float(finding.risk_score or 0.0)
        severity       = (finding.severity or "low").lower()
        ttps           = finding.ttps or []
        triggered      = finding.triggered_policies or []
        evidence       = finding.evidence or []
        recs           = finding.recommended_actions or []

        policy_event_type = {
            "allow":    "policy.allowed",
            "escalate": "policy.escalated",
            "block":    "policy.blocked",
        }.get(decision, "policy.escalated")

        base = dict(
            session_id     = session_id,
            timestamp      = now_iso,
            correlation_id = correlation_id,
            agent_id       = "threat-hunting-agent",
            tenant_id      = tenant_id,
            source         = "threat-hunting-agent",
        )

        return [
            # 1. session.started — the hypothesis the agent investigated
            {**base,
             "event_type": "session.started",
             "user_id":    "threat-hunter",
             "payload": {
                 "prompt":     hypothesis,
                 "agent_id":   "threat-hunting-agent",
                 "asset":      asset,
                 "finding_id": finding.id,
             }},
            # 2. context.retrieved — the evidence the hunt collected
            {**base,
             "event_type": "context.retrieved",
             "payload": {
                 "retrieved_contexts": evidence,
                 "context_count":      len(evidence),
             }},
            # 3. risk.calculated — the agent's own risk score / severity
            {**base,
             "event_type": "risk.calculated",
             "payload": {
                 "risk_score": risk_score,
                 "signals":    ttps,
                 "severity":   severity,
             }},
            # 4. policy.<decision> — the detection policies that fired
            {**base,
             "event_type": policy_event_type,
             "payload": {
                 "decision":           decision,
                 "reason":             f"{severity.upper()} · {finding.title}",
                 "triggered_policies": triggered,
             }},
            # 5. output.generated — the finding + recommended actions
            {**base,
             "event_type": "output.generated",
             "payload": {
                 "verdict":             decision,
                 "summary":             finding.title,
                 "finding_id":          finding.id,
                 "recommended_actions": recs,
             }},
        ]

    @classmethod
    async def _emit_threat_hunt_lineage(
        cls,
        *,
        publisher:  "EventPublisher",
        session_id: str,
        finding:    FindingRecord,
        decision:   str,
    ) -> None:
        """
        Publish the threat-hunting agent's hunt steps as lineage events on
        GlobalTopics.LINEAGE_EVENTS. All payload values come from the
        FindingRecord. Best-effort — never raises.
        """
        try:
            events = cls._build_threat_hunt_lineage_events(
                session_id = session_id,
                finding    = finding,
                decision   = decision,
            )
            for ev in events:
                try:
                    await publisher.emit_lineage_event(**ev)
                except Exception as exc:
                    logger.warning(
                        "threat_hunt_lineage publish_failed session=%s type=%s err=%s",
                        session_id, ev.get("event_type"), exc,
                    )
            logger.info(
                "threat_hunt_lineage published session=%s finding=%s events=%d",
                session_id, finding.id, len(events),
            )
        except Exception as exc:
            logger.warning(
                "threat_hunt_lineage publish_failed finding=%s err=%s",
                finding.id, exc,
            )

    @classmethod
    async def backfill_threat_hunt_lineage(
        cls,
        *,
        finding:      FindingRecord,
        session_id:   str,
        session_repo,                # SessionRepository
        event_repo,                  # EventRepository
    ) -> int:
        """
        Persist the canonical threat-hunt lineage track directly into
        session_events for an EXISTING threat-hunt case that has no events
        yet. Used by the lazy-backfill path on the
        GET /sessions/{sid}/events endpoint so cases opened before the
        Kafka-emit path was wired up — and cases that were created while
        Kafka was unreachable — still render a graph.

        Returns the number of events persisted.
        """
        # Local import keeps the publishing path import-light and avoids
        # forcing services/lineage_ingest into the module-load graph.
        from services.lineage_ingest import LineageEventInput, persist_lineage_event

        # Decision is needed to pick the policy event type. Reconstruct it
        # from the finding's severity, matching what create_finding does.
        severity = (finding.severity or "low").lower()
        _, decision = _SEVERITY_MAP.get(severity, (0.5, "escalate"))

        events = cls._build_threat_hunt_lineage_events(
            session_id = session_id,
            finding    = finding,
            decision   = decision,
        )

        persisted = 0
        for ev in events:
            try:
                ts = ev.get("timestamp")
                if isinstance(ts, str):
                    try:
                        ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    except Exception:
                        ts_dt = datetime.now(timezone.utc)
                else:
                    ts_dt = ts or datetime.now(timezone.utc)

                body = LineageEventInput(
                    session_id     = ev["session_id"],
                    event_type     = ev["event_type"],
                    payload        = ev["payload"],
                    timestamp      = ts_dt,
                    correlation_id = ev.get("correlation_id"),
                    agent_id       = ev.get("agent_id"),
                    user_id        = ev.get("user_id"),
                    tenant_id      = ev.get("tenant_id"),
                    source         = ev.get("source"),
                )
                await persist_lineage_event(session_repo, event_repo, body)
                persisted += 1
            except Exception as exc:
                logger.warning(
                    "threat_hunt_lineage backfill_event_failed session=%s type=%s err=%s",
                    session_id, ev.get("event_type"), exc,
                )

        logger.info(
            "threat_hunt_lineage backfilled session=%s finding=%s events=%d",
            session_id, finding.id, persisted,
        )
        return persisted

    async def create_finding(
        self,
        req: CreateFindingRequest,
        repo: ThreatFindingRepository,
        case_repo: CaseRepository,
        publisher: Optional["EventPublisher"] = None,
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
            source=req.source,
            is_proactive=req.is_proactive,
            confidence=req.confidence,
            risk_score=req.risk_score,
            # Fields previously silently dropped
            asset=req.asset,
            environment=req.environment,
            hypothesis=req.hypothesis,
            correlated_events=req.correlated_events,
            correlated_findings=req.correlated_findings,
            triggered_policies=req.triggered_policies,
            policy_signals=req.policy_signals,
            recommended_actions=req.recommended_actions,
            should_open_case=req.should_open_case,
        )
        await repo.insert(rec)
        logger.info(
            "Created finding id=%s tenant=%s severity=%s should_open_case=%s",
            rec.id, rec.tenant_id, rec.severity, req.should_open_case,
        )

        # ── Prioritization ────────────────────────────────────────────────────────
        async def _lookup_prior(dedup_key: str):
            prior = await repo.get_by_dedup_key(dedup_key)
            if prior is None:
                return None
            return {"first_seen": prior.first_seen, "occurrence_count": prior.occurrence_count}

        rec = await PrioritizationEngine.run(rec, _lookup_prior)
        if rec.priority_score is not None:
            await repo.update_priority_fields(rec)

        # Open a Case only when the agent flagged this as case-worthy AND priority meets threshold
        priority_ok = (rec.priority_score or 0.0) >= CASE_OPEN_PRIORITY_THRESHOLD
        if req.should_open_case and priority_ok:
            risk_score, decision = _SEVERITY_MAP.get(req.severity, (0.5, "escalate"))
            ttps_str = ", ".join(req.ttps) if req.ttps else "none"
            case = CaseRecord(
                case_id=str(uuid4()),
                session_id=f"threat-hunt:{rec.id}",   # threat-hunt scoped session id
                reason=f"threat-hunt · {req.severity.upper()} · {req.title} · TTPs: {ttps_str}",
                summary=f"Threat finding raised by the Threat-hunter agent — {req.description}",
                risk_score=risk_score,
                decision=decision,
            )
            await case_repo.insert(case)
            # Link the case back to the finding record
            rec.case_id = case.case_id
            await repo.attach_case(rec.id, case.case_id)
            logger.info(
                "Opened and linked case case_id=%s for finding id=%s",
                case.case_id, rec.id,
            )
            # Publish the threat-hunting agent's hunt steps as lineage
            # events on the same Kafka topic the api service uses; the
            # orchestrator's LineageEventConsumer drains them into
            # session_events so the Lineage page renders the graph the
            # same way it does for any other session.
            if publisher is not None:
                await self._emit_threat_hunt_lineage(
                    publisher  = publisher,
                    session_id = case.session_id,
                    finding    = rec,
                    decision   = decision,
                )

        # ── Publish finding.created event to Kafka ────────────────────────────
        if publisher is not None:
            try:
                await publisher.emit_finding_created(
                    finding_id=rec.id,
                    tenant_id=rec.tenant_id,
                    severity=rec.severity,
                    title=rec.title,
                    risk_score=rec.risk_score,
                    confidence=rec.confidence,
                    asset=rec.asset,
                    source=rec.source or "api",
                    priority_score=rec.priority_score,
                    should_open_case=req.should_open_case,
                    case_id=rec.case_id,
                )
            except Exception as pub_exc:
                # Never let event publishing failure break the finding creation path
                logger.warning("emit_finding_created failed (non-fatal): %s", pub_exc)

        return rec

    async def persist_finding_from_dict(
        self,
        finding_dict: dict,
        tenant_id: str,
        repo: ThreatFindingRepository,
        case_repo: Optional[CaseRepository] = None,
        publisher: Optional["EventPublisher"] = None,
    ) -> FindingRecord:
        """
        Persist a Finding dict (from run_hunt).
        Opens and links a Case when should_open_case=True (requires case_repo).
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

        should_open = bool(finding_dict.get("should_open_case", False))
        severity = finding_dict.get("severity", "low")

        rec = FindingRecord(
            id=finding_dict.get("finding_id", str(uuid4())),
            batch_hash=batch_hash,
            title=title,
            severity=severity,
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
            should_open_case=should_open,
            source="threat-hunting-agent",
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        # ── Prioritization pipeline ───────────────────────────────────────
        async def _lookup_prior(dedup_key: str) -> Optional[dict]:
            """Return minimal prior-occurrence metadata dict, or None."""
            prior = await repo.get_by_dedup_key(dedup_key)
            if prior is None:
                return None
            return {
                "first_seen": prior.first_seen,
                "occurrence_count": prior.occurrence_count,
            }

        rec = await PrioritizationEngine.run(rec, _lookup_prior)
        # ─────────────────────────────────────────────────────────────────

        await repo.insert(rec)
        logger.info(
            "Persisted finding id=%s tenant=%s severity=%s "
            "priority_score=%.3f suppressed=%s should_open_case=%s",
            rec.id, rec.tenant_id, rec.severity,
            rec.priority_score or 0.0, rec.suppressed, rec.should_open_case,
        )

        # Open a Case and link it when the agent flagged this as case-worthy
        if should_open and case_repo is not None:
            risk_score, decision = _SEVERITY_MAP.get(severity, (0.5, "escalate"))
            ttps = finding_dict.get("triggered_policies") or []
            ttps_str = ", ".join(ttps) if ttps else "none"
            case = CaseRecord(
                case_id=str(uuid4()),
                session_id=f"threat-hunt:{rec.id}",
                reason=(
                    f"threat-hunt · {severity.upper()} · {title} · TTPs: {ttps_str}"
                ),
                summary=(
                    f"Threat finding raised by the Threat-hunter agent — "
                    f"{finding_dict.get('hypothesis', '')}"
                ),
                risk_score=risk_score,
                decision=decision,
            )
            await case_repo.insert(case)
            rec.case_id = case.case_id
            await repo.attach_case(rec.id, case.case_id)
            logger.info(
                "Opened and linked case case_id=%s for finding id=%s",
                case.case_id, rec.id,
            )
            # Publish the threat-hunting agent's hunt steps as lineage
            # events on the same Kafka topic the api service uses; the
            # orchestrator's LineageEventConsumer drains them into
            # session_events so the Lineage page renders the graph the
            # same way it does for any other session.
            if publisher is not None:
                await self._emit_threat_hunt_lineage(
                    publisher  = publisher,
                    session_id = case.session_id,
                    finding    = rec,
                    decision   = decision,
                )

        # ── Publish finding.created event to Kafka ────────────────────────────
        if publisher is not None:
            try:
                await publisher.emit_finding_created(
                    finding_id=rec.id,
                    tenant_id=rec.tenant_id,
                    severity=rec.severity,
                    title=rec.title,
                    risk_score=rec.risk_score,
                    confidence=rec.confidence,
                    asset=rec.asset,
                    source=rec.source or "threat-hunting-agent",
                    priority_score=rec.priority_score,
                    should_open_case=rec.should_open_case or False,
                    case_id=rec.case_id,
                )
            except Exception as pub_exc:
                logger.warning("emit_finding_created failed (non-fatal): %s", pub_exc)

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
        *,
        publisher: Optional["EventPublisher"] = None,
        tenant_id: str = "t1",
        changed_by: Optional[str] = None,
        old_status: Optional[str] = None,
    ) -> None:
        """Transition finding to open | investigating | resolved."""
        assert new_status in ("open", "investigating", "resolved"), \
            f"Invalid status: {new_status}"
        await repo.update_status(finding_id, new_status)
        logger.info("Finding %s -> status=%s", finding_id, new_status)

        # ── Publish finding.status_changed event to Kafka ─────────────────────
        if publisher is not None:
            try:
                await publisher.emit_finding_status_changed(
                    finding_id=finding_id,
                    tenant_id=tenant_id,
                    new_status=new_status,
                    old_status=old_status,
                    changed_by=changed_by,
                )
            except Exception as pub_exc:
                logger.warning("emit_finding_status_changed failed (non-fatal): %s", pub_exc)

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
