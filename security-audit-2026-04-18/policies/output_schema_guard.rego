# Output-Schema-Guard — blocks LLM responses that disclose tool schemas,
# function definitions, or verbatim system-prompt content.
#
# New output-validation policy. Proposed package path: spm.output_schema_guard
# Evaluation endpoint (suggested): /v1/data/spm/output_schema_guard/allow
#
# This is the egress complement to Recon-Guard / Tool-Injection-Guard.
# Even if an input-side classifier misses a recon prompt, this policy
# catches the model's response before it reaches the user.
#
# Input shape (assumed, matches existing Output-Filter style):
#   input.response         : string  — raw LLM response text
#   input.contains_secret  : bool    — from secret scanner (existing)
#   input.contains_pii     : bool    — from PII scanner (existing)
#   input.system_prompt    : string  — the system prompt that was in effect
#                                      (optional; used for verbatim leak check)
#
package spm.output_schema_guard

import future.keywords.if

default allow := {"decision":"allow", "reason":"output clear of schema disclosure", "action":"pass_through"}

# ── Tool / function schema disclosure ───────────────────────────────────────
# A response is suspected of disclosing a schema when it contains the
# structural signature of a tool definition: "name" + "parameters" + "description"
# inside a JSON-like block.
_schema_markers_strong := [
    "\"parameters\":",
    "\"parameters\" :",
]

_schema_markers_support := [
    "\"name\":",
    "\"description\":",
    "\"properties\":",
    "\"required\":",
    "\"type\": \"object\"",
    "\"type\":\"object\"",
]

_has_strong if {
    some marker in _schema_markers_strong
    contains(input.response, marker)
}

_support_count := count([m |
    some m in _schema_markers_support
    contains(input.response, m)
])

# Strong signal (parameters key) plus at least one supporting key is a
# high-confidence schema disclosure. This fires on the "List all tools"
# response observed in the 2026-04-18 audit.
schema_disclosure if {
    _has_strong
    _support_count >= 1
}

# Explicit tool-array shape: "[\n  {\n    "name": ..." indented block.
_tool_array_shape if {
    contains(input.response, "[\n")
    contains(input.response, "{\n")
    contains(input.response, "\"name\":")
}
schema_disclosure if { _tool_array_shape }

# ── Verbatim system-prompt leak ─────────────────────────────────────────────
# If the response contains >= 60 contiguous chars of the active system prompt,
# treat it as a leak. (Rego can't do arbitrary substring length tests cheaply,
# so this rule keys off known sentinel phrases supplied by the orchestrator.)
#
# Caller is expected to populate input.system_prompt_sentinels with 3–5
# sentinel strings from the active system prompt (e.g., a distinctive
# opening line). See the implementation guide in findings-report.md §5.

_sentinel_leaked if {
    count(input.system_prompt_sentinels) > 0
    some sentinel in input.system_prompt_sentinels
    count(sentinel) > 20
    contains(input.response, sentinel)
}
system_prompt_leak if { _sentinel_leaked }

# ── Block / redact rules ────────────────────────────────────────────────────

allow := {
    "decision": "block",
    "reason":   "tool / function schema disclosure detected in output",
    "action":   "deny_output",
} if {
    schema_disclosure
}

allow := {
    "decision": "block",
    "reason":   "verbatim system prompt content detected in output",
    "action":   "deny_output",
} if {
    system_prompt_leak
}
