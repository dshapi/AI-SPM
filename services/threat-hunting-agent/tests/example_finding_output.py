"""
Example: what run_hunt() now returns given a realistic jailbreak batch.
Run with: python tests/example_finding_output.py
"""
import json
from unittest.mock import MagicMock
from agent.agent import run_hunt

_LLM_OUTPUT = '''
After analysing the 7-event batch I observed a clear jailbreak escalation pattern.

```json
{
  "title": "Repeated Jailbreak Pattern — dany.shapiro",
  "hypothesis": "User dany.shapiro submitted 7 jailbreak prompts within a 30-second window. All were blocked with risk_score=1.0. This is consistent with ATLAS AML.T0054 (Prompt Injection / Jailbreak).",
  "severity": "high",
  "asset": "chat-agent",
  "environment": "production",
  "evidence": [
    "7 sessions blocked, all with risk_score=1.0",
    "All events from principal dany.shapiro",
    "guard_verdict=block on all events",
    "policy_decision=block in all audit details"
  ],
  "triggered_policies": ["block_rule_v1.4.2"],
  "policy_signals": [
    {
      "type": "gap_detected",
      "policy": "jailbreak_rate_limit",
      "confidence": 0.75
    }
  ],
  "recommended_actions": ["block_session", "escalate"],
  "should_open_case": true
}
```
'''

events = [
    {
        "guard_verdict": "block", "risk_score": 1.0, "risk_tier": "critical",
        "principal": "dany.shapiro", "session_id": f"session-{i}",
        "details": {"policy_decision": "block", "risk_score": 1.0, "risk_tier": "critical"}
    }
    for i in range(7)
]

msg = MagicMock(); msg.content = _LLM_OUTPUT
agent = MagicMock(); agent.invoke.return_value = {"messages": [msg]}

finding = run_hunt(agent, "t1", events)
print(json.dumps(finding, indent=2))
