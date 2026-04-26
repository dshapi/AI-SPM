package ai.privacy.pii_mask

import future.keywords.if
import future.keywords.in

default allow := {"decision":"allow","action":"pass_through"}

# Secret detected — block entirely
allow := {"decision":"block","action":"deny_output","reason":"Credential or secret detected"} if {
    input.contains_secret == true
}

# LLM scan flagged high-risk content
allow := {"decision":"block","action":"deny_output","reason":"LLM scan flagged high-risk content"} if {
    input.llm_verdict == "block"
}

# PII detected in output — redact before delivery
allow := {"decision":"redact","action":"mask_pii","reason":"PII detected in response"} if {
    input.contains_pii == true
    input.contains_secret == false
    input.llm_verdict != "block"
}

# High-risk field types — always redact regardless of other signals
_pii_fields := {"ssn", "credit_card", "passport", "dob", "phone", "email"}

allow := {"decision":"redact","action":"mask_field","reason":"High-risk PII field detected"} if {
    some field in input.fields
    field in _pii_fields
}
