"""
policies/seed.py
─────────────────
Default policy seed data.
Called once at application startup if the policies table is empty.
No side effects on import — seeding only happens when seed_policies() is called.
"""
from __future__ import annotations

from .store import (
    _PROMPT_GUARD_CODE,
    _TOOL_SCOPE_CODE,
    _PII_MASK_CODE,
    _WRITE_APPROVAL_CODE,
    _TOKEN_BUDGET_CODE,
    _OUTPUT_FILTER_CODE,
    _EGRESS_CONTROL_CODE,
    _RAG_RETRIEVAL_CODE,
    _JAILBREAK_DETECT_CODE,
    _tokenise,
    create_policy_raw,
    list_policies,
)

_SEED_DATA = [
    {
        "id": "pg-v3",
        "name": "Prompt-Guard",
        "version": "v3",
        "type": "prompt-safety",
        "mode": "Enforce",
        "status": "Active",
        "scope": "All Production Agents",
        "owner": "security-ops",
        "createdBy": "admin@orbyx.ai",
        "created": "Mar 12, 2026",
        "updated": "2d ago",
        "updatedFull": "Apr 7, 2026 · 09:14 UTC",
        "description": "Detects and blocks adversarial prompt patterns including jailbreaks, role-play overrides, and Base64-encoded bypass attempts before they reach any production model invocation.",
        "affectedAssets": 8,
        "relatedAlerts": 4,
        "linkedSimulations": 2,
        "agents": ["CustomerSupport-GPT", "ThreatHunter-AI", "DataPipeline-Orchestrator"],
        "tools": [],
        "dataSources": [],
        "environments": ["Production"],
        "exceptions": ["staging-test-agent-01"],
        "impact": {"blocked": 4, "flagged": 11, "unchanged": 105, "total": 120},
        "history": [
            {"version": "v3", "by": "admin@orbyx.ai",   "when": "Apr 7, 2026 · 09:14",  "change": "Added Base64 payload detection. Confidence threshold raised to 0.92."},
            {"version": "v2", "by": "sec-eng@orbyx.ai", "when": "Mar 28, 2026 · 14:02", "change": "Expanded jailbreak signature library. Added roleplay framing detection."},
            {"version": "v1", "by": "admin@orbyx.ai",   "when": "Mar 12, 2026 · 10:30", "change": "Initial policy created. Basic injection pattern matching."},
        ],
        "logic_code": _PROMPT_GUARD_CODE,
        "logic_language": "rego",
    },
    {
        "id": "ts-v2",
        "name": "Tool-Scope",
        "version": "v2",
        "type": "tool-access",
        "mode": "Enforce",
        "status": "Active",
        "scope": "All Agents — Production",
        "owner": "platform-eng",
        "createdBy": "platform@orbyx.ai",
        "created": "Mar 14, 2026",
        "updated": "3d ago",
        "updatedFull": "Apr 6, 2026 · 11:30 UTC",
        "description": "Restricts which tools each agent role may invoke. Deny-by-default; explicit allowlist per scope + posture threshold check before any side-effect tool is executed.",
        "affectedAssets": 12,
        "relatedAlerts": 1,
        "linkedSimulations": 3,
        "agents": ["CustomerSupport-GPT", "ThreatHunter-AI", "DataPipeline-Orchestrator", "ReportGen-AI"],
        "tools": ["file.read", "file.write", "gmail.send_email", "calendar.write", "db.query"],
        "dataSources": [],
        "environments": ["Production", "Staging"],
        "exceptions": [],
        "impact": {"blocked": 7, "flagged": 5, "unchanged": 88, "total": 100},
        "history": [
            {"version": "v2", "by": "platform@orbyx.ai", "when": "Apr 6, 2026 · 11:30", "change": "Added db.query and web.search to allowlist. Tightened posture thresholds."},
            {"version": "v1", "by": "platform@orbyx.ai", "when": "Mar 14, 2026 · 09:00", "change": "Initial tool scope policy. Read-only tools permitted at posture < 0.40."},
        ],
        "logic_code": _TOOL_SCOPE_CODE,
        "logic_language": "rego",
    },
    {
        "id": "pm-v1",
        "name": "PII-Mask",
        "version": "v1",
        "type": "privacy",
        "mode": "Enforce",
        "status": "Active",
        "scope": "All Output Streams",
        "owner": "privacy-team",
        "createdBy": "dpo@orbyx.ai",
        "created": "Mar 20, 2026",
        "updated": "5d ago",
        "updatedFull": "Apr 4, 2026 · 16:22 UTC",
        "description": "Detects and redacts personally identifiable information (PII) from all LLM outputs before delivery to end users. Covers emails, SSNs, phone numbers, and financial data.",
        "affectedAssets": 6,
        "relatedAlerts": 0,
        "linkedSimulations": 1,
        "agents": [],
        "tools": [],
        "dataSources": ["customer-db", "hr-records"],
        "environments": ["Production"],
        "exceptions": ["internal-analytics-agent"],
        "impact": {"blocked": 0, "flagged": 3, "unchanged": 97, "total": 100},
        "history": [
            {"version": "v1", "by": "dpo@orbyx.ai", "when": "Mar 20, 2026 · 10:00", "change": "Initial PII masking policy. Regex + OPA hybrid detection."},
        ],
        "logic_code": _PII_MASK_CODE,
        "logic_language": "rego",
    },
    {
        "id": "wa-v2",
        "name": "Write-Approval",
        "version": "v2",
        "type": "tool-access",
        "mode": "Enforce",
        "status": "Active",
        "scope": "Write-Side-Effect Tools",
        "owner": "security-ops",
        "createdBy": "admin@orbyx.ai",
        "created": "Mar 22, 2026",
        "updated": "4d ago",
        "updatedFull": "Apr 5, 2026 · 14:10 UTC",
        "description": "Enforces human-in-the-loop approval for all write-side-effect tool calls (file.write, gmail.send_email, calendar.write) when posture score exceeds 0.20.",
        "affectedAssets": 5,
        "relatedAlerts": 2,
        "linkedSimulations": 1,
        "agents": ["CustomerSupport-GPT", "ReportGen-AI"],
        "tools": ["file.write", "gmail.send_email", "calendar.write"],
        "dataSources": [],
        "environments": ["Production"],
        "exceptions": [],
        "impact": {"blocked": 3, "flagged": 8, "unchanged": 89, "total": 100},
        "history": [
            {"version": "v2", "by": "admin@orbyx.ai",   "when": "Apr 5, 2026 · 14:10", "change": "Added calendar.write to approval scope. Lowered approval threshold to 0.20."},
            {"version": "v1", "by": "platform@orbyx.ai","when": "Mar 22, 2026 · 09:30", "change": "Initial write-approval policy. Covered file.write and gmail.send."},
        ],
        "logic_code": _WRITE_APPROVAL_CODE,
        "logic_language": "json",
    },
    {
        "id": "tb-v1",
        "name": "Token-Budget",
        "version": "v1",
        "type": "rate-limit",
        "mode": "Enforce",
        "status": "Active",
        "scope": "All Tenants — Sessions",
        "owner": "platform-eng",
        "createdBy": "platform@orbyx.ai",
        "created": "Mar 25, 2026",
        "updated": "6d ago",
        "updatedFull": "Apr 3, 2026 · 10:55 UTC",
        "description": "Hard caps on token consumption: 8,192 tokens per session, 2M tokens per tenant per day. Soft warning at 80%. Prevents runaway LLM loops and controls API spend.",
        "affectedAssets": 9,
        "relatedAlerts": 0,
        "linkedSimulations": 0,
        "agents": [],
        "tools": [],
        "dataSources": [],
        "environments": ["Production", "Staging"],
        "exceptions": ["load-test-tenant"],
        "impact": {"blocked": 1, "flagged": 4, "unchanged": 95, "total": 100},
        "history": [
            {"version": "v1", "by": "platform@orbyx.ai", "when": "Mar 25, 2026 · 11:00", "change": "Initial token budget policy. Session cap 8192, daily tenant cap 2M."},
        ],
        "logic_code": _TOKEN_BUDGET_CODE,
        "logic_language": "json",
    },
    {
        "id": "of-v2",
        "name": "Output-Filter",
        "version": "v2",
        "type": "output-validation",
        "mode": "Enforce",
        "status": "Active",
        "scope": "All LLM Outputs",
        "owner": "security-ops",
        "createdBy": "sec-eng@orbyx.ai",
        "created": "Mar 18, 2026",
        "updated": "3d ago",
        "updatedFull": "Apr 6, 2026 · 08:40 UTC",
        "description": "Scans all LLM responses for secrets, credentials, and high-risk content before delivery. Blocks outputs containing credentials; redacts PII; blocks outputs flagged by secondary LLM scan.",
        "affectedAssets": 8,
        "relatedAlerts": 3,
        "linkedSimulations": 2,
        "agents": [],
        "tools": [],
        "dataSources": [],
        "environments": ["Production"],
        "exceptions": [],
        "impact": {"blocked": 2, "flagged": 6, "unchanged": 92, "total": 100},
        "history": [
            {"version": "v2", "by": "sec-eng@orbyx.ai", "when": "Apr 6, 2026 · 08:40", "change": "Added secondary LLM verdict check. Tightened redaction regex."},
            {"version": "v1", "by": "sec-eng@orbyx.ai", "when": "Mar 18, 2026 · 12:15", "change": "Initial output filter. Secret regex + PII redaction."},
        ],
        "logic_code": _OUTPUT_FILTER_CODE,
        "logic_language": "rego",
    },
    {
        "id": "ec-v1",
        "name": "Egress-Control",
        "version": "v1",
        "type": "data-access",
        "mode": "Monitor",
        "status": "Active",
        "scope": "External HTTP Calls",
        "owner": "network-security",
        "createdBy": "netops@orbyx.ai",
        "created": "Apr 1, 2026",
        "updated": "6d ago",
        "updatedFull": "Apr 3, 2026 · 17:00 UTC",
        "description": "Deny-by-default allowlist for agent egress. Controls which external endpoints agents may contact. Blocks known exfiltration channels (pastebin, requestbin, ngrok).",
        "affectedAssets": 4,
        "relatedAlerts": 1,
        "linkedSimulations": 0,
        "agents": ["ThreatHunter-AI", "DataPipeline-Orchestrator"],
        "tools": ["web.search", "web_fetch"],
        "dataSources": [],
        "environments": ["Production"],
        "exceptions": [],
        "impact": {"blocked": 0, "flagged": 2, "unchanged": 98, "total": 100},
        "history": [
            {"version": "v1", "by": "netops@orbyx.ai", "when": "Apr 1, 2026 · 09:00", "change": "Initial egress control policy. Allowlist: *.orbyx.internal, api.tavily.com, api.anthropic.com."},
        ],
        "logic_code": _EGRESS_CONTROL_CODE,
        "logic_language": "json",
    },
    {
        "id": "rr-v1",
        "name": "RAG-Retrieval-Limit",
        "version": "v1",
        "type": "data-access",
        "mode": "Monitor",
        "status": "Active",
        "scope": "RAG Pipeline",
        "owner": "platform-eng",
        "createdBy": "platform@orbyx.ai",
        "created": "Apr 2, 2026",
        "updated": "5d ago",
        "updatedFull": "Apr 4, 2026 · 13:30 UTC",
        "description": "Limits RAG retrieval chunk counts under elevated posture scores. Reduces context window to 3 chunks at posture ≥ 0.40 and blocks retrieval entirely at posture ≥ 0.70. Sensitive namespaces require explicit scope.",
        "affectedAssets": 3,
        "relatedAlerts": 0,
        "linkedSimulations": 1,
        "agents": ["CustomerSupport-GPT", "DataPipeline-Orchestrator"],
        "tools": [],
        "dataSources": ["knowledge-base", "customer-db"],
        "environments": ["Production", "Staging"],
        "exceptions": [],
        "impact": {"blocked": 1, "flagged": 3, "unchanged": 96, "total": 100},
        "history": [
            {"version": "v1", "by": "platform@orbyx.ai", "when": "Apr 2, 2026 · 10:00", "change": "Initial RAG retrieval limit. Sensitive namespace protection. Posture-gated chunk reduction."},
        ],
        "logic_code": _RAG_RETRIEVAL_CODE,
        "logic_language": "rego",
    },
    {
        "id": "jd-v2",
        "name": "Jailbreak-Detect",
        "version": "v2",
        "type": "prompt-safety",
        "mode": "Enforce",
        "status": "Active",
        "scope": "All User Inputs",
        "owner": "security-ops",
        "createdBy": "admin@orbyx.ai",
        "created": "Mar 16, 2026",
        "updated": "4d ago",
        "updatedFull": "Apr 5, 2026 · 11:00 UTC",
        "description": "Detects jailbreak attempts via pattern matching, Base64 payload detection, and threat score thresholding. Covers DAN variants, developer-mode prompts, roleplay overrides, and encoded bypass attempts.",
        "affectedAssets": 8,
        "relatedAlerts": 2,
        "linkedSimulations": 3,
        "agents": ["CustomerSupport-GPT", "ThreatHunter-AI"],
        "tools": [],
        "dataSources": [],
        "environments": ["Production"],
        "exceptions": ["red-team-agent"],
        "impact": {"blocked": 5, "flagged": 7, "unchanged": 88, "total": 100},
        "history": [
            {"version": "v2", "by": "admin@orbyx.ai",   "when": "Apr 5, 2026 · 11:00", "change": "Added Base64 payload heuristic. Expanded DAN variant signatures."},
            {"version": "v1", "by": "sec-eng@orbyx.ai", "when": "Mar 16, 2026 · 14:20", "change": "Initial jailbreak detection policy. Pattern library + threat score gate."},
        ],
        "logic_code": _JAILBREAK_DETECT_CODE,
        "logic_language": "rego",
    },
]




