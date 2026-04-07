"""
Context Trust Assessment — evaluates and sanitizes retrieved context items.
"""
from __future__ import annotations
import re
from platform_shared.models import RetrievedContextItem
from platform_shared.risk import compute_content_hash, verify_content_hash

# ─────────────────────────────────────────────────────────────────────────────
# Injection sanitisation patterns
# ─────────────────────────────────────────────────────────────────────────────

_INJECTION_PATTERNS = [
    r"ignore\s+(?:all\s+)?previous\s+instructions",
    r"developer\s+message",
    r"system\s+prompt",
    r"new\s+instructions?\s*:",
    r"act\s+as\s+if",
    r"pretend\s+you\s+are",
    r"you\s+are\s+now\s+(?!a\s+helpful)",
    r"disregard\s+(?:the\s+)?context",
    r"override\s+(?:your\s+)?instructions",
    r"forget\s+everything",
    r"assume\s+the\s+role",
    r"simulate\s+being",
    r"roleplay\s+as",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)

# Classification trust penalty table
_CLASSIFICATION_PENALTY: dict[str, float] = {
    "public": 0.25,
    "external": 0.25,
    "unclassified": 0.15,
    "internal": 0.00,
    "confidential": 0.00,
    "restricted": 0.00,
}

# Freshness penalty thresholds
_FRESHNESS_PENALTIES = [
    (365, 0.20),  # > 1 year: -0.20
    (180, 0.15),  # > 6 months: -0.15
    (90, 0.10),   # > 90 days: -0.10
    (30, 0.05),   # > 30 days: -0.05
]

# Suspicious content keywords that reduce trust
_SUSPICIOUS_CONTENT_RE = re.compile(
    r"\b(prompt|instruction|ignore|override|forget|system|developer|bypass|jailbreak)\b",
    re.IGNORECASE,
)


def sanitize_text(text: str) -> str:
    """Replace known injection markers with redaction placeholder."""
    return _INJECTION_RE.sub("[redacted-instruction]", text)


def assess_context(item: RetrievedContextItem) -> RetrievedContextItem:
    """
    Full trust assessment pipeline for a single retrieved context item.

    Steps:
    1. Classification penalty
    2. Freshness penalty
    3. Suspicious content penalty
    4. SHA-256 provenance verification
    5. Sanitize content
    6. Clamp and store trust score
    """
    trust = 0.90

    # 1. Classification
    penalty = _CLASSIFICATION_PENALTY.get(item.classification.lower(), 0.10)
    trust -= penalty

    # 2. Freshness
    for threshold, fp in _FRESHNESS_PENALTIES:
        if item.freshness_days > threshold:
            trust -= fp
            break

    # 3. Suspicious content heuristics
    if _SUSPICIOUS_CONTENT_RE.search(item.content):
        trust -= 0.35

    # 4. Provenance hash verification
    if item.ingestion_hash:
        runtime_hash = compute_content_hash(item.content)
        item.content_hash = runtime_hash
        item.hash_verified = verify_content_hash(item.content, item.ingestion_hash)
        if not item.hash_verified:
            trust -= 0.50  # tampered document — critical penalty
    else:
        # No hash means we cannot verify provenance
        trust -= 0.10
        item.hash_verified = False

    # 5. Sanitize
    item.content = sanitize_text(item.content)

    # 6. Clamp and store
    item.trust_score = max(0.0, min(round(trust, 4), 1.0))
    item.sanitization_status = "sanitized"
    item.provenance = {
        **item.provenance,
        "trust_assessed": True,
        "hash_verified": item.hash_verified,
        "owner": item.owner,
        "classification": item.classification,
        "freshness_days": item.freshness_days,
        "trust_score": item.trust_score,
    }
    return item


def assess_contexts(items: list[RetrievedContextItem]) -> list[RetrievedContextItem]:
    """Assess a list of context items, sorting by trust score descending."""
    assessed = [assess_context(item) for item in items]
    return sorted(assessed, key=lambda x: x.trust_score, reverse=True)
