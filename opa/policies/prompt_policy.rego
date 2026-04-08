package spm.prompt

import future.keywords.if
import future.keywords.in

default allow := {"decision":"block","reason":"default deny","action":"deny_execution"}

has_signal(sig) if { sig in input.signals }
has_behavioral(sig) if { sig in input.behavioral_signals }
has_ttp(ttp) if { ttp in input.cep_ttps }

allow := {"decision":"block","reason":"guard model explicit block","action":"deny_execution"} if {
    input.guard_verdict == "block"
}
allow := {"decision":"block","reason":"exfiltration signal","action":"deny_execution"} if {
    has_signal("exfiltration")
}
allow := {"decision":"block","reason":"tool abuse signal","action":"deny_execution"} if {
    has_signal("tool_abuse")
}
allow := {"decision":"block","reason":"privilege escalation signal","action":"deny_execution"} if {
    has_signal("privilege_escalation")
}
allow := {"decision":"block","reason":"behavioral chain with sustained volume","action":"deny_execution"} if {
    has_behavioral("burst_detected")
    has_behavioral("sustained_high_volume")
}
allow := {"decision":"block","reason":"high intent drift with injection signal","action":"deny_execution"} if {
    input.intent_drift >= 0.75
    has_signal("prompt_injection")
}
allow := {"decision":"block","reason":"critical MITRE ATLAS TTP detected","action":"deny_execution"} if {
    has_ttp("AML.T0051.000")
}
allow := {"decision":"block","reason":"low retrieval trust blocks execution","action":"deny_execution"} if {
    input.retrieval_trust < 0.35
    input.posture_score >= 0.30
}
allow := {"decision":"block","reason":"posture score exceeds block threshold","action":"deny_execution"} if {
    input.posture_score >= 0.70
}
allow := {"decision":"escalate","reason":"posture in review zone","action":"review_only"} if {
    input.posture_score >= 0.30
    input.posture_score < 0.70
    not has_signal("exfiltration")
    not has_signal("tool_abuse")
    not has_signal("privilege_escalation")
    not input.guard_verdict == "block"
}
allow := {"decision":"allow","reason":"low posture score","action":"allow_execution"} if {
    input.posture_score < 0.30
    not has_signal("exfiltration")
    not has_signal("tool_abuse")
    not has_signal("privilege_escalation")
    not input.guard_verdict == "block"
}