def _run_backfill() -> None:
    """Idempotent backfill of PolicyVersionORM from existing PolicyORM rows."""
    try:
        from policies.migration_util import backfill_policy_versions
        from policies import store as _store
        sess = _store._get_or_new_session()
        backfill_policy_versions(sess)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("backfill_policy_versions failed: %s", e)

def _mock_policy_ids() -> set[str]:
    """IDs of the legacy hardcoded mock policies. Used by the Phase 1
    migration to detect a DB that was seeded against the pre-Phase-1
    code and needs the mocks evicted before real policies can take
    their place."""
    return {row["id"] for row in _SEED_DATA}


def _purge_mock_policies_if_present() -> int:
    """One-time migration: delete any rows whose ID matches the known
    mock seed.  Returns the count removed.

    Why this exists:
      Pre-Phase-1, ``seed_policies()`` populated the policies table from
      ``_SEED_DATA`` — fictional policies (Prompt-Guard, Tool-Scope,
      PII-Mask, etc.) used only for UI demos.  Phase 1 swaps that for
      the real OPA policies bundled from the chart's
      ``files/policies/*.rego``.  But ``seed_policies`` short-circuits
      when the table is non-empty, so on existing dev clusters the mock
      rows would block the real seed.

      Pruning is keyed strictly on the mock ID list — any user-created
      policy whose ID happens not to be in that set is left alone.

    Idempotent: a second call after the mocks are already gone deletes
    zero rows and returns 0.
    """
    mock_ids = _mock_policy_ids()
    if not mock_ids:
        return 0
    # Use the store's own session helpers so we honour the "don't close the
    # injected test session" contract — calling db.close() directly here
    # would break unit tests that mount their own SQLAlchemy session via
    # init_db_for_session().  ``_close()`` is the existing helper that
    # close-or-skips correctly.
    from .store import _get_session, _close
    db = _get_session()
    try:
        from .db_models import PolicyORM
        from sqlalchemy import select
        rows = db.scalars(
            select(PolicyORM).where(PolicyORM.policy_id.in_(mock_ids))
        ).all()
        n = 0
        for row in rows:
            db.delete(row)
            n += 1
        if n:
            db.commit()
        return n
    finally:
        _close(db)


