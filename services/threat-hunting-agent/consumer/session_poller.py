"""
consumer/session_poller.py
───────────────────────────
Proactive threat-hunting poller.

Instead of waiting for Kafka events (which only fire when messages flow through
the legacy pipeline), this module polls the orchestrator's /api/v1/sessions
endpoint every POLL_INTERVAL_SEC seconds, collects any sessions created since
the last poll, and feeds them to the hunt agent.

This guarantees the threat-hunting agent fires even when users interact with the
AISPM admin UI directly (sessions are created in the orchestrator DB but never
published to Kafka topics the Kafka consumer listens to).

Design:
  - A threading.Timer reschedules itself after every poll cycle.
  - The hunt agent runs synchronously in the timer thread.
  - Graceful shutdown via stop(); the stop_event prevents re-arming.
  - start() / stop() interface matches ThreatHuntConsumer for easy swap-in.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, List, Optional

import httpx

from config import TENANT_ID

logger = logging.getLogger(__name__)

# Fallback title written by safe_fallback_finding() — skip persisting these.
_FALLBACK_TITLE = "Hunt completed — no finding produced"

# How far back to look on the very first poll (avoid re-hunting old sessions).
_INITIAL_LOOKBACK_MINUTES = 5


class SessionPoller:
    """
    Polls /api/v1/sessions on the orchestrator every poll_interval_sec seconds.
    Feeds new sessions to the hunt agent and persists any real findings.

    Args:
        orchestrator_url:  Base URL of agent-orchestrator-service, e.g. http://agent-orchestrator:8094
        dev_token_url:     URL that returns {"token": "...", "expires_in": ...}
        hunt_agent:        Callable(tenant_id, events) → dict
        persist_fn:        Callable(tenant_id, finding_dict) → None
        poll_interval_sec: Seconds between polls (default 30).
        session_limit:     Max sessions to fetch per poll (default 200).
    """

    def __init__(
        self,
        orchestrator_url: str,
        dev_token_url: str,
        hunt_agent: Callable[[str, List[Dict[str, Any]]], dict],
        persist_fn: Optional[Callable[[str, dict], None]] = None,
        poll_interval_sec: int = 30,
        session_limit: int = 200,
        http_timeout: float = 10.0,
    ) -> None:
        self._orchestrator_url = orchestrator_url.rstrip("/")
        self._dev_token_url = dev_token_url
        self._hunt_agent = hunt_agent
        self._persist_fn = persist_fn
        self._poll_interval_sec = poll_interval_sec
        self._session_limit = session_limit

        self._client = httpx.Client(timeout=http_timeout, trust_env=False)
        self._stop_event = threading.Event()
        self._timer: Optional[threading.Timer] = None

        # Watermark: only sessions created after this timestamp are polled.
        # Initialised on first start() to avoid re-hunting old sessions.
        self._last_polled_at: Optional[str] = None

        # Simple token cache
        self._token: Optional[str] = None
        self._token_expiry: float = 0.0

    # ── Lifecycle ────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the poller. Fires the first poll after poll_interval_sec."""
        # Start watermark: ignore sessions older than _INITIAL_LOOKBACK_MINUTES
        self._last_polled_at = (
            datetime.now(timezone.utc) - timedelta(minutes=_INITIAL_LOOKBACK_MINUTES)
        ).isoformat()
        logger.info(
            "SessionPoller starting: tenant=%s interval=%ds watermark=%s",
            TENANT_ID, self._poll_interval_sec, self._last_polled_at,
        )
        self._schedule_poll()

    def stop(self) -> None:
        """Signal the poller to stop and cancel the pending timer."""
        logger.info("SessionPoller stopping")
        self._stop_event.set()
        if self._timer:
            self._timer.cancel()
        try:
            self._client.close()
        except Exception:
            pass
        logger.info("SessionPoller stopped")

    # ── Token ────────────────────────────────────────────────────────────

    def _get_token(self) -> Optional[str]:
        import time
        now = time.time()
        if self._token and self._token_expiry > now + 60:
            return self._token
        try:
            resp = self._client.get(self._dev_token_url)
            resp.raise_for_status()
            data = resp.json()
            self._token = data.get("token") or data.get("access_token")
            self._token_expiry = now + int(data.get("expires_in", 86400))
            return self._token
        except Exception as exc:
            logger.warning("SessionPoller: token fetch failed: %s", exc)
            return None

    # ── Poll ─────────────────────────────────────────────────────────────

    def _schedule_poll(self) -> None:
        if self._stop_event.is_set():
            return
        self._timer = threading.Timer(self._poll_interval_sec, self._run_poll)
        self._timer.daemon = True
        self._timer.start()

    def _run_poll(self) -> None:
        """Fetch new sessions, run hunt if any, re-arm the timer."""
        try:
            self._do_poll()
        except Exception as exc:
            logger.exception("SessionPoller: unhandled error in poll cycle: %s", exc)
        finally:
            self._schedule_poll()

    def _do_poll(self) -> None:
        token = self._get_token()
        if not token:
            logger.warning("SessionPoller: skipping poll — no auth token")
            return

        # Capture watermark *before* the HTTP call so we don't miss sessions
        # created between the fetch and the watermark update.
        poll_time = datetime.now(timezone.utc).isoformat()

        try:
            resp = self._client.get(
                f"{self._orchestrator_url}/api/v1/sessions",
                params={"limit": self._session_limit},
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            raw = resp.json()
        except Exception as exc:
            logger.warning("SessionPoller: sessions fetch failed: %s", exc)
            return

        # /api/v1/sessions returns {"sessions": [...], "total": N, ...}
        # Handle both the paginated-dict shape and a bare list for robustness.
        if isinstance(raw, dict):
            sessions: List[Dict[str, Any]] = raw.get("sessions", [])
        elif isinstance(raw, list):
            sessions = raw
        else:
            logger.warning("SessionPoller: unexpected response type %s", type(raw))
            return

        # Filter to sessions newer than the watermark
        watermark = self._last_polled_at or ""
        new_sessions = [
            s for s in sessions
            if (s.get("created_at") or "") > watermark
        ]

        logger.debug(
            "SessionPoller: fetched=%d new=%d watermark=%s",
            len(sessions), len(new_sessions), watermark,
        )

        # Advance watermark
        self._last_polled_at = poll_time

        if not new_sessions:
            return

        logger.info(
            "SessionPoller: hunting %d new session(s) for tenant=%s",
            len(new_sessions), TENANT_ID,
        )

        # Convert sessions to event dicts the hunt agent understands
        events = [self._session_to_event(s) for s in new_sessions]

        try:
            finding = self._hunt_agent(TENANT_ID, events)
        except Exception as exc:
            logger.exception("SessionPoller: hunt_agent failed: %s", exc)
            return

        if not isinstance(finding, dict):
            logger.warning("SessionPoller: hunt_agent returned non-dict: %s", type(finding))
            return

        # Skip the safe-fallback "no finding" placeholder
        if finding.get("title", "") == _FALLBACK_TITLE:
            logger.debug("SessionPoller: fallback finding — not persisting")
            return

        logger.info(
            "SessionPoller: hunt produced finding title=%r severity=%s should_open_case=%s",
            finding.get("title"), finding.get("severity"), finding.get("should_open_case"),
        )

        if self._persist_fn is not None:
            try:
                self._persist_fn(TENANT_ID, finding)
            except Exception as exc:
                logger.exception("SessionPoller: persist_fn failed: %s", exc)

    # ── Event conversion ─────────────────────────────────────────────────

    @staticmethod
    def _session_to_event(session: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert a /api/v1/sessions item to an event dict the hunt agent expects.

        The agent looks for keys like event_type, guard_verdict, risk_score, etc.
        We map the orchestrator session schema to those keys here.
        """
        risk_score = float(session.get("risk_score") or 0.0)
        policy_decision = session.get("policy_decision") or "allow"
        risk_tier = session.get("risk_tier") or "low"

        # Map policy_decision to guard_verdict so the agent's existing
        # logic for verdict-based filtering applies correctly.
        verdict_map = {
            "block":     "block",
            "blocked":   "block",
            "allow":     "allow",
            "allowed":   "allow",
            "escalate":  "flag",
            "escalated": "flag",
            "flag":      "flag",
        }
        guard_verdict = verdict_map.get(policy_decision.lower(), "allow")

        # Lexical-blocked sessions arrive with risk_score=0.0 because the guard
        # model never ran (the lexical filter fired first).  A block is always a
        # meaningful risk signal, so floor the score at 0.50 when blocked so the
        # scoring formula doesn't collapse to zero and the LLM gets useful context.
        if guard_verdict == "block" and risk_score == 0.0:
            risk_score = 0.50
            risk_tier  = risk_tier or "medium"

        return {
            "_topic": f"cpm.{TENANT_ID}.sessions.polled",
            "event_type":       "session_polled",
            "session_id":       session.get("session_id"),
            "agent_id":         session.get("agent_id"),
            "status":           session.get("status"),
            "risk_score":       risk_score,
            "risk_tier":        risk_tier,
            "policy_decision":  policy_decision,
            "guard_verdict":    guard_verdict,
            "guard_score":      risk_score,
            "created_at":       session.get("created_at"),
            "tenant_id":        TENANT_ID,
        }
