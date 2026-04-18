"""
platform_shared/policy_explainer.py
─────────────────────────────────────
Deterministic, template-based policy explanation generator.

PolicyExplainer.explain() accepts a raw block-event dict and returns a
structured explanation dict:
  {
    policy_id:   str,
    decision:    "deny" | "allow",
    explanation: {
      title:            str,
      reason:           str,
      matched_signal:   str,
      risk_level:       "low" | "medium" | "high" | "critical",
      impact:           str,
      technical_details: { blocked_by, categories, rule, policy_id }
    }
  }

NO LLM calls. NO external I/O. Fully deterministic.
"""
from __future__ import annotations

from typing import Any


# ── Explanation template registry ─────────────────────────────────────────────
POLICY_EXPLANATIONS: dict[str, dict[str, str]] = {

    # ── OPA policy file IDs ───────────────────────────────────────────────────
    "prompt_injection.rego": {
        "title":           "Prompt Injection Attempt Detected",
        "reason_template": "The input contains a pattern attempting to override system instructions.",
        "risk_level":      "high",
        "impact":          "Prevents instruction hijacking and unauthorized control.",
    },
    "data_exfiltration.rego": {
        "title":           "Sensitive Data Access Attempt",
        "reason_template": "The request attempted to retrieve protected or sensitive data.",
        "risk_level":      "critical",
        "impact":          "Prevents leakage of internal or private data.",
    },
    "tool_access.rego": {
        "title":           "Unauthorized Tool Usage Blocked",
        "reason_template": "A tool was invoked without proper authorization scope.",
        "risk_level":      "high",
        "impact":          "Prevents misuse of internal system capabilities.",
    },

    # ── Lexical pattern categories ────────────────────────────────────────────
    "prompt_injection": {
        "title":           "Prompt Injection Attempt Detected",
        "reason_template": "The input contains a known instruction override pattern.",
        "risk_level":      "high",
        "impact":          "Prevents unauthorized override of system behavior.",
    },
    "tool_abuse": {
        "title":           "Tool Abuse Pattern Detected",
        "reason_template": "The input attempted to enumerate or misuse available tools.",
        "risk_level":      "high",
        "impact":          "Prevents unauthorized reconnaissance of system capabilities.",
    },
    "detection_suppression": {
        "title":           "Detection Suppression Attempt Blocked",
        "reason_template": "The input attempted to suppress or bypass security monitoring.",
        "risk_level":      "high",
        "impact":          "Preserves integrity of security controls.",
    },
    "capability_enumeration": {
        "title":           "Capability Enumeration Blocked",
        "reason_template": "The input attempted to map or list system capabilities.",
        "risk_level":      "medium",
        "impact":          "Prevents attacker reconnaissance of the system surface.",
    },
    "code_abuse": {
        "title":           "Potentially Destructive Code Blocked",
        "reason_template": "The input contains patterns associated with destructive code execution.",
        "risk_level":      "high",
        "impact":          "Prevents execution of harmful system commands.",
    },
    "pii_extraction": {
        "title":           "PII Extraction Attempt Blocked",
        "reason_template": "The input attempted to extract personally identifiable information.",
        "risk_level":      "high",
        "impact":          "Protects user privacy and prevents data exfiltration.",
    },
    "output_manipulation": {
        "title":           "Output Manipulation Attempt Blocked",
        "reason_template": "The input attempted to manipulate model output formatting or content.",
        "risk_level":      "medium",
        "impact":          "Preserves integrity of model responses.",
    },

    # ── Llama Guard S1–S15 ────────────────────────────────────────────────────
    "S1": {
        "title":           "Violent Content Blocked",
        "reason_template": "The input involves violent or harmful activity.",
        "risk_level":      "high",
        "impact":          "Prevents generation of content that could facilitate harm.",
    },
    "S2": {
        "title":           "Chemical Weapon Content Blocked",
        "reason_template": "The input involves chemical weapons or substances capable of causing serious harm.",
        "risk_level":      "critical",
        "impact":          "Prevents dissemination of weapons-grade information.",
    },
    "S3": {
        "title":           "Biological Weapon Content Blocked",
        "reason_template": "The input involves biological weapons or dangerous pathogens.",
        "risk_level":      "critical",
        "impact":          "Prevents dangerous pathogen or bioweapon information from being produced.",
    },
    "S4": {
        "title":           "Radiological/Nuclear Content Blocked",
        "reason_template": "The input involves radiological or nuclear weapons capable of mass harm.",
        "risk_level":      "critical",
        "impact":          "Prevents nuclear weapons information from being shared.",
    },
    "S5": {
        "title":           "WMD Content Blocked",
        "reason_template": "The input involves weapons capable of mass destruction.",
        "risk_level":      "critical",
        "impact":          "Prevents mass-casualty weapon information from being produced.",
    },
    "S6": {
        "title":           "Regulated Professional Advice Blocked",
        "reason_template": "The request asks for specialized medical, legal, or professional advice.",
        "risk_level":      "medium",
        "impact":          "Prevents unqualified advice that could cause harm.",
    },
    "S7": {
        "title":           "Financial Fraud or Illegal Activity Blocked",
        "reason_template": "The input involves fraud, illegal financial activity, or harmful illegal conduct.",
        "risk_level":      "high",
        "impact":          "Prevents facilitation of financial crime.",
    },
    "S8": {
        "title":           "Child Safety Violation Blocked",
        "reason_template": "The input involves content targeting or depicting minors in a harmful way.",
        "risk_level":      "critical",
        "impact":          "Protects minors from harmful content.",
    },
    "S9": {
        "title":           "Weapons Content Blocked",
        "reason_template": "The input involves weapons or materials capable of causing mass harm.",
        "risk_level":      "high",
        "impact":          "Prevents dissemination of dangerous weapons information.",
    },
    "S10": {
        "title":           "Hate Speech Blocked",
        "reason_template": "The input includes hateful or abusive content targeting protected groups.",
        "risk_level":      "high",
        "impact":          "Prevents generation of discriminatory or hateful material.",
    },
    "S11": {
        "title":           "Self-Harm Content Blocked",
        "reason_template": "The input involves self-harm content.",
        "risk_level":      "high",
        "impact":          "Protects users from content that could encourage self-harm.",
    },
    "S12": {
        "title":           "Explicit Adult Content Blocked",
        "reason_template": "The input involves explicit sexual adult content.",
        "risk_level":      "medium",
        "impact":          "Enforces platform content policy on adult material.",
    },
    "S13": {
        "title":           "Privacy Violation Blocked",
        "reason_template": "The input involves tracking, stalking, or privacy-violating activity.",
        "risk_level":      "high",
        "impact":          "Prevents privacy violations and unauthorised surveillance.",
    },
    "S14": {
        "title":           "Destructive Code Blocked",
        "reason_template": "The input involves potentially destructive code or system commands.",
        "risk_level":      "high",
        "impact":          "Prevents execution of harmful system-level operations.",
    },
    "S15": {
        "title":           "Prompt Injection Attempt Detected",
        "reason_template": "The input attempts to override system safety instructions.",
        "risk_level":      "high",
        "impact":          "Prevents unauthorized control of model behaviour.",
    },
}

