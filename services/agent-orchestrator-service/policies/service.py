"""
policies/service.py
────────────────────
Business logic for policy validation and simulation.

Validation: combination of (a) OPA /v1/policies authoritative compile
when OPA is reachable, and (b) regex-based static checks as a
fall-through when OPA is offline. Fully deterministic given the same
input + OPA reachability.

Simulation: stateless deterministic mock — inspects policy data and the
provided input dict, no external calls. Phase 3 will swap this for real
OPA /v1/data evaluation; for now the mock keeps the UI functional.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from .models import SimulateResponse, ValidateResponse


# ── Validate ──────────────────────────────────────────────────────────────────

_OPA_URL = os.environ.get("OPA_URL", "http://opa.aispm.svc.cluster.local:8181")
_OPA_TIMEOUT_S = float(os.environ.get("OPA_VALIDATE_TIMEOUT_S", "5.0"))


def _rewrite_package_for_temp_upload(code: str, sandbox_prefix: str) -> tuple[str, str | None]:
    """Rewrite a Rego module's ``package`` declaration so the temp
    upload doesn't collide with an already-loaded copy of the same
    package in OPA.

    Why: validate / simulate both upload the EDITED policy under a
    temporary OPA policy ID (e.g. ``_validate_a1b2c3d4``) so we can
    compile-check or evaluate it without touching the live runtime
    copy.  But OPA stores policies by ID *and* compiles the union of
    all uploaded modules — so two modules under different IDs that
    declare the same package + ``default allow := X`` rule collide
    with::

        rego_type_error: multiple default rules data.<pkg>.allow found

    Renaming our temp upload's package to ``<sandbox_prefix>.<orig_pkg>``
    isolates it cleanly: the temp upload lives at
    ``data._validate_<rand>.ai.security.jailbreak_detect``, the runtime
    copy stays at ``data.ai.security.jailbreak_detect``, no overlap, no
    collision.

    Returns ``(rewritten_code, original_pkg)``.  ``original_pkg`` is the
    pre-rewrite package path, which simulate uses to compute the data
    API URL.  Returns ``(code, None)`` unchanged if no package
    declaration is present.

    Cross-policy imports are left untouched: ``prompt_policy.rego``
    keeps its ``import data.ai.security.recon_guard`` so it can still
    pull from OTHER policies' runtime copies.  Only the module-defining
    ``package`` line is rewritten.
    """
    pat = re.compile(r"^(\s*package\s+)([A-Za-z_][\w.]*)\s*$", re.MULTILINE)
    m = pat.search(code or "")
    if not m:
        return code, None
    original_pkg = m.group(2)
    rewritten = pat.sub(
        f"\\1{sandbox_prefix}.{original_pkg}",
        code,
        count=1,
    )
    return rewritten, original_pkg


def _validate_rego_via_opa(code: str) -> tuple[list[str], list[str]]:
    """Send Rego source to OPA's /v1/policies API for real compile-time
    validation. Returns (errors, warnings) — empty lists when valid.

    Why call OPA instead of doing more regex: Rego is a non-trivial
    language with type inference, dataset references, regex patterns,
    function arity, and a real compiler. Regex-based checks miss
    everything except gross syntactic issues — they pass code that's
    obviously broken (mismatched parens inside string literals look
    "balanced", undefined references look fine, wrong rule heads pass
    silently). Operators editing a policy in the UI need real feedback
    about whether the policy actually compiles.

    OPA's PUT /v1/policies/{id} endpoint returns:
      - 200 OK with empty body on success
      - 400 with JSON body containing the parse/compile errors and their
        line numbers when the policy fails.

    We use a temporary policy ID prefixed with "_validate_" so this never
    collides with a real policy in the OPA instance, and we DELETE it
    immediately after the validation call so OPA doesn't accumulate
    abandoned validate-only policies over time.

    Network failure is non-fatal — falls back to regex checks. The UI
    sees "OPA unreachable" as a warning rather than a hard error so
    editing remains possible during cluster maintenance.
    """
    import httpx  # local import keeps the regex-only path dep-free

    tmp_id = f"_validate_{os.urandom(4).hex()}"
    url = f"{_OPA_URL}/v1/policies/{tmp_id}"
    errors: list[str] = []
    warnings: list[str] = []

    # Rewrite ``package`` so the temp upload doesn't collide with an
    # already-loaded copy of the same package in OPA. Without this,
    # validating jailbreak_policy.rego (which already lives under
    # data.ai.security.jailbreak_detect via the chart ConfigMap) fails
    # with ``multiple default rules ... allow found`` — see
    # _rewrite_package_for_temp_upload's docstring for details.
    rewritten_code, _orig_pkg = _rewrite_package_for_temp_upload(code, tmp_id)

    try:
        with httpx.Client(timeout=_OPA_TIMEOUT_S) as client:
            resp = client.put(
                url,
                content=rewritten_code,
                headers={"Content-Type": "text/plain"},
            )
            if resp.status_code == 200:
                # Success — clean up the validate-only policy.
                try:
                    client.delete(url)
                except Exception:
                    pass
                return errors, warnings

            # 400 / 5xx — extract the error payload.
            try:
                body = resp.json()
            except Exception:
                body = {}

            opa_errors = body.get("errors") or []
            for e in opa_errors:
                # OPA error shape: {"code", "message", "location": {"file","row","col"}}
                msg = e.get("message", "Rego compilation error")
                loc = e.get("location") or {}
                row = loc.get("row")
                col = loc.get("col")
                if row:
                    errors.append(f"line {row}:{col or 1}: {msg}")
                else:
                    errors.append(msg)
            if not opa_errors and body.get("message"):
                errors.append(body["message"])
            if not errors:
                errors.append(f"OPA validation failed (HTTP {resp.status_code}).")

            # Best-effort cleanup even on failure (OPA stores the failed
            # policy as "invalid" until DELETE).
            try:
                client.delete(url)
            except Exception:
                pass

    except Exception as exc:
        warnings.append(
            f"OPA unreachable ({exc.__class__.__name__}); falling back to "
            "regex-only validation. Re-validate after OPA is reachable."
        )
        # Caller falls back to the regex checks below.

    return errors, warnings


def validate_policy(policy: dict) -> ValidateResponse:
    """
    Validate a policy's logic code.

    For Rego policies:
      1. Send the code to OPA's PUT /v1/policies/{tmp_id} endpoint —
         returns real compile errors with line/column numbers.
      2. If OPA is reachable, OPA's verdict is authoritative.
      3. If OPA is unreachable (network blip, cluster maintenance),
         fall back to the legacy regex-based static checks so editing
         remains possible — surface the OPA-unreachable state as a
         warning so the operator knows to re-validate.

    For JSON policies: parse + check recommended keys (unchanged).
    """
    pid = policy["id"]
    code: str = policy.get("logic_code", "")
    lang: str = policy.get("logic_language", "rego")
    errors: list[str] = []
    warnings: list[str] = []

    if not code.strip():
        errors.append("Logic code is empty.")
        return ValidateResponse(policy_id=pid, valid=False, errors=errors, warnings=warnings, line_count=0)

    lines = code.splitlines()
    line_count = len(lines)

    if lang == "json":
        try:
            data = json.loads(code)
        except json.JSONDecodeError as e:
            errors.append(f"JSON parse error: {e}")
            return ValidateResponse(policy_id=pid, valid=False, errors=errors, warnings=warnings, line_count=line_count)
        # Required top-level keys
        for key in ("policy", "rules"):
            if key not in data:
                warnings.append(f'Missing recommended key "{key}".')
        if "thresholds" not in data:
            warnings.append('No "thresholds" key — consider documenting numeric thresholds.')
    else:
        # ── Real OPA compile via /v1/policies (authoritative when reachable).
        opa_errors, opa_warnings = _validate_rego_via_opa(code)
        errors.extend(opa_errors)
        warnings.extend(opa_warnings)

        # Fall through to the regex checks ONLY when OPA was unreachable
        # (signalled by the "OPA unreachable" warning) AND we have no
        # OPA-side errors yet. When OPA reached and rejected the code,
        # we trust its verdict and skip the regex layer to avoid
        # double-reporting the same syntax issue with two different
        # phrasings.
        opa_unreachable = any("OPA unreachable" in w for w in opa_warnings)
        if opa_unreachable:
            if not re.search(r"^package\s+\S+", code, re.MULTILINE):
                errors.append("Missing `package` declaration.")
            if not re.search(r"^default\s+\S+\s*:=", code, re.MULTILINE):
                warnings.append("No `default` rule found — policy is deny-by-default without explicit fallback.")
            open_braces = code.count("{")
            close_braces = code.count("}")
            if open_braces != close_braces:
                errors.append(f"Unbalanced braces: {open_braces} `{{` vs {close_braces} `}}`.")
            rule_names = re.findall(r"^(\w+)\s*:=\s*\{", code, re.MULTILINE)
            seen: set[str] = set()
            for rn in rule_names:
                if rn in seen and rn not in ("_", "allow", "deny"):
                    warnings.append(f"Duplicate rule name `{rn}` — may cause OPA conflict errors.")
                seen.add(rn)

    valid = len(errors) == 0
    return ValidateResponse(
        policy_id=pid,
        valid=valid,
        errors=errors,
        warnings=warnings,
        line_count=line_count,
    )


# ── Simulate ──────────────────────────────────────────────────────────────────

_SIGNAL_BLOCKERS = {
    "exfiltration",
    "privilege_escalation",
    "tool_abuse",
    "prompt_injection",
    "indirect_injection",
}

_JAILBREAK_PATTERNS = [
    "ignore all previous",
    "forget your instructions",
    "you are now",
    "developer mode",
    "jailbreak",
    "bypass safety",
    "act as if you have no restrictions",
    "disregard your system prompt",
    "dan mode",
]


# ── Real OPA simulate (Phase 3) ──────────────────────────────────────────────
#
# The mock path below was useful for Phase 1/2 demos but it has two problems
# operators feel as soon as they start editing real policies:
#
#   1. A policy edit doesn't change the simulator's behaviour. The mock
#      branches on policy.type and hardcoded patterns; the actual Rego the
#      operator just edited is ignored. Editing a regex in jailbreak_policy
#      and clicking Simulate gives the same "allow / block" verdict as
#      before the edit.
#   2. New policy types ship without simulator support. The mock has a
#      type-by-type if/elif tree; anything outside the known set falls
#      through to a generic "allow".
#
# Phase 3 fixes both by evaluating the live Rego against the input via
# OPA's data API:
#   * PUT /v1/policies/_simulate_<rand>      — upload the current logic_code
#   * POST /v1/data/<package>?input=...      — evaluate the package
#   * DELETE /v1/policies/_simulate_<rand>   — clean up
#
# OPA's verdict is taken at face value: any rule in the package that
# returns ``true`` (e.g. ``allow``, ``deny``, ``block``) is reported, and
# we pick the most authoritative one for the SimulateResponse.decision
# field. The full data-API result object is included in
# ``SimulateResponse.details`` so operators can see every rule's value
# without having to reason about which one is "the answer".

_PACKAGE_RE = re.compile(r"^package\s+([a-zA-Z0-9_.]+)", re.MULTILINE)


def _extract_package(rego_code: str) -> str | None:
    m = _PACKAGE_RE.search(rego_code or "")
    return m.group(1) if m else None


def _opa_simulate(policy: dict, inp: dict[str, Any]) -> SimulateResponse | None:
    """Evaluate the policy's Rego against ``inp`` via OPA's data API.

    Returns ``None`` when OPA is unreachable, the policy isn't Rego, or the
    Rego has no recoverable package — caller falls back to the mock path.

    Cleanup-on-failure: if OPA accepts the policy upload but the data
    query fails, we still DELETE the temporary policy so OPA doesn't
    accumulate orphaned ``_simulate_*`` entries. The cleanup is
    best-effort; a failure here logs but doesn't propagate.
    """
    code: str = policy.get("logic_code", "")
    if (policy.get("logic_language", "rego") != "rego") or not code.strip():
        return None
    pkg = _extract_package(code)
    if not pkg:
        return None

    import httpx
    tmp_id = f"_simulate_{os.urandom(4).hex()}"
    upload_url = f"{_OPA_URL}/v1/policies/{tmp_id}"

    # Rewrite the package on upload so we don't collide with the
    # runtime copy already loaded under the same package path. The
    # data-API URL has to use the rewritten path because we want to
    # evaluate the EDITED code, not the runtime copy — querying the
    # original package path would silently return the runtime copy's
    # rules and the operator would think their edits had no effect.
    rewritten_code, _orig_pkg = _rewrite_package_for_temp_upload(code, tmp_id)
    sandboxed_pkg = f"{tmp_id}.{pkg}"
    data_url      = f"{_OPA_URL}/v1/data/{sandboxed_pkg.replace('.', '/')}"

    try:
        with httpx.Client(timeout=_OPA_TIMEOUT_S) as client:
            up = client.put(upload_url, content=rewritten_code,
                            headers={"Content-Type": "text/plain"})
            if up.status_code != 200:
                # Compile failed — return a structured response so the UI shows
                # the operator that the policy itself is broken (rather than
                # silently falling through to the mock). The mock can't catch
                # this anyway because the mock doesn't compile.
                try:
                    body = up.json()
                except Exception:
                    body = {}
                errs = body.get("errors") or [{"message": f"HTTP {up.status_code}"}]
                msgs = "; ".join(e.get("message", "?") for e in errs[:3])
                return SimulateResponse(
                    policy_id=policy["id"],
                    policy_name=policy["name"],
                    decision="error",
                    reason=f"Rego compile failed: {msgs}",
                    matched_rule=None,
                    details={"opa_errors": errs, "package": pkg},
                )

            try:
                resp = client.post(data_url, json={"input": inp})
            finally:
                # Best-effort cleanup of the temp policy upload.
                try:
                    client.delete(upload_url)
                except Exception:
                    pass

            if resp.status_code != 200:
                return None  # caller falls back to mock
            payload = resp.json()
            result  = payload.get("result")

    except Exception:
        return None  # OPA unreachable, fall back to mock

    # Normalise the OPA result into a SimulateResponse.
    #
    # Rego packages typically expose a small set of decision rules. The
    # convention across our policies is one of:
    #
    #   * ``allow := <bool>``         — true means the request is allowed.
    #   * ``deny  := <bool>``         — true means the request is blocked.
    #   * ``block := <bool>`` / ``flag := <bool>`` (used by some output policies).
    #   * ``allow := {...}``          — object with ``decision``/``reason``
    #                                   keys (the spm.prompt.allow shape).
    #
    # Order of precedence below mirrors how the live pipeline reads the
    # verdict — explicit object first, then deny, then allow — so the
    # simulator's verdict matches what the runtime would do for the same
    # input.
    decision_text = "allow"
    reason        = "Rule chain fell through to default."
    matched_rule  = None

    if isinstance(result, dict):
        # spm.prompt.allow style — value is itself a dict.
        if isinstance(result.get("allow"), dict):
            obj = result["allow"]
            obj_decision = str(obj.get("decision", "allow")).lower()
            decision_text = "block" if obj_decision == "block" else \
                           ("flag"  if obj_decision in ("flag", "monitor") else "allow")
            reason       = obj.get("reason", "(no reason returned by policy)")
            matched_rule = "allow"
        elif result.get("deny") is True:
            decision_text = "block"
            reason        = "deny == true"
            matched_rule  = "deny"
        elif result.get("block") is True:
            decision_text = "block"
            reason        = "block == true"
            matched_rule  = "block"
        elif result.get("flag") is True:
            decision_text = "flag"
            reason        = "flag == true"
            matched_rule  = "flag"
        elif result.get("allow") is False:
            decision_text = "block"
            reason        = "allow == false (deny by default)"
            matched_rule  = "allow"
        elif result.get("allow") is True:
            decision_text = "allow"
            reason        = "allow == true"
            matched_rule  = "allow"

    # Honour Monitor-mode — surface as flag rather than block, matching the
    # runtime's behaviour for not-yet-enforced policies.
    mode = policy.get("mode", "Monitor").lower()
    if decision_text == "block" and mode in ("monitor", "disabled"):
        decision_text = "flag"
        reason        = f"[Monitor mode — would block] {reason}"

    return SimulateResponse(
        policy_id    = policy["id"],
        policy_name  = policy["name"],
        decision     = decision_text,
        reason       = reason,
        matched_rule = matched_rule,
        details      = {
            "input":           inp,
            "mode":            mode,
            "policy_type":     policy.get("type", ""),
            "opa_package":     pkg,
            "opa_result":      result,
            "evaluated_via":   "opa.data_api",
        },
    )


# Entrypoint that the runtime API queries when deciding whether to allow a
# prompt through.  Pipeline mode targets this URL so the simulator's verdict
# matches what the actual ``/internal/probe`` and ``/chat`` endpoints would
# issue for the same input.  Keep this in sync with
# ``services/policy_decider/app.py``.
_PIPELINE_ENTRYPOINT_PATH = "spm/prompt/allow"


def _opa_simulate_pipeline(policy: dict, inp: dict[str, Any]) -> SimulateResponse | None:
    """Evaluate the ``spm.prompt.allow`` entrypoint against ``inp`` using the
    policies CURRENTLY LOADED in OPA.

    This is the "what would the runtime do?" verdict.  It transitively
    includes every guard the entrypoint imports (``recon_guard``,
    ``tool_injection_guard``, etc.) and applies the priority-ordered
    else-chain in ``spm.prompt.allow``.

    Important caveat: this evaluates the DEPLOYED policies, not the edited
    code carried in ``policy['logic_code']``.  If the operator wants to see
    how their unsaved edits behave inside the full pipeline they must
    promote + activate the policy first.  The result's ``details.note``
    field surfaces this so the UI can display a hint next to the verdict.

    Returns ``None`` when OPA is unreachable or returns a non-200 — the
    caller falls back to single-policy mode (or the mock) so simulate
    never silently no-ops.
    """
    import httpx
    data_url = f"{_OPA_URL}/v1/data/{_PIPELINE_ENTRYPOINT_PATH}"

    try:
        with httpx.Client(timeout=_OPA_TIMEOUT_S) as client:
            resp = client.post(data_url, json={"input": inp})
            if resp.status_code != 200:
                return None
            payload = resp.json()
            result  = payload.get("result")
    except Exception:
        return None

    # ``spm.prompt.allow`` returns one of:
    #   { "decision": "block",    "reason": "...", "action": "deny_execution" }
    #   { "decision": "allow",    "reason": "...", "action": "allow_execution" }
    #   { "decision": "escalate", "reason": "...", "action": "review_only"     }
    if not isinstance(result, dict):
        return None

    obj_decision = str(result.get("decision", "allow")).lower()
    decision_text = (
        "block" if obj_decision == "block"
        else "flag" if obj_decision in ("flag", "monitor", "escalate")
        else "allow"
    )
    reason = result.get("reason", "(no reason returned by pipeline)")

    return SimulateResponse(
        policy_id    = policy["id"],
        policy_name  = policy["name"],
        decision     = decision_text,
        reason       = reason,
        matched_rule = "spm.prompt.allow",
        details      = {
            "input":         inp,
            "mode":          policy.get("mode", "Monitor").lower(),
            "policy_type":   policy.get("type", ""),
            "evaluated_via": "opa.pipeline_entrypoint",
            "entrypoint":    _PIPELINE_ENTRYPOINT_PATH,
            "opa_result":    result,
            "pipeline":      True,
            "note": (
                "Pipeline simulation evaluates the currently-deployed "
                "policies. Unsaved edits to this policy are NOT reflected — "
                "promote + activate to test edited Rego through the full "
                "pipeline."
            ),
        },
    )


def simulate_policy(
    policy: dict,
    inp: dict[str, Any],
    *,
    pipeline: bool = False,
) -> SimulateResponse:
    """
    Simulate a policy against a sample input.

    pipeline=False (default): evaluate THIS policy's Rego in isolation
    via OPA's data API.  Used for tuning a single rule — operators see
    their unsaved edits reflected in the verdict.

    pipeline=True: evaluate the full prompt-safety pipeline (the
    ``spm.prompt.allow`` entrypoint) against the input.  This is the
    verdict the actual runtime API would issue, transitively running the
    input-side guards (recon_guard, tool_injection_guard) before the
    main rule.  Recommended for users who want to know whether a sample
    input WOULD BE BLOCKED IN PROD, not whether one specific policy
    fires on it.

    Both paths fall through to a deterministic mock when OPA is
    unreachable, so the UI keeps working during cluster maintenance.
    """
    if pipeline:
        pipe = _opa_simulate_pipeline(policy, inp)
        if pipe is not None:
            return pipe
        # If pipeline eval fails (OPA down, entrypoint not loaded), fall
        # through to single-policy eval so the user gets SOMETHING rather
        # than a silent no-op.

    real = _opa_simulate(policy, inp)
    if real is not None:
        return real

    pid  = policy["id"]
    name = policy["name"]
    ptype = policy.get("type", "")
    mode  = policy.get("mode", "Monitor").lower()

    # In Monitor mode → never actually blocks, just flags
    def _decision(d: str, reason: str, rule: str) -> SimulateResponse:
        if mode in ("monitor", "disabled") and d == "block":
            d = "flag"
            reason = f"[Monitor mode — would block] {reason}"
        return SimulateResponse(
            policy_id=pid,
            policy_name=name,
            decision=d,
            reason=reason,
            matched_rule=rule,
            details={"input": inp, "mode": mode, "policy_type": ptype},
        )

    prompt: str   = str(inp.get("prompt", ""))
    posture: float = float(inp.get("posture_score", 0.0))
    signals: list  = list(inp.get("signals", []))
    guard_verdict  = inp.get("guard_verdict", "allow")

    # ── prompt-safety (Prompt-Guard, Jailbreak-Detect) ────────────────────────
    if ptype == "prompt-safety":
        prompt_lower = prompt.lower()
        for pat in _JAILBREAK_PATTERNS:
            if pat in prompt_lower:
                return _decision("block", f"Jailbreak pattern matched: \"{pat}\"", "injection_detected")
        threat_score = float(inp.get("threat_score", 0.0))
        if threat_score > 0.85:
            return _decision("block", f"Threat score {threat_score:.2f} exceeds threshold 0.85", "jailbreak_pattern_matched")
        if guard_verdict == "block":
            return _decision("block", "Guard model explicit block", "guard_verdict_block")
        return _decision("allow", "No adversarial patterns detected.", None)

    # ── tool-access (Tool-Scope, Write-Approval) ──────────────────────────────
    if ptype == "tool-access":
        blocking_signals = [s for s in signals if s in _SIGNAL_BLOCKERS]
        if blocking_signals:
            return _decision("block", f"Signal(s) detected: {', '.join(blocking_signals)}", "signal_block")
        if posture >= 0.60:
            return _decision("block", f"Posture {posture:.2f} ≥ 0.60 — all write ops suspended", "block_write_critical_posture")
        tool_name = inp.get("tool_name", "")
        tool_category = inp.get("tool_category", "")
        if posture >= 0.20 and tool_category == "write":
            return _decision("flag", f"Write tool '{tool_name}' requires approval at posture {posture:.2f}", "require_approval_high_posture")
        return _decision("allow", "Tool access permitted within scope and posture thresholds.", None)

    # ── privacy / output-validation (PII-Mask, Output-Filter) ────────────────
    if ptype in ("privacy", "output-validation"):
        if inp.get("contains_secret"):
            return _decision("block", "Credential or secret detected in output.", "secret_detected")
        if guard_verdict == "block" or inp.get("llm_verdict") == "block":
            return _decision("block", "LLM scan flagged high-risk content.", "llm_verdict_block")
        if inp.get("contains_pii"):
            return _decision("redact", "PII detected — redacting before delivery.", "pii_detected")
        return _decision("allow", "Output passed all content checks.", None)

    # ── data-access (Egress-Control, RAG-Retrieval-Limit) ────────────────────
    if ptype == "data-access":
        if policy["name"] == "RAG-Retrieval-Limit":
            if posture >= 0.70:
                return _decision("block", f"Critical posture {posture:.2f} ≥ 0.70 — RAG suspended.", "block_rag_critical")
            if posture >= 0.40:
                return _decision("flag", f"Posture {posture:.2f} ≥ 0.40 — reduced to 3 chunks.", "rag_reduced_window")
            ns = inp.get("namespace", "")
            if ns in ("credentials", "secrets", "pki", "hr_records"):
                scopes = inp.get("auth_context", {}).get("scopes", [])
                if "rag:sensitive" not in scopes:
                    return _decision("block", f"Namespace '{ns}' requires rag:sensitive scope.", "sensitive_namespace_block")
        else:
            # Egress-Control
            destination = inp.get("destination", "")
            if any(bad in destination for bad in ("pastebin.com", "requestbin", "ngrok")):
                return _decision("block", f"Destination '{destination}' is a known exfil channel.", "block_exfil_domain")
            ALLOWLIST = ["orbyx.internal", "api.tavily.com", "api.anthropic.com"]
            if destination and not any(a in destination for a in ALLOWLIST):
                return _decision("block", f"Destination '{destination}' not in egress allowlist.", "deny_all_by_default")
        return _decision("allow", "Request within permitted parameters.", None)

    # ── rate-limit (Token-Budget) ─────────────────────────────────────────────
    if ptype == "rate-limit":
        tokens_used = int(inp.get("tokens_used", 0))
        session_cap = 8192
        daily_cap   = 2_000_000
        if tokens_used >= session_cap:
            return _decision("block", f"Session token budget exhausted ({tokens_used} / {session_cap}).", "session_cap")
        daily_used = int(inp.get("daily_tokens_used", 0))
        if daily_used >= daily_cap:
            return _decision("block", f"Daily tenant token budget reached ({daily_used:,} / {daily_cap:,}).", "daily_tenant_cap")
        if tokens_used >= int(session_cap * 0.80):
            return _decision("flag", f"Approaching session cap: {tokens_used} / {session_cap} tokens used.", "warn_at_80_pct")
        return _decision("allow", f"Within token budget ({tokens_used} / {session_cap} session tokens used).", None)

    # ── fallback ──────────────────────────────────────────────────────────────
    return SimulateResponse(
        policy_id=pid,
        policy_name=name,
        decision="allow",
        reason="Policy type not evaluated — no matching simulation logic.",
        matched_rule=None,
        details={"input": inp},
    )
