"""
policies/store.py
──────────────────
DB-backed policy store — synchronous SQLAlchemy.

Public interface is identical to the previous in-memory implementation.
The _seed() function is gone; call seed.seed_policies() from main.py instead.

Thread safety: each public function opens a fresh Session from _SessionLocal
and closes it on exit (or uses the injected test session).

Initialisation
──────────────
  init_db(db_url)             — call once from main.py lifespan
  init_db_for_session(sess)   — test helper: injects a pre-made Session
"""
from __future__ import annotations

import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.pool import StaticPool

from .db_models import PolicyORM
from .models import PolicyCreate, PolicyUpdate

# ── Module-level state ────────────────────────────────────────────────────────

_SessionLocal = None   # set by init_db()
_test_session = None   # set by init_db_for_session() for tests


# ── Time helpers ──────────────────────────────────────────────────────────────

def _now_display() -> str:
    return datetime.now(timezone.utc).strftime("%b %d, %Y")


def _now_full() -> str:
    return datetime.now(timezone.utc).strftime("%b %d, %Y · %H:%M UTC")


def _bump_version(current: str) -> str:
    """v1 → v2, v2 → v3, etc."""
    try:
        n = int(current.lstrip("v"))
        return f"v{n + 1}"
    except ValueError:
        return current + ".1"


# ── Tokeniser ─────────────────────────────────────────────────────────────────

_REGO_KW  = {"package", "import", "default", "if", "in", "not", "else", "with", "as", "some", "every", "allow", "deny"}
_JSON_KW  = {"true", "false", "null"}


def _tokenise(code: str, language: str) -> list[dict]:
    """
    Very lightweight tokeniser that produces [{t, v}] token lists
    compatible with the existing CodeBlock component.

    Token types:
      kw  – keyword
      fn  – function / rule name
      str – string literal
      num – number
      bl  – boolean / null
      cm  – comment
      tx  – plain text
    """
    if not code.strip():
        return []

    tokens: list[dict] = []
    i = 0
    kw_set = _REGO_KW if language != "json" else _JSON_KW

    while i < len(code):
        ch = code[i]

        # Comment — Rego uses #
        if ch == "#" and language != "json":
            end = code.find("\n", i)
            end = end if end != -1 else len(code)
            tokens.append({"t": "cm", "v": code[i:end]})
            i = end
            continue

        # String — double-quoted
        if ch == '"':
            j = i + 1
            while j < len(code):
                if code[j] == "\\" and j + 1 < len(code):
                    j += 2
                elif code[j] == '"':
                    j += 1
                    break
                else:
                    j += 1
            tokens.append({"t": "str", "v": code[i:j]})
            i = j
            continue

        # Number
        if ch.isdigit() or (ch == "-" and i + 1 < len(code) and code[i + 1].isdigit()):
            j = i + (1 if ch == "-" else 0)
            while j < len(code) and (code[j].isdigit() or code[j] in ".eE+-"):
                j += 1
            tokens.append({"t": "num", "v": code[i:j]})
            i = j
            continue

        # Identifier — keyword / boolean / function / plain
        if ch.isalpha() or ch == "_":
            j = i
            while j < len(code) and (code[j].isalnum() or code[j] == "_" or code[j] == "."):
                j += 1
            word = code[i:j]
            if word in kw_set:
                tokens.append({"t": "kw", "v": word})
            elif word in ("true", "false", "null"):
                tokens.append({"t": "bl", "v": word})
            elif j < len(code) and code[j] == "(":
                tokens.append({"t": "fn", "v": word})
            else:
                tokens.append({"t": "tx", "v": word})
            i = j
            continue

        # Everything else (operators, punctuation, whitespace)
        # Accumulate until we hit something we'd parse differently
        j = i
        while j < len(code) and not (
            code[j].isalpha() or code[j] == "_"
            or code[j] == '"'
            or (code[j].isdigit())
            or (code[j] == "#" and language != "json")
        ):
            j += 1
            if j > i and code[j - 1] in ('"', "#"):
                j -= 1
                break
        if j > i:
            tokens.append({"t": "tx", "v": code[i:j]})
            i = j
        else:
            tokens.append({"t": "tx", "v": ch})
            i += 1

    return tokens


