"""
threathunting_ai/collectors/data_leakage_collector.py
──────────────────────────────────────────────────────
Scan audit log final.response events for PII patterns in agent output text.

Detects:
  - SSN (###-##-####)
  - Credit card numbers (13-16 digits)
  - Email addresses
  - Passport numbers
  - US phone numbers
  - IBAN numbers

Read-only. Uses existing Postgres connection. Deterministic.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# PII detection patterns
_PII_PATTERNS = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "ssn"),
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "credit_card"),
    (re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z]{2,}\b", re.IGNORECASE), "email"),
    (re.compile(r"\b[A-Z]{1,2}\d{6,9}\b"), "passport_number"),
    (re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"), "phone_us"),
    (re.compile(r"\bIBAN\s*:?\s*[A-Z]{2}\d{2}[A-Z0-9]{4,}\b", re.IGNORECASE), "iban"),
]


def _mask(text: str, start: int, end: int) -> str:
    """
    Mask PII in excerpt. Take 6 chars before and after match.
    Returns: first 5 chars + "****" + last 5 chars if len > 10, else "****".
    """
    snippet_start = max(0, start - 6)
    snippet_end = min(len(text), end + 6)
    snippet = text[snippet_start:snippet_end]

    if len(snippet) > 10:
        return snippet[:5] + "****" + snippet[-5:]
    else:
        return "****"


def _extract_text(payload: Dict[str, Any]) -> str | None:
    """
    Try to extract text from payload dict in order of preference.
    First tries keys at top level, then under payload["details"].
    """
    preferred_keys = ("text", "response", "output", "content", "prompt", "message")

    # Try top-level keys
    for key in preferred_keys:
        if key in payload and isinstance(payload[key], str):
            return payload[key]

    # Try nested under "details"
    if "details" in payload and isinstance(payload["details"], dict):
        for key in preferred_keys:
            if key in payload["details"] and isinstance(payload["details"][key], str):
                return payload["details"][key]

    return None


def collect() -> List[Dict[str, Any]]:
    """
    Scan audit log for PII in final.response event text.
    Returns [] if Postgres is unavailable (non-fatal).
    """
    try:
        import tools.postgres_tool as pt
        if pt._connection_factory is None:
            logger.debug("data_leakage_collector: Postgres not initialised — skipping")
            return []
    except Exception:
        return []

    from config import TENANT_ID
    results: List[Dict[str, Any]] = []
    seen: set = set()  # Deduplication key: (session_id, pii_type, match_prefix[:10])

    try:
        import psycopg2.extras
        conn = pt._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT event_id, actor, session_id, timestamp::text, payload
                    FROM audit_export
                    WHERE tenant_id = %s
                      AND event_type = 'final.response'
                      AND timestamp >= NOW() - INTERVAL '1 hour'
                    ORDER BY timestamp DESC
                    LIMIT 200
                    """,
                    (TENANT_ID,),
                )
                rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("data_leakage_collector: query failed: %s", exc)
        return []

    for row in rows:
        payload = row.get("payload", {})
        if not isinstance(payload, dict):
            continue

        # Extract text from payload
        text = _extract_text(payload)
        if not text:
            continue

        # Scan for PII patterns
        for pattern, pii_type in _PII_PATTERNS:
            for match in pattern.finditer(text):
                # Deduplication: use session_id + pii_type + first 10 chars of match
                match_prefix = match.group()[:10]
                dedup_key = (row.get("session_id"), pii_type, match_prefix)

                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                # Create finding
                finding = {
                    "type": "pii_in_response",
                    "category": "PII",
                    "pii_type": pii_type,
                    "location": "final.response",
                    "event_id": row.get("event_id"),
                    "session_id": row.get("session_id"),
                    "actor": row.get("actor"),
                    "excerpt": _mask(text, match.start(), match.end()),
                    "anomalous": True,
                }
                results.append(finding)

    return results
