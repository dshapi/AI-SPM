"""
Output Guard — two-pass scanning of final responses before delivery.

Pass 1: Regex — SSN, credit card, email, phone, PEM keys, JWTs, connection strings
Pass 2: LLM semantic scan via guard_model /screen endpoint
OPA: decides block / redact / allow based on combined signals
"""
from __future__ import annotations
import logging
import re
import httpx
from platform_shared.base_service import ConsumerService
from platform_shared.config import get_settings
from platform_shared.models import FinalResponse
from platform_shared.topics import topics_for_tenant
from platform_shared.opa_client import get_opa_client
from platform_shared.audit import emit_audit, emit_security_alert
from platform_shared.kafka_utils import safe_send

log = logging.getLogger("output-guard")
settings = get_settings()

# ─────────────────────────────────────────────────────────────────────────────
# PII patterns
# ─────────────────────────────────────────────────────────────────────────────

_PII_PATTERNS = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),                          "ssn"),
    (re.compile(r"\b(?:\d[ -]*?){13,16}\b"),                         "credit_card"),
    (re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"), "email"),
    (re.compile(r"\b(\+?\d[\d\s\-().]{7,14}\d)\b"),                  "phone"),
    (re.compile(r"\b[A-Z]{1,2}\d{6,9}\b"),                           "passport"),
    (re.compile(r"\b\d{9}\b"),                                        "national_id"),
    (re.compile(r"\b(19|20)\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b"), "date_of_birth"),
]

# ─────────────────────────────────────────────────────────────────────────────
# Secret patterns
# ─────────────────────────────────────────────────────────────────────────────

_SECRET_PATTERNS = [
    (re.compile(r"(?i)api[_ -]?key\s*[:=]\s*\S+"),                   "api_key"),
    (re.compile(r"(?i)secret\s*[:=]\s*\S+"),                         "secret"),
    (re.compile(r"(?i)(?<!\w)token\s*[:=]\s*\S+"),                   "token"),
    (re.compile(r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----"),         "pem_private_key"),
    (re.compile(r"-----BEGIN\s+CERTIFICATE-----"),                    "pem_certificate"),
    (re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "jwt_token"),
    (re.compile(r"(?i)(mysql|postgres|postgresql|mongodb|redis|mssql)://[^\s]+"), "connection_string"),
    (re.compile(r"(?i)password\s*[:=]\s*\S+"),                       "password"),
    (re.compile(r"(?i)passwd\s*[:=]\s*\S+"),                         "password"),
    (re.compile(r"AKIA[0-9A-Z]{16}"),                                 "aws_access_key"),
    (re.compile(r"(?i)sk-[a-zA-Z0-9]{20,}"),                         "openai_api_key"),
    (re.compile(r"github_pat_[a-zA-Z0-9_]{20,}"),                    "github_pat"),
]


def _regex_scan(text: str) -> tuple[list[str], list[str]]:
    """
    Returns (pii_types_found, secret_types_found).
    """
    pii_found = []
    for pattern, label in _PII_PATTERNS:
        if pattern.search(text):
            pii_found.append(label)

    secret_found = []
    for pattern, label in _SECRET_PATTERNS:
        if pattern.search(text):
            secret_found.append(label)

    return pii_found, secret_found


def _redact_pii(text: str) -> str:
    """Replace PII matches with [REDACTED] placeholders."""
    for pattern, label in _PII_PATTERNS:
        text = pattern.sub(f"[REDACTED:{label.upper()}]", text)
    return text


def _llm_scan(text: str) -> tuple[str, list[str]]:
    """
    Call guard_model /screen for semantic secret/PII detection.
    Returns (verdict: allow|flag|block, categories).
    Falls back gracefully if unavailable.
    """
    if not settings.output_guard_llm_enabled:
        return "allow", []
    try:
        resp = httpx.post(
            f"{settings.output_guard_llm_url}/screen",
            json={"text": text, "context": "tool_output"},
            timeout=settings.output_guard_llm_timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("verdict", "allow"), data.get("categories", [])
    except httpx.TimeoutException:
        log.warning("Guard model timeout in output guard — skipping LLM scan")
        return "allow", []
    except Exception as e:
        log.warning("Guard model error in output guard: %s — skipping LLM scan", e)
        return "allow", []


class OutputGuard(ConsumerService):
    service_name = "output-guard"

    def __init__(self):
        t = topics_for_tenant("t1")
        super().__init__([t.final_response, t.freeze_control], "cpm-output-guard")
        self._opa = get_opa_client()

    def handle(self, payload: dict) -> None:
        if "scope" in payload:
            return

        resp = FinalResponse(**payload)
        scan_notes: list[str] = []

        # ── Pass 1: Regex scan ─────────────────────────────────────────────
        pii_types, secret_types = _regex_scan(resp.text)
        contains_pii = len(pii_types) > 0
        contains_secret = len(secret_types) > 0

        if pii_types:
            scan_notes.extend([f"pii:{t}" for t in pii_types])
        if secret_types:
            scan_notes.extend([f"secret:{t}" for t in secret_types])

        # ── Pass 2: LLM semantic scan ──────────────────────────────────────
        llm_verdict, llm_categories = _llm_scan(resp.text)
        if llm_categories:
            scan_notes.extend([f"llm:{c}" for c in llm_categories])
            if llm_verdict == "block":
                contains_secret = True
            elif llm_verdict == "flag" and any("S1" in c or "S11" in c for c in llm_categories):
                contains_secret = True
            elif llm_verdict == "flag":
                contains_pii = True

        # ── OPA output policy decision ────────────────────────────────────
        opa_result = self._opa.eval(
            "/v1/data/spm/output/allow",
            {
                "contains_pii": contains_pii,
                "contains_secret": contains_secret,
                "pii_types": pii_types,
                "secret_types": secret_types,
                "llm_verdict": llm_verdict,
                "llm_categories": llm_categories,
            },
        )
        decision = opa_result.get("decision", "allow")

        # ── Apply decision ────────────────────────────────────────────────
        if decision == "block":
            if contains_secret:
                emit_security_alert(
                    resp.tenant_id, self.service_name, "secret_in_output",
                    ttp_codes=["AML.T0048"],
                    event_id=resp.event_id, principal=resp.user_id,
                    session_id=resp.session_id,
                    details={"secret_types": secret_types, "llm_categories": llm_categories},
                )
            resp.text = "Response blocked by output policy: sensitive content detected."
            resp.blocked = True
            resp.reason = opa_result.get("reason", "output blocked")
            scan_notes.append("action:blocked")

        elif decision == "redact":
            resp.text = _redact_pii(resp.text)
            resp.reason = opa_result.get("reason", "PII redacted")
            resp.pii_redacted = True
            scan_notes.append("action:pii_redacted")

        resp.output_scan_notes = scan_notes

        # Emit final response (in production: deliver to user-facing channel)
        import json
        print(resp.model_dump_json(indent=2))

        emit_audit(
            resp.tenant_id, self.service_name, "output_checked",
            event_id=resp.event_id, principal=resp.user_id,
            session_id=resp.session_id,
            severity="warning" if resp.blocked else "info",
            details={
                "blocked": resp.blocked,
                "pii_redacted": resp.pii_redacted,
                "scan_notes": scan_notes,
                "decision": decision,
            },
        )


if __name__ == "__main__":
    OutputGuard().run()