# ── Policy code constants (copied verbatim from old store.py) ───────────────────

_PROMPT_GUARD_CODE = """\
package ai.security.prompt_guard

import future.keywords.if
import future.keywords.in

default allow := false

allow if {
    not injection_detected
    not jailbreak_pattern_matched
}

injection_detected if {
    patterns := [
        "ignore all previous instructions",
        "forget your system prompt",
        "you are now",
        "act as if you have no",
    ]
    some pattern in patterns
    contains(lower(input.prompt), pattern)
}

jailbreak_pattern_matched if {
    input.threat_score > 0.85
    input.pattern_type == "adversarial"
}\
"""

_TOOL_SCOPE_CODE = """\
package spm.tools

import future.keywords.if
import future.keywords.in

default allow := {"decision":"block","reason":"tool denied by default","action":"deny_tool_execution"}

has_scope(scope) if { scope in input.auth_context.scopes }
has_signal(sig)  if { sig  in input.signals }

# Block exfiltration attempts across all tools
allow := {"decision":"block","reason":"exfiltration signal","action":"deny_tool_execution"} if {
    has_signal("exfiltration")
}

# Block high-posture side-effect tools
allow := {"decision":"block","reason":"high posture blocks side-effect tools","action":"deny_tool_execution"} if {
    input.posture_score >= 0.50
    input.tool_name != "security.review"
}

# Read-only tools
allow := {"decision":"allow","reason":"file read permitted","action":"allow_tool_execution"} if {
    input.tool_name == "file.read"
    has_scope("file:read")
    not has_signal("exfiltration")
    input.posture_score < 0.35
}

# Security review always permitted
allow := {"decision":"allow","reason":"security review permitted","action":"allow_tool_execution"} if {
    input.tool_name == "security.review"
}\
"""

_PII_MASK_CODE = """\
package ai.privacy.pii_mask

import future.keywords.if
import future.keywords.in

default allow := {"decision":"allow","action":"pass_through"}

# PII detected in output — redact before delivery
allow := {"decision":"redact","action":"mask_pii","reason":"PII detected in response"} if {
    input.contains_pii == true
    input.contains_secret == false
    input.llm_verdict != "block"
}

# Secret detected — block entirely
allow := {"decision":"block","action":"deny_output","reason":"Credential or secret detected"} if {
    input.contains_secret == true
}

# High-risk fields — always redact
_pii_fields := {"ssn", "credit_card", "passport", "dob", "phone", "email"}

allow := {"decision":"redact","action":"mask_field","reason":"High-risk PII field"} if {
    some field in input.fields
    field in _pii_fields
}\
"""

_WRITE_APPROVAL_CODE = """\
{
  "policy": "write-approval",
  "version": "v2",
  "description": "All write-side-effect tool calls require human-in-the-loop approval above posture 0.20",
  "rules": [
    {
      "id": "require_approval_high_posture",
      "condition": { "posture_score": { "gte": 0.20 }, "tool_category": "write" },
      "action": "require_approval",
      "approver": "security-ops"
    },
    {
      "id": "block_write_critical_posture",
      "condition": { "posture_score": { "gte": 0.60 } },
      "action": "block",
      "reason": "Critical posture: all write ops suspended"
    },
    {
      "id": "allow_write_low_posture",
      "condition": { "posture_score": { "lt": 0.20 }, "signals": [] },
      "action": "allow"
    }
  ],
  "thresholds": {
    "approval_posture": 0.20,
    "block_posture": 0.60
  }
}\
"""

