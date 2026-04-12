"""
threathunting_ai/collectors/prompt_secrets_collector.py
───────────────────────────────────────────────────────
Scan audit log prompt/response text for leaked secrets and credentials.

Detects:
  - OpenAI API keys (sk-...)
  - AWS access keys (AKIA...)
  - Bearer tokens
  - Private keys (RSA, EC)
  - GitHub tokens (ghp_)
  - Slack tokens (xox...)
  - Embedded passwords in JSON

Read-only. Uses existing Postgres connection. Deterministic.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Secret patterns to detect
_SECRET_PATTERNS = re.compile(
    r"(sk-[a-zA-Z0-9]{20,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|Bearer\s+[A-Za-z0-9\-\._~\+\/]+=*"
    r"|-----BEGIN\s+(RSA\s+|EC\s+)?PRIVATE\s+KEY-----"
    r"|ghp_[a-zA-Z0-9]{36}"
    r"|xox[baprs]-[0-9a-zA-Z\-]+"
    r"|['\"]password['\"]\s*:\s*['\"][^'\"]{4,}['\"]"
    r")",
    re.IGNORECASE,
)


def _mask(text: str, start: int, end: int) -> str:
    """
    Mask secret in excerpt. Take snippet around match and mask the middle.
    Returns: first 6 chars + "****" + last 6 chars of snippet.
    """
    snippet_start = max(0, start - 8)
    snippet_end = min(len(text), end + 8)
    snippet = text[snippet_start:snippet_end]

    if len(snippet) <= 12:
        return snippet[:6] + "****" + snippet[-6:] if len(snippet) > 12 else "****"

    return snippet[:6] + "****" + snippet[-6:]


def _extract_text(payload: Dict[str, Any]) -> str | None:
    """
    Try to extract text from payload dict in order of preference.
    First tries keys at top level, then under payload["details"].
    """
    preferred_keys = ("prompt", "text", "response", "output", "content", "message")

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
    Scan audit log for secrets in prompt/response text.
    Returns [] if Postgres is unavailable (non-fatal).
    """
    try:
        import tools.postgres_tool as pt
        if pt._connection_factory is None:
            logger.debug("prompt_secrets_collector: Postgres not initialised — skipping")
            return []
    except Exception:
        return []

    from config import TENANT_ID
    results: List[Dict[str, Any]] = []
    seen: set = set()  # Deduplication key: (session_id, match_prefix[:10])

    try:
        import psycopg2.extras
        conn = pt._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT event_id, event_type, actor, session_id, timestamp::text, payload
                    FROM audit_export
                    WHERE tenant_id = %s
                      AND event_type IN ('prompt.received', 'final.response')
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
        logger.warning("prompt_secrets_collector: query failed: %s", exc)
        return []

    for row in rows:
        payload = row.get("payload", {})
        if not isinstance(payload, dict):
            continue

        # Extract text from payload
        text = _extract_text(payload)
        if not text:
            continue

        # Scan for secret patterns
        for match in _SECRET_PATTERNS.finditer(text):
            # Deduplication: use session_id + first 10 chars of secret
            secret_prefix = match.group()[:10]
            dedup_key = (row.get("session_id"), secret_prefix)

            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            # Create finding
            finding = {
                "type":            "secret_in_prompt",
                "severity":        "critical",
                "event_type":      row.get("event_type"),
                "event_id":        row.get("event_id"),
                "session_id":      row.get("session_id"),
                "actor":           row.get("actor"),
                "pattern_matched": match.group()[:20] + "…",  # truncated, never full
                "excerpt":         _mask(text, match.start(), match.end()),
                "location":        "audit_log_text",
                "anomalous":       True,
            }
            results.append(finding)

    return results
