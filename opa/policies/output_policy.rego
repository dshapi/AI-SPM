package spm.output

import future.keywords.if

# Import egress-side schema-disclosure / system-prompt-leak guard.
# Lives in opa/policies/output_schema_guard.rego (package spm.output_schema_guard).
import data.spm.output_schema_guard

default allow := {"decision":"allow","reason":"output allowed"}

allow := {"decision":"block","reason":"secret or credential detected in output"} if {
    input.contains_secret == true
}
allow := {"decision":"block","reason":"LLM scan flagged high-risk content"} if {
    input.llm_verdict == "block"
}
allow := {"decision":"redact","reason":"PII detected — redacting before delivery"} if {
    input.contains_pii == true
    input.contains_secret == false
    input.llm_verdict != "block"
}

# ── Delegated sub-decision from Output-Schema-Guard ────────────────────────
# Catches tool / function schema disclosure and verbatim system-prompt leaks
# even if upstream guards missed them on the input side.
allow := {"decision":"block","reason":reason} if {
    output_schema_guard.allow.decision == "block"
    reason := sprintf("output-schema-guard: %s", [output_schema_guard.allow.reason])
}
