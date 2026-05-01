package spm.tools

import future.keywords.if
import future.keywords.in

default allow := {"decision":"block","reason":"tool denied by default","action":"deny_tool_execution"}

has_scope(scope) if { scope in input.auth_context.scopes }
has_signal(sig) if { sig in input.signals }

# Global blocks
allow := {"decision":"block","reason":"exfiltration signal blocks all tools","action":"deny_tool_execution"} if {
    has_signal("exfiltration")
}
allow := {"decision":"block","reason":"high posture blocks side-effect tools","action":"deny_tool_execution"} if {
    input.posture_score >= 0.50
    input.tool_name != "security.review"
}
allow := {"decision":"block","reason":"injection signal blocks side-effect tools","action":"deny_tool_execution"} if {
    has_signal("prompt_injection")
    input.tool_name != "security.review"
    input.tool_name != "calendar.read"
    input.tool_name != "gmail.read"
}

# Read-only tools (no approval, scope required)
allow := {"decision":"allow","reason":"calendar read permitted","action":"allow_tool_execution"} if {
    input.tool_name == "calendar.read"
    has_scope("calendar:read")
    input.posture_score < 0.40
}
allow := {"decision":"allow","reason":"gmail read permitted","action":"allow_tool_execution"} if {
    input.tool_name == "gmail.read"
    has_scope("gmail:read")
    input.posture_score < 0.35
}
allow := {"decision":"allow","reason":"file read permitted","action":"allow_tool_execution"} if {
    input.tool_name == "file.read"
    has_scope("file:read")
    not has_signal("exfiltration")
    input.posture_score < 0.35
}
allow := {"decision":"allow","reason":"db query permitted","action":"allow_tool_execution"} if {
    input.tool_name == "db.query"
    has_scope("db:read")
    not has_signal("exfiltration")
    input.posture_score < 0.30
}
allow := {"decision":"allow","reason":"web search permitted","action":"allow_tool_execution"} if {
    input.tool_name == "web.search"
    input.posture_score < 0.50
}

# ── Production tool names (services/api/app.py:_TOOLS) ──────────────────────
# The /chat path exposes web_search and web_fetch (underscore form). Keep
# these rules in sync with the _TOOLS list in services/api/app.py and the
# _TEST_TOOLS list in services/garak/main.py — all three must agree on
# the canonical tool names.

allow := {"decision":"allow","reason":"web_search permitted","action":"allow_tool_execution"} if {
    input.tool_name == "web_search"
    not has_signal("prompt_injection")
    not has_signal("indirect_injection")
    not has_signal("exfiltration")
    input.posture_score < 0.50
}

allow := {"decision":"allow","reason":"web_fetch permitted","action":"allow_tool_execution"} if {
    input.tool_name == "web_fetch"
    not has_signal("prompt_injection")
    not has_signal("indirect_injection")
    not has_signal("exfiltration")
    input.posture_score < 0.50
}

# Side-effect tools (require low posture + explicit scope + no injection)
allow := {"decision":"allow","reason":"gmail send permitted","action":"allow_tool_execution"} if {
    input.tool_name == "gmail.send_email"
    has_scope("gmail:send")
    input.posture_score < 0.25
    not has_signal("prompt_injection")
    not has_signal("indirect_injection")
    not has_signal("exfiltration")
}
allow := {"decision":"allow","reason":"calendar write permitted","action":"allow_tool_execution"} if {
    input.tool_name == "calendar.write"
    has_scope("calendar:write")
    input.posture_score < 0.25
    not has_signal("prompt_injection")
}
allow := {"decision":"allow","reason":"file write permitted","action":"allow_tool_execution"} if {
    input.tool_name == "file.write"
    has_scope("file:write")
    input.posture_score < 0.20
    not has_signal("prompt_injection")
    not has_signal("exfiltration")
}

# Security review: always permitted (no side effects)
allow := {"decision":"allow","reason":"security review always permitted","action":"allow_tool_execution"} if {
    input.tool_name == "security.review"
}
