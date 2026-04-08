package spm.output

import future.keywords.if

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
