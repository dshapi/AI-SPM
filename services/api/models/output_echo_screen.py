"""
models/output_echo_screen.py
─────────────────────────────
Output-side defense against model prompt regurgitation.

Even when the input scanner (lexical → Llama Guard → OPA) lets a prompt
through, the model can still fail by emitting the adversarial prompt back
verbatim — a behaviour that:

  * surfaces the jailbreak persona / payload in downstream logs and
    consumers (the prompt is now in the assistant turn, where it
    propagates further than the user turn would);
  * indicates the model engaged with adversarial content rather than
    refusing, which is itself a defense miss regardless of whether the
    response carries through on the persona's intent;
  * is invisible to the existing output scanner, which checks for
    secrets / PII / OPA-redaction signals — none of which fire on a
    benign-looking persona handoff.

This module adds a third output-scan signal: response-vs-prompt overlap.
It is intentionally STRICTER than the runner-side
``services/garak/main._is_prompt_echo`` heuristic — that helper relabels
already-emitted findings, while this one runs INSIDE the request path
and can downgrade ``guard_verdict`` to "block" so the response is never
returned to the caller.

Public API:
    screen_output_echo(prompt, response) -> (blocked: bool, reason: Optional[str])
"""
from __future__ import annotations

import os
from typing import Optional, Tuple


# ── Tunable thresholds (env-overridable for ops without redeploy) ──────────

_MIN_DIRECT_CHARS  = int(os.environ.get("OUTPUT_ECHO_MIN_DIRECT_CHARS",  "8"))
_MIN_OVERLAP_CHARS = int(os.environ.get("OUTPUT_ECHO_MIN_OVERLAP_CHARS", "40"))


# ── Refusal short-circuit markers ───────────────────────────────────────────
#
# A response that begins with a refusal marker is, by definition, not a
# regurgitation — even if the response then quotes the prompt verbatim
# (the canonical "I won't say 'X' — that's hate speech" pattern).
# Lowercased substring match against the head of the cleaned response.

_REFUSAL_HEAD_MARKERS: tuple[str, ...] = (
    "i won't",
    "i will not",
    "i can't",
    "i cannot",
    "i'm not going to",
    "i am not going to",
    "i refuse",
    "i decline",
    "i'm unable",
    "i am unable",
    "i'm sorry, but",
    "i am sorry, but",
    "as an ai",
    "as a language model",
)


# ── Role markers ────────────────────────────────────────────────────────────
#
# When upstream serialises a multi-turn Conversation object to a flat
# string (services/garak/main.CPMPipelineGenerator._to_str), each turn is
# prefixed with the role in square brackets. A raw model response should
# never start with these markers — when it does, it's almost always
# because the model echoed a serialised prompt back into its output. We
# strip the prefixes before overlap matching so a "[user] PERSONA=Kira..."
# response is correctly recognised as a regurgitation of the underlying
# "PERSONA=Kira..." prompt.

_ROLE_MARKERS: tuple[str, ...] = ("[user]", "[assistant]", "[system]")


def screen_output_echo(prompt: str, response: str) -> Tuple[bool, Optional[str]]:
    """Screen *response* for substantial echo of *prompt*.

    Returns:
        (blocked, reason)
          - blocked == True when the response is judged a regurgitation
            of the prompt and should NOT be returned to the caller.
          - reason is a short, operator-readable string suitable for
            logging / Kafka enrichment / UI display. Never includes the
            raw matched substring, so an attacker cannot probe the
            threshold via response inspection.

    Heuristic:
      1. Strip leading role markers from the response.
      2. Bail (False) on responses below ``_MIN_DIRECT_CHARS`` — too
         short to classify reliably.
      3. Bail (False) when the response head contains a refusal marker
         — refuse-with-quote patterns are NOT regurgitation.
      4. Return True if the cleaned response is contained verbatim in
         the prompt OR if any contiguous ``_MIN_OVERLAP_CHARS``-long
         substring of the cleaned response appears verbatim in the
         prompt.
    """
    if not prompt or not response:
        return False, None

    cleaned = response.strip()

    # Strip stacked role markers from the start.
    while cleaned:
        prev = cleaned
        for marker in _ROLE_MARKERS:
            if cleaned.startswith(marker):
                cleaned = cleaned[len(marker):].lstrip()
                break
        if cleaned == prev:
            break

    if len(cleaned) < _MIN_DIRECT_CHARS:
        return False, None

    head = cleaned[:200].lower()
    if any(marker in head for marker in _REFUSAL_HEAD_MARKERS):
        return False, None

    cleaned_lower = cleaned.lower()
    prompt_lower  = prompt.lower()

    # Direct containment — short fragments (e.g. base64 echoes) and
    # full-prompt regurgitation both land here.
    if cleaned_lower in prompt_lower:
        return True, "output_echo_direct_containment"

    # Sliding-window — partial echoes longer than the window size.
    window = _MIN_OVERLAP_CHARS
    if window <= len(cleaned_lower):
        step = max(1, window // 2)
        for i in range(0, len(cleaned_lower) - window + 1, step):
            if cleaned_lower[i:i + window] in prompt_lower:
                return True, "output_echo_window_overlap"

    return False, None
