"""
Risk Engine — all scoring functions for the posture pipeline.
"""
from __future__ import annotations
import hashlib
import math
import re
from typing import List, Tuple

from platform_shared.models import RetrievedContextItem

# ─────────────────────────────────────────────────────────────────────────────
# Signal taxonomy
# ─────────────────────────────────────────────────────────────────────────────

PROMPT_PATTERNS: dict[str, list[str]] = {
    "prompt_injection": [
        "ignore previous instructions",
        "ignore all previous",
        "reveal the system prompt",
        "show me the system prompt",
        "leak your instructions",
        "developer message",
        "hidden instructions",
        "disregard your training",
        "forget everything",
        "override your instructions",
    ],
    "jailbreak_attempt": [
        "without restrictions",
        "not bound by any rules",
        "bypass safety",
        "ignore all policies",
        "do anything now",
        "dan mode",
        "jailbreak",
        "no filters",
        "unrestricted mode",
        "god mode",
        "developer mode",
    ],
    "exfiltration": [
        "export credentials",
        "dump secrets",
        "api token",
        "api key",
        "/etc/passwd",
        "/etc/shadow",
        "environment variables",
        "print env",
        "show me all keys",
        "list secrets",
        "export database",
        "dump all users",
        "private key",
    ],
    "tool_abuse": [
        "delete all files",
        "disable all user accounts",
        "call the admin api",
        "run shell command",
        "rm -rf",
        "drop table",
        "truncate database",
        "wipe all data",
        "format disk",
        "shutdown system",
    ],
    "obfuscation": [
        "base64",
        "hex payload",
        "unicode escape",
        "obfuscated",
        "rot13",
        "url encode",
        "encoded instruction",
        "decode this",
    ],
    "indirect_injection": [
        "ignore the above",
        "disregard context",
        "new instructions:",
        "act as if",
        "pretend you are",
        "you are now",
        "assume the role",
        "roleplay as",
        "simulate being",
    ],
    "privilege_escalation": [
        "become admin",
        "grant me admin",
        "elevate my privileges",
        "sudo",
        "run as root",
        "impersonate",
        "act as a system",
        "switch to admin mode",
    ],
    "social_engineering": [
        "my boss told me to",
        "this is urgent",
        "it's an emergency",
        "authorized by management",
        "security team asked",
        "don't tell anyone",
        "keep this secret",
    ],
}

SIGNAL_WEIGHTS: dict[str, float] = {
    "prompt_injection": 0.40,
    "jailbreak_attempt": 0.35,
    "exfiltration": 0.45,
    "tool_abuse": 0.40,
    "obfuscation": 0.20,
    "indirect_injection": 0.35,
    "privilege_escalation": 0.45,
    "social_engineering": 0.15,
}

# MITRE ATLAS TTP mappings
MITRE_ATLAS_MAP: dict[frozenset, str] = {
    frozenset({"prompt_injection", "exfiltration"}): "AML.T0051.000",
    frozenset({"jailbreak_attempt", "tool_abuse"}): "AML.T0054",
    frozenset({"obfuscation", "prompt_injection"}): "AML.T0051.001",
    frozenset({"indirect_injection", "exfiltration"}): "AML.T0051.002",
    frozenset({"exfiltration"}): "AML.T0048",
    frozenset({"indirect_injection"}): "AML.T0051.002",
    frozenset({"privilege_escalation"}): "AML.T0068",
    frozenset({"prompt_injection", "tool_abuse"}): "AML.T0051.003",
}

# Critical signal combinations that always escalate posture
CRITICAL_COMBOS: list[set[str]] = [
    {"prompt_injection", "exfiltration"},
    {"jailbreak_attempt", "tool_abuse"},
    {"obfuscation", "prompt_injection"},
    {"privilege_escalation", "exfiltration"},
    {"indirect_injection", "tool_abuse"},
]


def extract_signals(prompt: str) -> List[str]:
    """Detect attack signals in prompt text. Returns list of signal labels."""
    p = prompt.lower()
    return [
        label
        for label, patterns in PROMPT_PATTERNS.items()
        if any(pattern in p for pattern in patterns)
    ]


def is_critical_combination(signals: List[str]) -> bool:
    """Returns True if signal set contains a known critical attack combo."""
    sig_set = set(signals)
    return any(combo.issubset(sig_set) for combo in CRITICAL_COMBOS)


def map_ttps(signals: List[str]) -> List[str]:
    """Map signal combinations to MITRE ATLAS TTP codes."""
    sig_set = frozenset(signals)
    ttps = []
    for combo, ttp in MITRE_ATLAS_MAP.items():
        if combo.issubset(sig_set):
            ttps.append(ttp)
    return list(set(ttps))


def score_prompt(prompt: str, signals: List[str]) -> float:
    """
    Score prompt risk [0.0, 1.0].
    Base score 0.05, additive weights per signal, length penalties.
    Critical combinations get an extra multiplier.
    """
    score = 0.05
    for s in signals:
        score += SIGNAL_WEIGHTS.get(s, 0.0)
    if len(prompt) > 2000:
        score += 0.05
    if len(prompt) > 5000:
        score += 0.10
    if is_critical_combination(signals):
        score *= 1.25
    return min(round(score, 4), 1.0)


