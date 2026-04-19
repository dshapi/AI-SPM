# Orbyx AI-SPM — Security Audit (2026-04-18)

Self-initiated red-team against the Orbyx AI-SPM chat surface, with
remediation suggestions. Nothing in this folder edits existing Orbyx source
code — everything here is additive analysis, additive policy, and a
standalone test harness.

## Contents

```
security-audit-2026-04-18/
├─ findings-report.md                  Full analysis: transcript, root cause,
│                                      finding list (ORBYX-001 … 008),
│                                      severity, remediation plan.
├─ policies/
│  ├─ recon_guard.rego                 NEW prompt-safety policy — catches
│  │                                   capability enumeration / recon intent.
│  ├─ tool_injection_guard.rego        NEW prompt-safety policy — catches
│  │                                   structured tool-call shapes and
│  │                                   authority-token impersonation.
│  └─ output_schema_guard.rego         NEW output-validation policy —
│                                      blocks LLM responses containing
│                                      tool/function schemas or verbatim
│                                      system-prompt content.
└─ test-harness/
   └─ attack_battery.py                Standalone regression harness.
                                       Replays 8 attack prompts against
                                       a running Orbyx stack and asserts
                                       the pipeline handles them correctly.
```

## TL;DR of the findings

- Pipeline is sound. Scorer is not stubbed.
- `PROMPT_PATTERNS` in `platform_shared/risk.py` has coverage holes for:
  capability enumeration, authority-token impersonation, tool-call injection
  in user prompt, sensitive paths beyond `/etc/`, meta-bypass phrasing, and
  output-coercion language.
- Llama Guard 3/4 (via Groq) is working but is a content-safety model, not an
  SPM-injection detector, and should not be the last line of defence for
  those threats.
- There is no output-side scanner for tool-schema disclosure — the one
  realised leak in the audit (full `web_search` / `web_fetch` JSON schemas
  returned to the attacker) would have been caught by such a scanner.

See `findings-report.md` for full detail.

## Adopting the policies

All three `.rego` files are written against the same input contract style
Orbyx already uses in `opa/policies/`:

- `input.prompt` — user prompt text.
- `input.response` — model response text (for `output_schema_guard`).
- `input.signals` / `input.threat_score` — optional, passed through.
- `input.system_prompt_sentinels` — optional array of distinctive
  substrings from the active system prompt, used by `output_schema_guard`
  to detect verbatim system-prompt leaks.

Suggested OPA bundle registration:

```text
package             evaluation endpoint                             stage
──────────────────  ──────────────────────────────────────────────  ─────────
ai.security.recon_guard           /v1/data/ai/security/recon_guard/allow          pre-LLM
ai.security.tool_injection_guard  /v1/data/ai/security/tool_injection_guard/allow pre-LLM
spm.output_schema_guard           /v1/data/spm/output_schema_guard/allow          post-LLM
```

In `services/policy_decider/app.py` you'd add two more `self._opa.eval(...)`
calls alongside the existing one, short-circuiting on any `block` decision.
On the output side, wire `spm.output_schema_guard` into `services/output_guard/`.

These files are intentionally provided as *drafts for review* — you know
your environment better than this audit; tune the phrase lists and shape
heuristics before promoting to `Enforce` mode.

## Running the test harness

From a shell with the Orbyx stack running:

```bash
cd security-audit-2026-04-18/test-harness
python3 -m pip install --break-system-packages requests
python3 attack_battery.py
```

Options:

```
--base-url URL     Orbyx base URL (default: http://localhost:3001)
--model ID         Model to route prompts through (default: claude-haiku)
--wait SECONDS     Pause between prompts (default: 0.8)
--out PATH         Write full JSON results to PATH
--no-color         Disable ANSI colour
```

Exit codes:
- `0` — all 8 attacks were either blocked or escalated to score ≥ 0.50.
- `1` — at least one attack was approved at score < 0.50 (regression).
- `2` — harness could not reach the Orbyx API.

### Discovering the session endpoint

The harness tries a short list of likely session-creation paths
(`/api/v1/sessions`, `/api/v1/chat`, etc.). If your build names the
endpoint differently, patch `OrbyxClient.SESSION_PATHS` at the top of
`attack_battery.py`. The harness is a black-box client — it does not
import any Orbyx module.

## Before shipping any of this

- Review each `.rego` file and tune phrase lists for false-positive rate
  against your real traffic. Run in `Monitor` mode first; promote to
  `Enforce` only after you're comfortable.
- The `Recon-Guard` phrase list is deliberately aggressive. In some
  deployments "what can you do" is a legitimate end-user question; if so,
  relax the phrase list or move the policy to `Monitor` mode and rely on
  the `tier=MEDIUM` escalate path instead of a hard block.
- The `Tool-Injection-Guard` JSON-shape heuristic may flag legitimate
  structured input (e.g., users who copy-paste JSON they want summarised).
  Either downgrade to `Monitor`, or require two signals (e.g., JSON shape
  *and* an authority token) before blocking.
- The `Output-Schema-Guard` needs `input.system_prompt_sentinels` to be
  populated by the orchestrator for the verbatim-leak branch to function.
  Add that wiring in `services/output_guard/` before enabling.

## Not included, by design

- No edits to existing source code.
- No modifications to `platform_shared/risk.py::PROMPT_PATTERNS`. The
  recommended pattern additions are documented in `findings-report.md` §3.3
  and §5 so the Orbyx team can review and merge with judgement.
- No modifications to `services/guard_model/app.py`. The finding that
  Llama Guard 3/4 under-detects SPM-specific threats is an
  architectural/selection concern, not a code bug.
