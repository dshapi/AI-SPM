package spm.memory

default allow := {"decision":"block","reason":"memory denied by default"}

has_scope(scope) if { input.auth_context.scopes[_] == scope }
has_signal(sig) if { input.signals[_] == sig }

allow := {"decision":"allow","reason":"session memory read permitted"} if {
    input.operation == "read"; input.namespace == "session"; has_scope("memory:read")
}
allow := {"decision":"allow","reason":"longterm memory read permitted"} if {
    input.operation == "read"; input.namespace == "longterm"; has_scope("memory:read:longterm")
}
allow := {"decision":"allow","reason":"system memory read permitted — admin only"} if {
    input.operation == "read"; input.namespace == "system"
    input.auth_context.roles[_] == "spm:admin"
}
allow := {"decision":"allow","reason":"session memory write permitted"} if {
    input.operation == "write"; input.namespace == "session"; has_scope("memory:write")
    input.posture_score < 0.35
    not has_signal("prompt_injection"); not has_signal("exfiltration"); not has_signal("indirect_injection")
}
allow := {"decision":"allow","reason":"longterm memory write permitted"} if {
    input.operation == "write"; input.namespace == "longterm"; has_scope("memory:write:longterm")
    input.posture_score < 0.20
    not has_signal("prompt_injection"); not has_signal("exfiltration"); not has_signal("indirect_injection")
}
allow := {"decision":"allow","reason":"session memory list permitted"} if {
    input.operation == "list"; input.namespace == "session"; has_scope("memory:read")
}
allow := {"decision":"allow","reason":"memory delete permitted"} if {
    input.operation == "delete"; has_scope("memory:delete"); input.posture_score < 0.50
}
