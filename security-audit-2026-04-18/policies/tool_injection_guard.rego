# Tool-Injection-Guard — detects structured tool-call shapes inside user prompt.
#
# New prompt-safety policy. Proposed package path: ai.security.tool_injection_guard
# Evaluation endpoint (suggested): /v1/data/ai/security/tool_injection_guard/allow
#
# Motivation: attackers paste out a full tool invocation inside their message
# hoping the model will treat it as a legitimate call. This policy detects
# the *shape* of such prompts, not just keywords.
#
# Three detection families:
#   (1) Tool-call JSON injection            — e.g. Call the "X" tool with: {...}
#   (2) Authority-token / system-channel    — e.g. admin_override:, [SYSTEM], <|system|>
#   (3) Policy-override flag                — e.g. "override_policy": true, bypass=true
#
package ai.security.tool_injection_guard

import future.keywords.if
import future.keywords.in

default allow := {"decision":"allow", "reason":"no tool-call injection detected", "action":"pass_through"}

# ── (1) Tool-call-in-prompt markers ──────────────────────────────────────────

_tool_call_markers := [
    "call the ",                 # "Call the \"file_reader\" tool with:"
    "invoke the tool",
    "use the tool",
    "run the tool",
    "execute the tool",
    "call the tool",
    ".tool(",                    # X.tool(
    "tool_call:",
    "tool_code:",
    "function_call:",
    "function.call(",
    "parameters:",               # in conjunction with other markers
]

# Shape heuristic: prompt contains a JSON-object literal with a path / query
# parameter — typical of pasted tool calls.
_json_path_shape if {
    contains(input.prompt, "\"path\"")
    contains(input.prompt, ":")
    contains(input.prompt, "{")
}
_json_query_shape if {
    contains(input.prompt, "\"query\"")
    contains(input.prompt, ":")
    contains(input.prompt, "{")
}
_json_url_shape if {
    contains(input.prompt, "\"url\"")
    contains(input.prompt, ":")
    contains(input.prompt, "{")
}

tool_call_detected if {
    some marker in _tool_call_markers
    contains(lower(input.prompt), marker)
}

tool_call_detected if { _json_path_shape  }
tool_call_detected if { _json_query_shape }
tool_call_detected if { _json_url_shape   }

# ── (2) Authority-token / system-channel spoofing ────────────────────────────

_authority_tokens := [
    "admin_override:",
    "admin_override ",
    "system_override:",
    "override_system:",
    "sudo_as:",
    "assume_role:",
    "role: system",
    "role:system",
    "[system]",
    "[admin]",
    "[root]",
    "<|system|>",
    "<|admin|>",
    "<system>",
    "<admin>",
    "## system",
    "##system",
    "### system",
    "### admin",
    "{{system}}",
    "{system}",
    "{admin}",
]

authority_spoof if {
    some token in _authority_tokens
    contains(lower(input.prompt), token)
}

# ── (3) Policy-override flags ───────────────────────────────────────────────

_override_flags := [
    "\"override_policy\": true",
    "\"override_policy\":true",
    "override_policy: true",
    "override_policy=true",
    "bypass_policy: true",
    "bypass_policy=true",
    "skip_safety: true",
    "skip_safety=true",
    "ignore_policy: true",
    "disable_safety: true",
    "policy_override\": \"true\"",
    "force_execute: true",
    "--force",
    "--no-safety",
]

override_flag_detected if {
    some flag in _override_flags
    contains(lower(input.prompt), flag)
}

# ── Sensitive-path references (complements Tool-Scope) ──────────────────────

_sensitive_paths := [
    "/internal/",
    "/secrets/",
    "/vault/",
    "/kube/",
    "/root/",
    "/var/lib/",
    "/etc/passwd",
    "/etc/shadow",
    "/etc/sudoers",
    "\\\\server\\",
    "c:\\windows\\system32",
]

sensitive_path_referenced if {
    some path in _sensitive_paths
    contains(lower(input.prompt), path)
}

# ── Block rules ─────────────────────────────────────────────────────────────

allow := {"decision":"block", "reason":"tool-call injection in user prompt",          "action":"deny_prompt"} if { tool_call_detected }
allow := {"decision":"block", "reason":"authority-token / system-channel spoof",      "action":"deny_prompt"} if { authority_spoof }
allow := {"decision":"block", "reason":"policy-override flag in user prompt",         "action":"deny_prompt"} if { override_flag_detected }
allow := {"decision":"block", "reason":"sensitive path reference in user prompt",     "action":"deny_prompt"} if { sensitive_path_referenced }