_TOKEN_BUDGET_CODE = """\
{
  "policy": "token-budget",
  "version": "v1",
  "description": "Hard caps on token consumption per session and per tenant per day",
  "rules": [
    {
      "id": "session_cap",
      "scope": "session",
      "limit": 8192,
      "action": "block",
      "reason": "Session token budget exhausted"
    },
    {
      "id": "daily_tenant_cap",
      "scope": "tenant_day",
      "limit": 2000000,
      "action": "throttle",
      "reason": "Daily tenant token budget reached"
    },
    {
      "id": "warn_at_80_pct",
      "scope": "session",
      "threshold_pct": 80,
      "action": "warn",
      "reason": "Approaching session token limit"
    }
  ],
  "thresholds": {
    "session_hard_cap": 8192,
    "daily_tenant_cap": 2000000,
    "warn_pct": 80
  }
}\
"""

_OUTPUT_FILTER_CODE = """\
package spm.output

import future.keywords.if

default allow := {"decision":"allow","reason":"output allowed"}

allow := {"decision":"block","reason":"secret or credential detected in output"} if {
    input.contains_secret == true
}

allow := {"decision":"block","reason":"LLM scan flagged high-risk content"} if {
    input.llm_verdict == "block"
}

allow := {"decision":"redact","reason":"PII detected — redacting before delivery"} if {
    input.contains_pii == true
    input.contains_secret == false
    input.llm_verdict != "block"
}\
"""

_EGRESS_CONTROL_CODE = """\
{
  "policy": "egress-control",
  "version": "v1",
  "description": "Controls which external endpoints agents may call. Deny-by-default allowlist model.",
  "rules": [
    {
      "id": "deny_all_by_default",
      "action": "block",
      "reason": "Egress blocked: destination not in allowlist"
    },
    {
      "id": "allow_internal_apis",
      "condition": { "destination": { "matches": "*.orbyx.internal" } },
      "action": "allow"
    },
    {
      "id": "allow_tavily_search",
      "condition": { "destination": "api.tavily.com", "tool": "web.search" },
      "action": "allow"
    },
    {
      "id": "block_data_exfil_domains",
      "condition": { "destination": { "matches": ["pastebin.com", "requestbin.*", "ngrok.*"] } },
      "action": "block",
      "reason": "Potential data exfiltration destination"
    }
  ],
  "allowlist": [
    "*.orbyx.internal",
    "api.tavily.com",
    "api.anthropic.com"
  ]
}\
"""

_RAG_RETRIEVAL_CODE = """\
package ai.rag.retrieval_limit

import future.keywords.if
import future.keywords.in

default allow := {"decision":"allow","chunks":10}

# Reduce retrieval window under high posture
allow := {"decision":"allow","chunks":3,"reason":"Posture-gated: reduced context window"} if {
    input.posture_score >= 0.40
    input.posture_score < 0.70
}

# Block RAG entirely under critical posture
allow := {"decision":"block","chunks":0,"reason":"Critical posture: RAG retrieval suspended"} if {
    input.posture_score >= 0.70
}

# Block sensitive namespaces unless explicitly scoped
allow := {"decision":"block","chunks":0,"reason":"Sensitive namespace requires explicit scope"} if {
    input.namespace in {"credentials","secrets","pki","hr_records"}
    not "rag:sensitive" in input.auth_context.scopes
}\
"""

_JAILBREAK_DETECT_CODE = """\
package ai.security.jailbreak_detect

import future.keywords.if
import future.keywords.in

default allow := false

_jailbreak_patterns := [
    "ignore all previous",
    "forget your instructions",
    "you are now dan",
    "developer mode",
    "jailbreak",
    "bypass safety",
    "act as if you have no restrictions",
    "pretend you are an ai without",
    "disregard your system prompt",
]

_base64_likely(s) if {
    count(s) > 60
    regex.match(`^[A-Za-z0-9+/=]{60,}$`, s)
}

injection_detected if {
    some pattern in _jailbreak_patterns
    contains(lower(input.prompt), pattern)
}

base64_payload_detected if {
    some token in input.tokens
    _base64_likely(token)
}

allow if {
    not injection_detected
    not base64_payload_detected
    input.threat_score < 0.85
}\
"""