def _reconcile_real_policies_logic_code() -> int:
    """Self-healing reconciliation between the bundled .rego files and the
    catalog DB.  For every real-policy row, if its ``logic_code`` doesn't
    match the bundled .rego content, update the row to match the bundle.

    Returns the count of rows updated.

    Why this exists:
      The Phase 1 seed only runs when the policies table is empty.  Once
      it's populated, every subsequent restart short-circuits.  That's
      idempotent in the happy path, but it leaks one specific class of
      bug: if a single .rego file was empty / unreadable / incomplete
      during the very first seed, its row carries the empty value
      forever.  We hit exactly this with ``pii_policy-v1`` — its row
      was inserted with logic_code='' on an early deploy and the
      idempotent seed never re-ran to fix it.

      This reconciliation step closes the loop.  Each startup compares
      every real-policy row's ``logic_code`` against the bundled file's
      current content; any mismatch is updated in place.  ``user-edited
      policies'' (those whose IDs aren't in the bundled set) are never
      touched.

    Operationally idempotent — when bundle and DB match, this does N
    SELECTs and zero writes, finishing in <50ms even with hundreds of
    policies.  Logs a warning per update so operators see when self-
    heal kicks in.
    """
    from .rego_seed import load_real_policies
    seeds = load_real_policies()
    if not seeds:
        return 0

    bundled_by_id = {s["id"]: s for s in seeds}

    from .store import _get_session, _close
    db = _get_session()
    try:
        from .db_models import PolicyORM, PolicyVersionORM
        from sqlalchemy import select, func
        rows = db.scalars(
            select(PolicyORM).where(
                PolicyORM.policy_id.in_(list(bundled_by_id.keys()))
            )
        ).all()

        # ── User-edit safety check ──────────────────────────────────────
        # Reconciliation MUST NOT clobber operator edits.  When a user
        # edits a policy via the UI (Phase 2), Phase 2's PUT /policies/
        # {id} or its draft endpoint creates an additional PolicyVersionORM
        # row beyond the seed's v1.  So we only reconcile rows whose
        # version count is exactly 1 — meaning no operator edit has been
        # saved yet, the row is still "as-shipped from the chart bundle"
        # and safe to re-sync.  Any policy with 2+ versions is treated
        # as user-owned and left alone.
        version_counts = {
            pid: count for pid, count in db.execute(
                select(
                    PolicyVersionORM.policy_id,
                    func.count(PolicyVersionORM.id),
                ).where(
                    PolicyVersionORM.policy_id.in_(list(bundled_by_id.keys()))
                ).group_by(PolicyVersionORM.policy_id)
            ).all()
        }

        n_updated = 0
        n_skipped_user_edited = 0
        n_recovered_empty   = 0
        for row in rows:
            bundled = bundled_by_id[row.policy_id]
            new_code = bundled["logic_code"]
            if (row.logic_code or "") == new_code:
                continue   # already matches — no work

            current_is_empty = not (row.logic_code or "").strip()

            # Two reconcile-eligible cases:
            #
            #  (a) version count == 1: still as-shipped from the bundle,
            #      no operator edits yet → safe to re-sync to the bundle.
            #
            #  (b) current logic_code is empty/whitespace, REGARDLESS of
            #      version count: this is the "wiped" state from the
            #      May-2-2026 incident where every UI Save-Draft click
            #      sent logic_code="" and silently bumped the row to
            #      v6/v11/etc.  An empty body cannot represent a real
            #      operator edit (the backend now refuses empty PUTs;
            #      see policies/store.py:update_policy), so overwriting
            #      empty with the bundle content can never destroy real
            #      user work — it can only restore lost content.
            #
            # Anything else (current has content AND >1 version) is a
            # genuine operator edit and stays untouched.
            if current_is_empty:
                row.logic_code = new_code
                row.logic = _tokenise(new_code, bundled["logic_language"])
                n_recovered_empty += 1
                n_updated += 1
                continue
            if version_counts.get(row.policy_id, 1) > 1:
                n_skipped_user_edited += 1
                continue
            row.logic_code = new_code
            row.logic = _tokenise(new_code, bundled["logic_language"])
            n_updated += 1

        if n_updated:
            db.commit()

        if n_skipped_user_edited or n_recovered_empty:
            import logging as _logging
            _log = _logging.getLogger(__name__)
            if n_recovered_empty:
                _log.warning(
                    "_reconcile: recovered %d policies with empty logic_code "
                    "from chart bundle (likely victims of the empty-PUT bug)",
                    n_recovered_empty,
                )
            if n_skipped_user_edited:
                _log.info(
                    "_reconcile: skipped %d policies with user edits (>1 version, non-empty)",
                    n_skipped_user_edited,
                )
        return n_updated
    finally:
        _close(db)


