package spm.prompt

import future.keywords.if
import future.keywords.in

# ── Imports from new input-side guards ─────────────────────────────────────
# These packages live in opa/policies/recon_guard.rego and
# opa/policies/tool_injection_guard.rego. They are loaded by OPA automatically
# and consulted here so spm.prompt.allow remains the single entrypoint that
# services/policy_decider/app.py queries via /v1/data/spm/prompt/allow.
import data.ai.security.recon_guard
import data.ai.security.tool_injection_guard

has_signal(sig) if { sig in input.signals }
has_behavioral(sig) if { sig in input.behavioral_signals }
has_scope(scope) if { scope in input.auth_context.scopes }
has_ttp(ttp) if { ttp in input.cep_ttps }

# ── Single else-chained `allow` rule ─────────────────────────────────────────
# Priority order (most specific -> least specific). Using `else := ... if`
# collapses what used to be ~10 competing complete-rule definitions into a
# single rule that produces exactly one output value. This fixes the latent
# OPA `eval_conflict_error` that would otherwise be raised whenever more than
# one block condition matched the same input (e.g. exfiltration signal +
# posture_score >= 0.70 at the same time).

allow := {
    "decision": "block",
    "reason":   "guard model explicit block",
    "action":   "deny_execution",
} if {
    input.guard_verdict == "block"
} else := {
    "decision": "block",
    "reason":   "critical MITRE ATLAS TTP detected",
    "action":   "deny_execution",
} if {
    has_ttp("AML.T0051.000")
} else := {
    "decision": "block",
    "reason":   sprintf("recon-guard: %s", [recon_guard.allow.reason]),
    "action":   "deny_execution",
} if {
    recon_guard.allow.decision == "block"
} else := {
    "decision": "block",
    "reason":   sprintf("tool-injection-guard: %s", [tool_injection_guard.allow.reason]),
    "action":   "deny_execution",
} if {
    tool_injection_guard.allow.decision == "block"
} else := {
    "decision": "block",
    "reason":   "exfiltration signal",
    "action":   "deny_execution",
} if {
    has_signal("exfiltration")
} else := {
    "decision": "block",
    "reason":   "tool abuse signal",
    "action":   "deny_execution",
} if {
    has_signal("tool_abuse")
} else := {
    "decision": "block",
    "reason":   "privilege escalation signal",
    "action":   "deny_execution",
} if {
    has_signal("privilege_escalation")
} else := {
    "decision": "block",
    "reason":   "high intent drift with injection signal",
    "action":   "deny_execution",
} if {
    input.intent_drift >= 0.75
    has_signal("prompt_injection")
} else := {
    # Encoded payload was decoded and re-screened by Llama Guard. The
    # guard cleared the inner content (or we wouldn't get here), but the
    # PRESENCE of obfuscation is itself a risk signal: legitimate users
    # rarely Base64-encode their prompts. We escalate to block when
    # combined with any non-trivial guard score, leaving short benign
    # decodes (like "Dogan") allowed since their score is ~0. Tenants
    # that need to allow Base64 traffic can grant the
    # `prompts:encoded_allowed` scope to bypass this rule.
    "decision": "block",
    "reason":   "obfuscation signal with elevated guard score",
    "action":   "deny_execution",
} if {
    has_signal("obfuscation")
    input.guard_score >= 0.30
    not has_scope("prompts:encoded_allowed")
} else := {
    "decision": "block",
    "reason":   "behavioral chain with sustained volume",
    "action":   "deny_execution",
} if {
    has_behavioral("burst_detected")
    has_behavioral("sustained_high_volume")
} else := {
    "decision": "block",
    "reason":   "low retrieval trust blocks execution",
    "action":   "deny_execution",
} if {
    input.retrieval_trust < 0.35
    input.posture_score >= 0.30
} else := {
    "decision": "block",
    "reason":   "posture score exceeds block threshold",
    "action":   "deny_execution",
} if {
    input.posture_score >= 0.70
} else := {
    "decision": "escalate",
    "reason":   "posture in review zone",
    "action":   "review_only",
} if {
    input.posture_score >= 0.30
    input.posture_score < 0.70
} else := {
    "decision": "allow",
    "reason":   "low posture score",
    "action":   "allow_execution",
} if {
    input.posture_score < 0.30
} else := {
    "decision": "block",
    "reason":   "default deny",
    "action":   "deny_execution",
}