# ── Initialisation helpers ────────────────────────────────────────────────────

def init_db(db_url: str, create_tables: bool = True) -> None:
    """Initialise the module-level session factory from a database URL."""
    global _SessionLocal, _test_session
    # Always clear any injected test session so the live session factory wins.
    _test_session = None

    from db.base import Base
    from policies.db_models import PolicyORM  # noqa: F401 — registers table on Base.metadata

    # SQLite :memory: opens a brand-new empty DB for every connection by default.
    # StaticPool forces all connections to reuse the same underlying connection so
    # create_all() and subsequent queries see the same tables.
    engine_kwargs: dict = {"echo": False, "future": True}
    if ":memory:" in db_url:
        engine_kwargs["connect_args"] = {"check_same_thread": False}
        engine_kwargs["poolclass"] = StaticPool

    engine = create_engine(db_url, **engine_kwargs)
    if create_tables:
        Base.metadata.create_all(engine, checkfirst=True)
    _SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def init_db_for_session(session: Session) -> None:
    """Test helper — bypass _SessionLocal entirely."""
    global _test_session, _SessionLocal
    _SessionLocal = None   # prevent accidental use of a live factory alongside an injected session
    _test_session = session


def _get_session() -> Session:
    """Get the current session (test or live)."""
    if _test_session is not None:
        return _test_session
    if _SessionLocal is None:
        raise RuntimeError("Policy store not initialised — call init_db() first.")
    return _SessionLocal()



def _get_or_new_session() -> Session:
    """Return current test session or create one from _SessionLocal. For internal use only."""
    if _test_session is not None:
        return _test_session
    if _SessionLocal is None:
        raise RuntimeError("Policy store not initialised — call init_db() first.")
    return _SessionLocal()

def _close(session: Session) -> None:
    """Close only if it is NOT the injected test session."""
    if session is not _test_session:
        session.close()



def _sync_version_row(policy_dict: dict, actor: str = "system") -> None:
    """
    Create a PolicyVersionORM row to match the current PolicyORM state.
    Called after every create_policy / update_policy write.
    Failures are logged but never propagated.
    """
    try:
        from policies.repository import VersionRepository
        from policies.lifecycle import map_mode_to_state, derive_is_runtime_active, PolicyState
        from policies.db_models import PolicyVersionORM as _PV

        sess = _get_or_new_session()
        repo = VersionRepository(sess)

        pid = policy_dict["id"]
        mode = policy_dict.get("mode", "Draft")
        state = map_mode_to_state(mode)

        try:
            vnum = int(policy_dict.get("version", "v1").lstrip("v"))
        except (ValueError, TypeError):
            vnum = 1

        # Skip if this version row already exists (idempotent)
        existing = sess.query(_PV).filter_by(policy_id=pid, version_number=vnum).first()
        if existing:
            return

        is_active = derive_is_runtime_active(
            state,
            legacy_status=policy_dict.get("status", "Active")
        )
        history = policy_dict.get("history") or []
        change_summary = history[-1].get("change", "") if history else ""

        v = repo.create_version(
            pid,
            logic_code=policy_dict.get("logic_code", ""),
            logic_language=policy_dict.get("logic_language", "rego"),
            actor=actor,
            change_summary=change_summary,
            commit=True,
        )

        # Promote + activate if policy is live
        if is_active and state != PolicyState.DRAFT:
            try:
                if state != PolicyState.DRAFT:
                    repo.promote_version(pid, v.version_number, state,
                                        actor=actor, reason="sync from store", commit=True)
                    repo.set_runtime_active(pid, v.version_number, actor=actor, commit=True)
            except Exception as e:
                import logging as _log
                _log.getLogger(__name__).warning("_sync_version_row promote failed: %s", e)
    except Exception as exc:
        import logging as _log
        _log.getLogger(__name__).warning("_sync_version_row failed: %s", exc)