# Fallback used when no category or policy ID matches
_FALLBACK: dict[str, str] = {
    "title":           "Request Blocked by Security Policy",
    "reason_template": "The input triggered one or more security policy rules.",
    "risk_level":      "medium",
    "impact":          "Prevents potentially unsafe requests from being processed.",
}

_VALID_RISK_LEVELS = {"low", "medium", "high", "critical"}


class PolicyExplainer:
    """
    Deterministic, template-based policy explanation generator.

    Usage::

        explainer = PolicyExplainer()
        result = explainer.explain({
            "categories":     ["S15"],
            "blocked_by":     "guard",
            "reason":         "prompt injection",
            "input_fragment": "ignore all previous instructions",
            "decision":       "deny",
        })
    """

    def explain(self, policy_event: dict[str, Any]) -> dict[str, Any]:
        """
        Produce a structured explanation from a raw policy block event.

        Returns
        -------
        dict with keys: policy_id, decision, explanation
        """
        categories:     list[str]      = policy_event.get("categories") or []
        blocked_by:     str | None     = policy_event.get("blocked_by")
        policy_id:      str            = policy_event.get("policy_id") or ""
        rule:           str            = policy_event.get("rule") or ""
        input_fragment: str            = policy_event.get("input_fragment") or ""
        decision:       str            = policy_event.get("decision") or "deny"

        template = self._resolve_template(policy_id, rule, categories, blocked_by)

        explanation = {
            "title":          template["title"],
            "reason":         template["reason_template"],
            "matched_signal": input_fragment[:200],
            "risk_level":     self._normalize_risk(template.get("risk_level", "medium")),
            "impact":         template["impact"],
            "technical_details": {
                "blocked_by": blocked_by or "unknown",
                "categories": categories,
                "rule":       rule or None,
                "policy_id":  policy_id or None,
            },
        }

        return {
            "policy_id":   policy_id or None,
            "decision":    decision,
            "explanation": explanation,
        }

    def _resolve_template(
        self,
        policy_id: str,
        rule: str,
        categories: list[str],
        blocked_by: str | None,
    ) -> dict[str, str]:
        """Return the best-matching template, falling back to _FALLBACK."""

        # 1. Exact OPA policy ID match
        if policy_id and policy_id in POLICY_EXPLANATIONS:
            return POLICY_EXPLANATIONS[policy_id]

        # 2. First recognized category
        for cat in categories:
            if cat in POLICY_EXPLANATIONS:
                return POLICY_EXPLANATIONS[cat]

        # 3. Blocked-by source type
        _SOURCE_FALLBACKS = {
            "lexical": POLICY_EXPLANATIONS.get("prompt_injection", _FALLBACK),
            "guard":   _FALLBACK,
            "opa":     POLICY_EXPLANATIONS.get("prompt_injection.rego", _FALLBACK),
        }
        if blocked_by and blocked_by in _SOURCE_FALLBACKS:
            return _SOURCE_FALLBACKS[blocked_by]

        return _FALLBACK

    @staticmethod
    def _normalize_risk(level: str) -> str:
        normalized = level.lower().strip()
        return normalized if normalized in _VALID_RISK_LEVELS else "medium"