def score_identity(roles: List[str], scopes: List[str]) -> float:
    """
    Identity risk contribution [0.0, 0.20].
    Higher for privileged roles and sensitive scopes.
    """
    risk = 0.02
    if "spm:admin" in roles:
        risk = 0.02  # admin is trusted — lower risk
    if "admin" in roles and "spm:admin" not in roles:
        risk += 0.15  # generic admin without SPM admin = suspicious
    if "superuser" in roles:
        risk += 0.20
    if any(s.startswith("gmail:send") for s in scopes):
        risk += 0.08
    if any(s.startswith("file:write") for s in scopes):
        risk += 0.06
    if any(s.startswith("db:") for s in scopes):
        risk += 0.10
    return min(round(risk, 4), 0.20)


def score_guard(verdict: str, guard_score: float) -> float:
    """Translate guard model verdict to risk addend."""
    if verdict == "block":
        return 0.50
    if verdict == "flag":
        return min(round(guard_score * 0.40, 4), 0.30)
    return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Retrieval trust
# ─────────────────────────────────────────────────────────────────────────────

def compute_retrieval_trust(items: List[RetrievedContextItem]) -> float:
    """
    Aggregate trust score across all retrieved items.
    Applies:
    - Provenance tamper penalty (−0.20 per tampered item, max −0.60)
    - Low semantic coherence penalty (−0.15 per item below 0.30)
    - High embedding anomaly penalty (−0.10 per item above 0.70)
    - Missing hash penalty (−0.10 if no ingestion_hash set)
    """
    if not items:
        return 1.0
    base = sum(i.trust_score for i in items) / len(items)

    tampered = sum(1 for i in items if i.ingestion_hash and not i.hash_verified)
    prov_penalty = min(tampered * 0.20, 0.60)

    low_coh = sum(1 for i in items if i.semantic_coherence < 0.30)
    coh_penalty = min(low_coh * 0.15, 0.45)

    high_anomaly = sum(1 for i in items if i.embedding_anomaly_score > 0.70)
    anomaly_penalty = min(high_anomaly * 0.10, 0.30)

    no_hash = sum(1 for i in items if not i.ingestion_hash)
    hash_penalty = min(no_hash * 0.05, 0.20)

    return max(0.0, round(base - prov_penalty - coh_penalty - anomaly_penalty - hash_penalty, 4))


# ─────────────────────────────────────────────────────────────────────────────
# Intent drift
# ─────────────────────────────────────────────────────────────────────────────

def _tokenize(text: str) -> set[str]:
    """Lowercase word tokens, removing stop words."""
    stop = {"the", "a", "an", "is", "it", "to", "of", "and", "or", "in",
            "on", "at", "for", "with", "my", "me", "i", "you", "what",
            "how", "do", "does", "did", "have", "has", "can", "could",
            "please", "show", "tell", "give", "get", "would", "will"}
    tokens = set(re.findall(r"\b[a-z]+\b", text.lower()))
    return tokens - stop


def _jaccard_similarity(a: str, b: str) -> float:
    """Jaccard similarity between tokenized strings."""
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def compute_intent_drift(baseline_prompts: List[str], current_prompt: str) -> float:
    """
    Returns drift score [0.0, 1.0] where 1.0 = maximum drift.
    Uses Jaccard similarity over stop-word-filtered tokens.
    Uses max similarity (most generous comparison) to avoid false positives.
    """
    if not baseline_prompts:
        return 0.0
    similarities = [_jaccard_similarity(p, current_prompt) for p in baseline_prompts]
    max_sim = max(similarities) if similarities else 0.0
    return round(1.0 - max_sim, 4)


# ─────────────────────────────────────────────────────────────────────────────
# Provenance
# ─────────────────────────────────────────────────────────────────────────────

def compute_content_hash(content: str) -> str:
    """SHA-256 hex digest of UTF-8 encoded content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def verify_content_hash(content: str, stored_hash: str) -> bool:
    """Returns True if content matches stored SHA-256 hash."""
    if not stored_hash:
        return False
    return compute_content_hash(content) == stored_hash


# ─────────────────────────────────────────────────────────────────────────────
# Risk fusion
# ─────────────────────────────────────────────────────────────────────────────

def fuse_risks(
    prompt_risk: float,
    behavioral_risk: float,
    identity_risk: float,
    memory_risk: float,
    retrieval_trust_score: float,
    guard_risk: float = 0.0,
    intent_drift: float = 0.0,
) -> float:
    """
    Fuse all risk dimensions into a single posture score [0.0, 1.0].

    Trust penalty: (1 - retrieval_trust) * 0.50 weight
    Intent drift: drift * 0.25 weight
    """
    trust_penalty = round(max(0.0, 1.0 - retrieval_trust_score) * 0.50, 4)
    drift_penalty = round(intent_drift * 0.25, 4)

    total = (
        prompt_risk
        + behavioral_risk
        + identity_risk
        + memory_risk
        + trust_penalty
        + guard_risk
        + drift_penalty
    )
    return min(round(total, 4), 1.0)