# ── Converter ─────────────────────────────────────────────────────────────────

def _to_dict(row: PolicyORM) -> dict:
    """Convert a PolicyORM row to a dict matching the public API shape."""
    return {
        "id":                row.policy_id,
        "name":              row.name,
        "version":           row.version,
        "type":              row.type,
        "mode":              row.mode,
        "status":            row.status,
        "scope":             row.scope,
        "owner":             row.owner,
        "createdBy":         row.created_by,
        "created":           row.created,
        "updated":           row.updated,
        "updatedFull":       row.updated_full,
        "description":       row.description,
        "affectedAssets":    row.affected_assets,
        "relatedAlerts":     row.related_alerts,
        "linkedSimulations": row.linked_sims,
        "agents":            row.agents       or [],
        "tools":             row.tools        or [],
        "dataSources":       row.data_sources or [],
        "environments":      row.environments or [],
        "exceptions":        row.exceptions   or [],
        "impact":            row.impact       or {},
        "history":           row.history      or [],
        "logic":             row.logic        or [],
        "logic_code":        row.logic_code,
        "logic_language":    row.logic_language,
    }


# ── CRUD operations ──────────────────────────────────────────────────────────

def list_policies() -> list[dict]:
    """Return all policies as a list of dicts."""
    session = _get_session()
    try:
        rows = session.query(PolicyORM).all()
        return [_to_dict(row) for row in rows]
    finally:
        _close(session)


def get_policy(policy_id: str) -> Optional[dict]:
    """Fetch a single policy by ID."""
    session = _get_session()
    try:
        row = session.get(PolicyORM, policy_id)
        return _to_dict(row) if row else None
    finally:
        _close(session)


def create_policy(data: PolicyCreate, actor: str = "api") -> dict:
    """Create and return a new policy."""
    pid = str(uuid.uuid4())[:8]
    now_d = _now_display()
    now_f = _now_full()

    record = {
        "id": pid,
        "name": data.name,
        "version": "v1",
        "type": data.type,
        "mode": data.mode,
        "status": data.status,
        "scope": data.scope,
        "owner": data.owner,
        "createdBy": actor,
        "created": now_d,
        "updated": "just now",
        "updatedFull": now_f,
        "description": data.description,
        "affectedAssets": 0,
        "relatedAlerts": 0,
        "linkedSimulations": 0,
        "agents": data.agents,
        "tools": data.tools,
        "dataSources": data.data_sources,
        "environments": data.environments,
        "exceptions": data.exceptions,
        "impact": {"blocked": 0, "flagged": 0, "unchanged": 0, "total": 0},
        "history": [
            {
                "version": "v1",
                "by": actor,
                "when": now_f,
                "change": "Policy created.",
            }
        ],
        "logic": _tokenise(data.logic_code, data.logic_language),
        "logic_code": data.logic_code,
        "logic_language": data.logic_language,
    }

    session = _get_session()
    try:
        orm = PolicyORM(
            policy_id=pid,
            name=record["name"],
            version=record["version"],
            type=record["type"],
            mode=record["mode"],
            status=record["status"],
            scope=record["scope"],
            owner=record["owner"],
            created_by=record["createdBy"],
            created=record["created"],
            updated=record["updated"],
            updated_full=record["updatedFull"],
            description=record["description"],
            affected_assets=record["affectedAssets"],
            related_alerts=record["relatedAlerts"],
            linked_sims=record["linkedSimulations"],
            agents=record["agents"],
            tools=record["tools"],
            data_sources=record["dataSources"],
            environments=record["environments"],
            exceptions=record["exceptions"],
            impact=record["impact"],
            history=record["history"],
            logic=record["logic"],
            logic_code=record["logic_code"],
            logic_language=record["logic_language"],
            snapshots={"v1": deepcopy(record)},
        )
        session.add(orm)
        session.commit()
        result = record
        _sync_version_row(result, actor=actor)
        return result
    finally:
        _close(session)


