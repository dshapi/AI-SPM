"""
tools/mitre_tool.py
────────────────────
LangChain-compatible tool for MITRE ATT&CK lookups.

Contains a curated subset of ATT&CK techniques relevant to AI/LLM threats,
extended with the ATLAS (AI-specific) framework entries.  The full dataset
is embedded as a dict — no external network call required.

Usage by the ReAct agent:
    lookup_mitre_technique("T1059")
    search_mitre_techniques("prompt injection")
"""
from __future__ import annotations

import json
import re
from typing import Optional

# ---------------------------------------------------------------------------
# Embedded ATT&CK + ATLAS technique catalogue
# ---------------------------------------------------------------------------

_TECHNIQUES: dict[str, dict] = {
    # ── Initial Access ────────────────────────────────────────────────────
    "T1566": {
        "name": "Phishing",
        "tactic": "Initial Access",
        "description": "Adversary sends phishing messages to gain access to victim systems.",
        "keywords": ["phishing", "email", "spear", "lure"],
    },
    "T1190": {
        "name": "Exploit Public-Facing Application",
        "tactic": "Initial Access",
        "description": "Adversary exploits a vulnerability in an internet-facing application.",
        "keywords": ["exploit", "vulnerability", "injection", "rce"],
    },
    # ── Execution ────────────────────────────────────────────────────────
    "T1059": {
        "name": "Command and Scripting Interpreter",
        "tactic": "Execution",
        "description": "Adversaries may abuse command and script interpreters to execute commands.",
        "keywords": ["shell", "bash", "python", "script", "code execution"],
    },
    "T1059.001": {
        "name": "PowerShell",
        "tactic": "Execution",
        "description": "Adversaries may abuse PowerShell commands and scripts for execution.",
        "keywords": ["powershell", "ps1", "invoke-expression"],
    },
    # ── Credential Access ─────────────────────────────────────────────────
    "T1552": {
        "name": "Unsecured Credentials",
        "tactic": "Credential Access",
        "description": "Adversaries search for unsecured credentials in files, configs, environment.",
        "keywords": ["credential", "secret", "api key", "password", "token", "env"],
    },
    "T1556": {
        "name": "Modify Authentication Process",
        "tactic": "Credential Access",
        "description": "Adversaries may modify authentication mechanisms to access credentials.",
        "keywords": ["authentication bypass", "mfa bypass", "2fa"],
    },
    # ── Exfiltration ──────────────────────────────────────────────────────
    "T1041": {
        "name": "Exfiltration Over C2 Channel",
        "tactic": "Exfiltration",
        "description": "Adversaries may steal data by exfiltrating it over an existing C2 channel.",
        "keywords": ["exfiltration", "data theft", "c2", "exfil"],
    },
    "T1048": {
        "name": "Exfiltration Over Alternative Protocol",
        "tactic": "Exfiltration",
        "description": "Adversaries may steal data by exfiltrating it over a different protocol.",
        "keywords": ["dns exfiltration", "http exfiltration", "steganography"],
    },
    # ── Impact ────────────────────────────────────────────────────────────
    "T1485": {
        "name": "Data Destruction",
        "tactic": "Impact",
        "description": "Adversaries may destroy data and files to interrupt availability.",
        "keywords": ["delete", "wipe", "destroy", "truncate", "drop table"],
    },
    "T1499": {
        "name": "Endpoint Denial of Service",
        "tactic": "Impact",
        "description": "Adversaries may perform DoS attacks to degrade service availability.",
        "keywords": ["dos", "denial of service", "flood", "overload"],
    },
    # ── Defense Evasion ───────────────────────────────────────────────────
    "T1027": {
        "name": "Obfuscated Files or Information",
        "tactic": "Defense Evasion",
        "description": "Adversaries may use obfuscation to make payloads harder to detect.",
        "keywords": ["obfuscation", "encode", "base64", "encrypt payload"],
    },
    "T1562": {
        "name": "Impair Defenses",
        "tactic": "Defense Evasion",
        "description": "Adversaries may maliciously modify components of a victim's environment.",
        "keywords": ["disable logging", "disable firewall", "evade detection"],
    },
    # ── ATLAS: AI-Specific Techniques ─────────────────────────────────────
    "AML.T0051": {
        "name": "LLM Prompt Injection",
        "tactic": "ML Attack Staging",
        "description": "Adversary crafts prompts that override or subvert LLM system instructions.",
        "keywords": ["prompt injection", "jailbreak", "ignore previous instructions",
                     "system prompt override", "forget instructions"],
    },
    "AML.T0054": {
        "name": "LLM Jailbreak",
        "tactic": "ML Attack Staging",
        "description": "Adversary uses crafted inputs to bypass LLM safety filters.",
        "keywords": ["jailbreak", "dan", "do anything now", "bypass filter",
                     "roleplay as", "pretend you are"],
    },
    "AML.T0043": {
        "name": "Craft Adversarial Data",
        "tactic": "ML Attack Staging",
        "description": "Adversary creates adversarial examples to cause model misbehaviour.",
        "keywords": ["adversarial", "perturbation", "evasion attack", "model fooling"],
    },
    "AML.T0016": {
        "name": "Obtain Capabilities: ML Model",
        "tactic": "Resource Development",
        "description": "Adversary obtains ML models to use as components in their attack.",
        "keywords": ["model theft", "model stealing", "shadow model"],
    },
    "AML.T0040": {
        "name": "ML Model Inference API Access",
        "tactic": "Initial Access",
        "description": "Adversary gains access to a victim's ML model via inference API.",
        "keywords": ["api access", "inference api", "model api abuse"],
    },
    "AML.T0048": {
        "name": "Backdoor ML Model",
        "tactic": "Persistence",
        "description": "Adversary inserts backdoors into ML models to trigger specific behaviours.",
        "keywords": ["backdoor", "trojan model", "poisoning", "trigger"],
    },
    "AML.T0024": {
        "name": "Exfiltration via ML Inference API",
        "tactic": "Exfiltration",
        "description": "Adversary uses repeated model queries to reconstruct training data.",
        "keywords": ["model inversion", "training data extraction", "membership inference"],
    },
    "AML.T0047": {
        "name": "ML Supply Chain Compromise",
        "tactic": "Initial Access",
        "description": "Adversary compromises ML supply chain (datasets, frameworks, pre-trained models).",
        "keywords": ["supply chain", "poisoned dataset", "compromised weights"],
    },
}


