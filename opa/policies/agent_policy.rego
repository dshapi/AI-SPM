package spm.agent

default resolve_tool := {"tool_name": null, "intent": "general"}

has_scope(scope) if { input.auth_context.scopes[_] == scope }
has_signal(sig) if { input.signals[_] == sig }

_has_keyword(text, keywords) if {
    lower_text := lower(text); keyword := keywords[_]; contains(lower_text, keyword)
}

resolve_tool := {"tool_name":"calendar.read","intent":"read_calendar"} if {
    _has_keyword(input.prompt, ["calendar","schedule","meeting","appointment","event","today"])
    not _has_keyword(input.prompt, ["delete","cancel","remove","create","add"])
    has_scope("calendar:read")
    input.posture_score < 0.40
}
resolve_tool := {"tool_name":"calendar.write","intent":"write_calendar"} if {
    _has_keyword(input.prompt, ["schedule","create","add","book","set up"])
    _has_keyword(input.prompt, ["meeting","event","appointment","calendar"])
    has_scope("calendar:write")
    input.posture_score < 0.25
    not has_signal("prompt_injection")
}
resolve_tool := {"tool_name":"gmail.send_email","intent":"send_email"} if {
    _has_keyword(input.prompt, ["email","send","mail","compose","write to"])
    has_scope("gmail:send")
    input.posture_score < 0.25
    not has_signal("prompt_injection")
    not has_signal("indirect_injection")
    not has_signal("exfiltration")
}
resolve_tool := {"tool_name":"gmail.read","intent":"read_email"} if {
    _has_keyword(input.prompt, ["email","inbox","message","read mail","check mail"])
    not _has_keyword(input.prompt, ["send","compose","forward","reply to"])
    has_scope("gmail:read")
    input.posture_score < 0.40
}
resolve_tool := {"tool_name":"file.read","intent":"read_file"} if {
    _has_keyword(input.prompt, ["file","read file","open file","contents of","show file"])
    not has_signal("exfiltration")
    has_scope("file:read")
    input.posture_score < 0.35
}
resolve_tool := {"tool_name":"web.search","intent":"web_search"} if {
    _has_keyword(input.prompt, ["search","look up","find","what is","who is","latest"])
    not _has_keyword(input.prompt, ["credentials","password","secret","token","key"])
    input.posture_score < 0.50
}
resolve_tool := {"tool_name":"security.review","intent":"security_review"} if {
    input.posture_score >= 0.30
    input.posture_score < 0.70
}