def update_policy(policy_id: str, data: PolicyUpdate, actor: str = "api") -> Optional[dict]:
    """Update a policy and return the new version, or None if not found."""
    session = _get_session()
    try:
        row = session.get(PolicyORM, policy_id)
        if row is None:
            return None

        changed_fields: list[str] = []
        if data.name is not None and data.name != row.name:
            row.name = data.name
            changed_fields.append("name")
        if data.mode is not None and data.mode != row.mode:
            changed_fields.append(f"mode {row.mode} → {data.mode}")
            row.mode = data.mode
        if data.status is not None:
            row.status = data.status
        if data.scope is not None:
            row.scope = data.scope
        if data.owner is not None:
            row.owner = data.owner
        if data.description is not None:
            row.description = data.description
        if data.agents is not None:
            row.agents = data.agents
        if data.tools is not None:
            row.tools = data.tools
        if data.data_sources is not None:
            row.data_sources = data.data_sources
        if data.environments is not None:
            row.environments = data.environments
        if data.exceptions is not None:
            row.exceptions = data.exceptions
        if data.logic_code is not None:
            row.logic_code = data.logic_code
            lang = data.logic_language or row.logic_language
            row.logic_language = lang
            row.logic = _tokenise(data.logic_code, lang)
            changed_fields.append("logic updated")

        # Bump version + append history
        new_ver = _bump_version(row.version)
        row.version = new_ver
        now_f = _now_full()
        row.updated = "just now"
        row.updated_full = now_f
        change_summary = "; ".join(changed_fields) if changed_fields else "Updated."

        # Ensure history is mutable and mark as modified
        if row.history is None:
            row.history = []
        row.history = [
            {
                "version": new_ver,
                "by": actor,
                "when": now_f,
                "change": change_summary,
            }
        ] + row.history
        flag_modified(row, "history")

        # Save snapshot before commit
        if row.snapshots is None:
            row.snapshots = {}
        row.snapshots[new_ver] = deepcopy(_to_dict(row))
        flag_modified(row, "snapshots")

        session.commit()
        result = _to_dict(row)
        _sync_version_row(result, actor=actor)
        return result
    finally:
        _close(session)


def delete_policy(policy_id: str) -> bool:
    """Delete a policy. Return True if found and deleted, False otherwise."""
    session = _get_session()
    try:
        row = session.get(PolicyORM, policy_id)
        if row is None:
            return False
        session.delete(row)
        session.commit()
        return True
    finally:
        _close(session)


def duplicate_policy(policy_id: str, actor: str = "api") -> Optional[dict]:
    """Create a copy of an existing policy with a new ID."""
    session = _get_session()
    try:
        src = session.get(PolicyORM, policy_id)
        if src is None:
            return None

        pid = str(uuid.uuid4())[:8]
        now_d = _now_display()
        now_f = _now_full()

        copy = PolicyORM(
            policy_id=pid,
            name=f"{src.name} (Copy)",
            version="v1",
            type=src.type,
            mode="Monitor",
            status="Active",
            scope=src.scope,
            owner=src.owner,
            created_by=actor,
            created=now_d,
            updated="just now",
            updated_full=now_f,
            description=src.description,
            affected_assets=0,
            related_alerts=0,
            linked_sims=0,
            agents=src.agents or [],
            tools=src.tools or [],
            data_sources=src.data_sources or [],
            environments=src.environments or [],
            exceptions=src.exceptions or [],
            impact={"blocked": 0, "flagged": 0, "unchanged": 0, "total": 0},
            history=[{
                "version": "v1",
                "by": actor,
                "when": now_f,
                "change": f"Duplicated from {src.name} {src.version}.",
            }],
            logic=src.logic or [],
            logic_code=src.logic_code,
            logic_language=src.logic_language,
            snapshots={"v1": None},  # will be populated below
        )

        session.add(copy)
        session.flush()

        # Save snapshot
        copy.snapshots = {"v1": deepcopy(_to_dict(copy))}
        session.commit()
        return _to_dict(copy)
    finally:
        _close(session)


