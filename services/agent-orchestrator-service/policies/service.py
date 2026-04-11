"""
policies/service.py
────────────────────
Business logic for policy validation and simulation.
Both are stateless — they only inspect policy data and the provided input dict.
No external calls; fully deterministic.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .models import SimulateResponse, ValidateResponse


# ── Validate ──────────────────────────────────────────────────────────────────

def validate_policy(policy: dict) -> ValidateResponse:
    """
    Lightweight static analysis of a policy's logic code.
    Rego: checks for required package declaration, default rule, balanced braces.
    JSON: checks parseable JSON + required keys.
    """
    pid = policy["id"]
    code: str = policy.get("logic_code", "")
    lang: str = policy.get("logic_language", "rego")
    errors: list[str] = []
    warnings: list[str] = []

    if not code.strip():
        errors.append("Logic code is empty.")
        return ValidateResponse(policy_id=pid, valid=False, errors=errors, warnings=warnings, line_count=0)

    lines = code.splitlines()
    line_count = len(lines)

    if lang == "json":
        try:
            data = json.loads(code)
        except json.JSONDecodeError as e:
            errors.append(f"JSON parse error: {e}")
            return ValidateResponse(policy_id=pid, valid=False, errors=errors, warnings=warnings, line_count=line_count)
        # Required top-level keys
        for key in ("policy", "rules"):
            if key not in data:
                warnings.append(f'Missing recommended key "{key}".')
        if "thresholds" not in data:
            warnings.append('No "thresholds" key — consider documenting numeric thresholds.')
    else:
        # Rego checks
        if not re.search(r"^package\s+\S+", code, re.MULTILINE):
            errors.append("Missing `package` declaration.")
        if not re.search(r"^default\s+\S+\s*:=", code, re.MULTILINE):
            warnings.append("No `default` rule found — policy is deny-by-default without explicit fallback.")
        # Balanced braces
        open_braces = code.count("{")
        close_braces = code.count("}")
        if open_braces != close_braces:
            errors.append(f"Unbalanced braces: {open_braces} `{{` vs {close_braces} `}}`.")
        # Duplicate rule names
        rule_names = re.findall(r"^(\w+)\s*:=\s*\{", code, re.MULTILINE)
        seen: set[str] = set()
        for rn in rule_names:
            if rn in seen and rn not in ("_", "allow", "deny"):
                warnings.append(f"Duplicate rule name `{rn}` — may cause OPA conflict errors.")
            seen.add(rn)

    valid = len(errors) == 0
    return ValidateResponse(
        policy_id=pid,
        valid=valid,
        errors=errors,
        warnings=warnings,
        line_count=line_count,
    )


# ── Simulate ──────────────────────────────────────────────────────────────────

_SIGNAL_BLOCKERS = {
    "exfiltration",
    "privilege_escalation",
    "tool_abuse",
    "prompt_injection",
    "indirect_injection",
}

_JAILBREAK_PATTERNS = [
    "ignore all previous",
    "forget your instructions",
    "you are now",
    "developer mode",
    "jailbreak",
    "bypass safety",
    "act as if you have no restrictions",
    "disregard your system prompt",
    "dan mode",
]


def simulate_policy(policy: dict, inp: dict[str, Any]) -> SimulateResponse:
    """
    Run a deterministic simulation of a policy against a sample input.
    Reads the policy type and mode; applies type-specific logic inline.
    """
    pid  = policy["id"]
    name = policy["name"]
    ptype = policy.get("type", "")
    mode  = policy.get("mode", "Monitor").lower()

    # In Monitor mode → never actually blocks, just flags
    def _decision(d: str, reason: str, rule: str) -> SimulateResponse:
        if mode in ("monitor", "disabled") and d == "block":
            d = "flag"
            reason = f"[Monitor mode — would block] {reason}"
        return SimulateResponse(
            policy_id=pid,
            policy_name=name,
            decision=d,
            reason=reason,
            matched_rule=rule,
            details={"input": inp, "mode": mode, "policy_type": ptype},
        )

    prompt: str   = str(inp.get("prompt", ""))
    posture: float = float(inp.get("posture_score", 0.0))
    signals: list  = list(inp.get("signals", []))
    guard_verdict  = inp.get("guard_verdict", "allow")

    # ── prompt-safety (Prompt-Guard, Jailbreak-Detect) ────────────────────────
    if ptype == "prompt-safety":
        prompt_lower = prompt.lower()
        for pat in _JAILBREAK_PATTERNS:
            if pat in prompt_lower:
                return _decision("block", f"Jailbreak pattern matched: \"{pat}\"", "injection_detected")
        threat_score = float(inp.get("threat_score", 0.0))
        if threat_score > 0.85:
            return _decision("block", f"Threat score {threat_score:.2f} exceeds threshold 0.85", "jailbreak_pattern_matched")
        if guard_verdict == "block":
            return _decision("block", "Guard model explicit block", "guard_verdict_block")
        return _decision("allow", "No adversarial patterns detected.", None)

    # ── tool-access (Tool-Scope, Write-Approval) ──────────────────────────────
    if ptype == "tool-access":
        blocking_signals = [s for s in signals if s in _SIGNAL_BLOCKERS]
        if blocking_signals:
            return _decision("block", f"Signal(s) detected: {', '.join(blocking_signals)}", "signal_block")
        if posture >= 0.60:
            return _decision("block", f"Posture {posture:.2f} ≥ 0.60 — all write ops suspended", "block_write_critical_posture")
        tool_name = inp.get("tool_name", "")
        tool_category = inp.get("tool_category", "")
        if posture >= 0.20 and tool_category == "write":
            return _decision("flag", f"Write tool '{tool_name}' requires approval at posture {posture:.2f}", "require_approval_high_posture")
        return _decision("allow", "Tool access permitted within scope and posture thresholds.", None)

    # ── privacy / output-validation (PII-Mask, Output-Filter) ────────────────
    if ptype in ("privacy", "output-validation"):
        if inp.get("contains_secret"):
            return _decision("block", "Credential or secret detected in output.", "secret_detected")
        if guard_verdict == "block" or inp.get("llm_verdict") == "block":
            return _decision("block", "LLM scan flagged high-risk content.", "llm_verdict_block")
        if inp.get("contains_pii"):
            return _decision("redact", "PII detected — redacting before delivery.", "pii_detected")
        return _decision("allow", "Output passed all content checks.", None)

    # ── data-access (Egress-Control, RAG-Retrieval-Limit) ────────────────────
    if ptype == "data-access":
        if policy["name"] == "RAG-Retrieval-Limit":
            if posture >= 0.70:
                return _decision("block", f"Critical posture {posture:.2f} ≥ 0.70 — RAG suspended.", "block_rag_critical")
            if posture >= 0.40:
                return _decision("flag", f"Posture {posture:.2f} ≥ 0.40 — reduced to 3 chunks.", "rag_reduced_window")
            ns = inp.get("namespace", "")
            if ns in ("credentials", "secrets", "pki", "hr_records"):
                scopes = inp.get("auth_context", {}).get("scopes", [])
                if "rag:sensitive" not in scopes:
                    return _decision("block", f"Namespace '{ns}' requires rag:sensitive scope.", "sensitive_namespace_block")
        else:
            # Egress-Control
            destination = inp.get("destination", "")
            if any(bad in destination for bad in ("pastebin.com", "requestbin", "ngrok")):
                return _decision("block", f"Destination '{destination}' is a known exfil channel.", "block_exfil_domain")
            ALLOWLIST = ["orbyx.internal", "api.tavily.com", "api.anthropic.com"]
            if destination and not any(a in destination for a in ALLOWLIST):
                return _decision("block", f"Destination '{destination}' not in egress allowlist.", "deny_all_by_default")
        return _decision("allow", "Request within permitted parameters.", None)

    # ── rate-limit (Token-Budget) ─────────────────────────────────────────────
    if ptype == "rate-limit":
        tokens_used = int(inp.get("tokens_used", 0))
        session_cap = 8192
        daily_cap   = 2_000_000
        if tokens_used >= session_cap:
            return _decision("block", f"Session token budget exhausted ({tokens_used} / {session_cap}).", "session_cap")
        daily_used = int(inp.get("daily_tokens_used", 0))
        if daily_used >= daily_cap:
            return _decision("block", f"Daily tenant token budget reached ({daily_used:,} / {daily_cap:,}).", "daily_tenant_cap")
        if tokens_used >= int(session_cap * 0.80):
            return _decision("flag", f"Approaching session cap: {tokens_used} / {session_cap} tokens used.", "warn_at_80_pct")
        return _decision("allow", f"Within token budget ({tokens_used} / {session_cap} session tokens used).", None)

    # ── fallback ──────────────────────────────────────────────────────────────
    return SimulateResponse(
        policy_id=pid,
        policy_name=name,
        decision="allow",
        reason="Policy type not evaluated — no matching simulation logic.",
        matched_rule=None,
        details={"input": inp},
    )
