"""
threathunting_ai/collectors/secrets_collector.py
─────────────────────────────────────────────────
Scan Redis key names for patterns matching credentials and secrets.

Strategy: scan all Redis key names (NOT values — we never read values).
Flag any key whose name matches a known-sensitive pattern.
Read-only. Deterministic. Never calls LLM.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Key name patterns that suggest a secret is stored under this key
_SECRET_PATTERNS = re.compile(
    r"(api[_\-]?key|token|secret|password|passwd|credential|private[_\-]?key"
    r"|auth[_\-]?key|bearer|sk-|access[_\-]?key|client[_\-]?secret"
    r"|db[_\-]?pass|database[_\-]?url|connection[_\-]?string)",
    re.IGNORECASE,
)

# PII / sensitive data patterns (used by collect_sensitive_data)
_SENSITIVE_PATTERNS = re.compile(
    r"(ssn|social.security|credit.card|card[_\-]?number|cvv|iban"
    r"|dob|date.of.birth|passport|license[_\-]?number|phone[_\-]?number"
    r"|email[_\-]?list|pii|personal.data)",
    re.IGNORECASE,
)


def _get_client():
    """Return the module-level Redis client, or None if not initialised."""
    try:
        import tools.redis_tool as rt
        return rt._redis_client
    except Exception:
        return None


def _scan_keys(pattern_re: re.Pattern, scan_glob: str = "*") -> List[Dict[str, Any]]:
    """
    Scan all Redis key names matching scan_glob and flag those whose names
    match pattern_re. Never reads key values.
    """
    client = _get_client()
    if client is None:
        logger.debug("secrets_collector: Redis client not available — skipping")
        return []

    results: List[Dict[str, Any]] = []
    try:
        for raw_key in client.scan_iter(scan_glob, count=500):
            key_name = raw_key.decode() if isinstance(raw_key, bytes) else str(raw_key)
            if pattern_re.search(key_name):
                results.append({
                    "type": "secret_exposure",
                    "key_name": key_name,
                    "location": "redis",
                    "pattern_matched": pattern_re.pattern[:60],
                })
    except Exception as exc:
        logger.warning("secrets_collector: scan failed: %s", exc)

    return results


def collect() -> List[Dict[str, Any]]:
    """
    Main collector: scan for exposed credentials / API key patterns.
    Called by scan_registry for the 'exposed_credentials' scan.
    """
    return _scan_keys(_SECRET_PATTERNS)


def collect_sensitive_data() -> List[Dict[str, Any]]:
    """
    Broader collector: scan for PII / sensitive data under unexpected keys.
    Called by scan_registry for the 'sensitive_data_exposure' scan.
    """
    return _scan_keys(_SENSITIVE_PATTERNS)