def restore_policy(policy_id: str, target_version: str, actor: str = "api") -> Optional[dict]:
    """Restore a policy to a prior version snapshot, creating a new version entry."""
    session = _get_session()
    try:
        row = session.get(PolicyORM, policy_id)
        if row is None:
            return None

        snaps = row.snapshots or {}
        snap = snaps.get(target_version)
        if snap is None:
            return None

        # Restore fields from snapshot
        restored_snap = deepcopy(snap)
        new_ver = _bump_version(row.version)
        now_f = _now_full()

        row.name = restored_snap["name"]
        row.mode = restored_snap["mode"]
        row.status = restored_snap["status"]
        row.scope = restored_snap["scope"]
        row.owner = restored_snap["owner"]
        row.description = restored_snap["description"]
        row.agents = restored_snap.get("agents", [])
        row.tools = restored_snap.get("tools", [])
        row.data_sources = restored_snap.get("dataSources", [])
        row.environments = restored_snap.get("environments", [])
        row.exceptions = restored_snap.get("exceptions", [])
        row.logic_code = restored_snap["logic_code"]
        row.logic_language = restored_snap["logic_language"]
        row.logic = restored_snap.get("logic", [])

        row.version = new_ver
        row.updated = "just now"
        row.updated_full = now_f

        # Ensure history is mutable and mark as modified
        if row.history is None:
            row.history = []
        row.history = [
            {
                "version": new_ver,
                "by": actor,
                "when": now_f,
                "change": f"Restored from {target_version}.",
            }
        ] + row.history
        flag_modified(row, "history")

        if row.snapshots is None:
            row.snapshots = {}
        row.snapshots[new_ver] = deepcopy(_to_dict(row))
        flag_modified(row, "snapshots")

        session.commit()
        return _to_dict(row)
    finally:
        _close(session)


def list_restorable_versions(policy_id: str) -> list[str]:
    """Return version strings that can be restored (all except current)."""
    session = _get_session()
    try:
        row = session.get(PolicyORM, policy_id)
        if row is None:
            return []
        snaps = row.snapshots or {}
        current_ver = row.version
        return [v for v in snaps if v != current_ver]
    finally:
        _close(session)


# ── Seed helper (used by seed.py) ─────────────────────────────────────────────

def create_policy_raw(raw: dict, actor: str = "seed") -> dict:
    """Insert a policy from a raw dict — used ONLY by seed.py. No version bumping."""
    session = _get_session()
    try:
        orm = PolicyORM(
            policy_id=raw["id"],
            name=raw["name"],
            version=raw["version"],
            type=raw["type"],
            mode=raw["mode"],
            status=raw["status"],
            scope=raw["scope"],
            owner=raw["owner"],
            created_by=raw.get("createdBy", ""),
            created=raw.get("created", ""),
            updated=raw.get("updated", ""),
            updated_full=raw.get("updatedFull", ""),
            description=raw.get("description", ""),
            affected_assets=raw.get("affectedAssets", 0),
            related_alerts=raw.get("relatedAlerts", 0),
            linked_sims=raw.get("linkedSimulations", 0),
            agents=raw.get("agents", []),
            tools=raw.get("tools", []),
            data_sources=raw.get("dataSources", []),
            environments=raw.get("environments", []),
            exceptions=raw.get("exceptions", []),
            impact=raw.get("impact", {}),
            history=raw.get("history", []),
            logic=raw.get("logic", []),
            logic_code=raw.get("logic_code", ""),
            logic_language=raw.get("logic_language", "rego"),
            snapshots={raw["version"]: deepcopy(raw)},
        )
        session.add(orm)
        session.commit()
        return _to_dict(orm)
    finally:
        _close(session)