def seed_policies() -> None:
    """Insert default policies if the table is empty. Idempotent.

    Three-pass startup contract:
      1. ``_purge_mock_policies_if_present()`` — evict pre-Phase-1 mock
         rows by ID so the real seed can claim the table on existing
         dev clusters.
      2. ``_reconcile_real_policies_logic_code()`` — self-heal any
         existing real-policy rows whose ``logic_code`` drifted from
         the bundled .rego (insert-time bug, partial seed, etc.).
         This runs on EVERY startup — DB and bundle stay in lockstep.
      3. If the table is still empty, do the initial seed: real .rego
         policies bundled from ``deploy/helm/aispm/files/policies/`` if
         present, hardcoded mocks (``_SEED_DATA``) otherwise (used by
         local dev / tests where the Dockerfile bundling didn't run).

    User-created policies (any row whose ID isn't in the bundled real
    set or the mock set) are never touched by any pass.
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)

    # 1. Phase 1 migration — evict legacy mock rows so the real seed can run.
    purged = _purge_mock_policies_if_present()
    if purged:
        _log.info("seed_policies: purged %d legacy mock rows", purged)

    # 2. Self-heal: re-sync logic_code from the bundle when it drifted.
    try:
        n_recon = _reconcile_real_policies_logic_code()
        if n_recon:
            _log.warning(
                "seed_policies: reconciled %d real-policy row(s) whose "
                "logic_code drifted from the chart bundle (self-heal)",
                n_recon,
            )
    except Exception as exc:
        _log.warning("seed_policies: reconciliation failed (non-fatal): %s", exc)

    if list_policies():
        _run_backfill()
        return

    # 3. Initial seed — real .rego policies first, mocks as fallback.
    from .rego_seed import load_real_policies
    real_seeds = load_real_policies()
    if real_seeds:
        for raw in real_seeds:
            raw["logic"] = _tokenise(raw["logic_code"], raw["logic_language"])
            create_policy_raw(raw)
        _log.info(
            "seed_policies: seeded %d real OPA policies from chart bundle",
            len(real_seeds),
        )
        _run_backfill()
        return

    # Fallback — use the hardcoded mocks (local dev / tests).
    for raw in _SEED_DATA:
        raw = dict(raw)  # don't mutate the module-level constant
        raw["logic"] = _tokenise(raw["logic_code"], raw["logic_language"])
        create_policy_raw(raw)
    _run_backfill()
