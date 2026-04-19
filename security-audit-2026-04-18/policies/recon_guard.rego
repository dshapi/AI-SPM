# Recon-Guard — detects capability-enumeration / reconnaissance intent.
#
# New prompt-safety policy. Proposed package path: ai.security.recon_guard
# Evaluation endpoint (suggested): /v1/data/ai/security/recon_guard/allow
#
# Input shape (same style as existing Prompt-Guard):
#   input.prompt          : string  — user prompt (already lowercased upstream)
#   input.signals         : array   — signal labels from platform_shared.risk
#   input.tokens          : array   — optional tokenised prompt
#   input.threat_score    : number  — guard model score 0..1 (if available)
#
# Decision object:
#   {"decision":"allow"|"block", "reason":"...", "action":"..."}
#
# Default block-on-match; allow only when no recon indicator is present.
#
package ai.security.recon_guard

import future.keywords.if
import future.keywords.in

default allow := {"decision":"allow", "reason":"no recon intent detected", "action":"pass_through"}

# ── Recon phrase list ────────────────────────────────────────────────────────
# These are intent markers for capability enumeration. A single match is
# sufficient to block because recon has no legitimate end-user rationale
# inside a production AI-SPM chat surface.
_recon_phrases := [
    # Tool / function inventory
    "list all tools",
    "list your tools",
    "list the tools",
    "what tools do you have",
    "what tools are available",
    "which tools can you",
    "available to you",
    "show your functions",
    "show me your functions",
    "list your functions",
    "list your capabilities",
    "enumerate your",
    "in json format",
    "as json",
    "output as json",
    "return json",

    # System prompt / instruction disclosure
    "your system prompt",
    "the system prompt",
    "reveal system prompt",
    "print system prompt",
    "show system prompt",
    "dump your prompt",
    "leak your prompt",
    "reveal your instructions",
    "show your instructions",
    "print your instructions",

    # Model / backend disclosure
    "what model are you",
    "which model",
    "your backend",
    "your architecture",
    "your training data",
]

# ── Detection ────────────────────────────────────────────────────────────────

recon_detected if {
    some phrase in _recon_phrases
    contains(lower(input.prompt), phrase)
}

# Dual-trigger: a tool-call request paired with reconnaissance framing.
# This catches "list all tools … then select one that retrieves memory".
recon_pivot if {
    recon_detected
    some verb in ["select", "choose", "pick", "invoke", "call", "execute"]
    contains(lower(input.prompt), verb)
}

# ── Block rules ──────────────────────────────────────────────────────────────

allow := {"decision":"block", "reason":"capability enumeration / recon intent", "action":"deny_prompt"} if {
    recon_detected
}

allow := {"decision":"block", "reason":"recon + tool-selection pivot", "action":"deny_prompt"} if {
    recon_pivot
}