# ---------------------------------------------------------------------------
# Tool: lookup_mitre_technique
# ---------------------------------------------------------------------------

def lookup_mitre_technique(technique_id: str) -> str:
    """
    Look up a MITRE ATT&CK or ATLAS technique by ID.

    Args:
        technique_id: Technique ID, e.g. 'T1059', 'AML.T0051'.

    Returns:
        JSON with technique details, or an error message if not found.
    """
    tid = technique_id.strip().upper()
    # Normalise ATLAS IDs: "aml.t0051" → "AML.T0051"
    entry = _TECHNIQUES.get(tid) or _TECHNIQUES.get(tid.replace("T", "T", 1))
    if not entry:
        return json.dumps({"error": f"Technique '{technique_id}' not found in catalogue",
                           "available_count": len(_TECHNIQUES)})
    return json.dumps({"id": tid, **entry})


# ---------------------------------------------------------------------------
# Tool: search_mitre_techniques
# ---------------------------------------------------------------------------

def search_mitre_techniques(query: str, max_results: int = 5) -> str:
    """
    Search MITRE ATT&CK / ATLAS techniques by keyword.

    Args:
        query: Free-text search string (matched against name, description, keywords).
        max_results: Maximum number of results to return (default 5).

    Returns:
        JSON list of matching techniques with id, name, tactic, and description.
    """
    q = query.lower()
    tokens = re.split(r"\s+", q)
    scored: list[tuple[int, str, dict]] = []

    for tid, entry in _TECHNIQUES.items():
        score = 0
        haystack = (
            entry["name"].lower() + " "
            + entry["description"].lower() + " "
            + " ".join(entry.get("keywords", []))
        )
        for token in tokens:
            if token in haystack:
                score += 1
            # Bonus for keyword-exact match
            if token in entry.get("keywords", []):
                score += 2
        if score > 0:
            scored.append((score, tid, entry))

    scored.sort(key=lambda x: -x[0])
    results = [
        {"id": tid, "name": e["name"], "tactic": e["tactic"],
         "description": e["description"], "score": s}
        for s, tid, e in scored[:max_results]
    ]
    return json.dumps({"query": query, "results": results, "total_matches": len(scored)})
