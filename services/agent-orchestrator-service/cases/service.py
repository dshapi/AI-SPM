"""
cases/service.py
────────────────
CasesService: builds and stores CaseRecord objects in an in-memory dict.

Usage
─────
  One shared instance wired to app.state.cases_service in main.py lifespan.
  All repo/service arguments are injected per-request by the router.

create_case() returns None when the session_id does not exist in the DB —
the router is responsible for converting that to a 404 HTTP response.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional
from uuid import uuid4

from cases.schemas import CaseRecord
from models.event import EventRepository
from models.session import SessionRecord, SessionRepository
from results.schemas import SessionResults
from results.service import ResultsService

logger = logging.getLogger(__name__)


class CasesService:
    """
    Manages cases in an in-memory dictionary.

    Share one instance via app.state.cases_service; do NOT instantiate
    per-request (you would lose all stored cases between requests).
    """

    def __init__(self) -> None:
        self._cases: Dict[str, CaseRecord] = {}

    async def create_case(
        self,
        session_id: str,
        reason: str,
        session_repo: SessionRepository,
        event_repo: EventRepository,
        results_svc: ResultsService,
    ) -> Optional[CaseRecord]:
        """
        Fetch session + results, build a CaseRecord, and store it.

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
        self._cases[case.case_id] = case
        logger.info(
            "case created case_id=%s session_id=%s decision=%s risk=%.2f",
            case.case_id, session_id, case.decision, case.risk_score,
        )
        return case

    def list_cases(self) -> List[CaseRecord]:
        """Return all cases sorted newest-first."""
        return sorted(self._cases.values(), key=lambda c: c.created_at, reverse=True)


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
