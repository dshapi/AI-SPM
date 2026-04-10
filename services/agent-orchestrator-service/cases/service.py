"""
cases/service.py
────────────────
CasesService: builds CaseRecord objects and persists them via CaseRepository.

Usage
─────
  One shared *stateless* instance wired to app.state.cases_service in main.py.
  All repository arguments are injected per-request by the router.

  State now lives in the DB — the service survives container restarts.
"""
from __future__ import annotations

import logging
from typing import List, Optional
from uuid import uuid4

from cases.schemas import CaseRecord
from models.cases import CaseRepository
from models.event import EventRepository
from models.session import SessionRecord, SessionRepository
from results.schemas import SessionResults
from results.service import ResultsService

logger = logging.getLogger(__name__)


class CasesService:
    """
    Stateless service — all persistence is delegated to CaseRepository.
    One instance is stored on app.state; no mutable state is held here.
    """

    async def create_case(
        self,
        session_id: str,
        reason: str,
        session_repo: SessionRepository,
        event_repo: EventRepository,
        results_svc: ResultsService,
        case_repo: CaseRepository,
    ) -> Optional[CaseRecord]:
        """
        Fetch session + results, build a CaseRecord, and persist to the DB.

        Returns:
            CaseRecord on success.
            None if the session_id does not exist.
        """
        session = await session_repo.get_by_id(session_id)
        if session is None:
            logger.warning("create_case: session not found session_id=%s", session_id)
            return None

        events = await event_repo.get_by_session_id(session_id)
        results = await results_svc.get_results(session_id, event_repo)

        summary = _build_summary(session, results, event_count=len(events))
        case = CaseRecord(
            case_id=str(uuid4()),
            session_id=session_id,
            reason=reason,
            summary=summary,
            risk_score=results.risk.score,
            decision=results.decision,
        )

        await case_repo.insert(case)
        logger.info(
            "case created case_id=%s session_id=%s decision=%s risk=%.2f",
            case.case_id, session_id, case.decision, case.risk_score,
        )
        return case

    async def list_cases(
        self,
        case_repo: CaseRepository,
        limit: int = 200,
    ) -> List[CaseRecord]:
        """Return all cases from the DB, newest-first."""
        return await case_repo.list_all(limit=limit)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_summary(
    session: SessionRecord,
    results: SessionResults,
    event_count: int,
) -> str:
    """Build a one-line human-readable summary for the case."""
    return (
        f"Session {session.session_id} (agent: {session.agent_id}) escalated. "
        f"Risk tier: {results.risk.tier} (score {results.risk.score:.2f}). "
        f"Policy decision: {results.decision}. "
        f"Events observed: {event_count}."
    )
