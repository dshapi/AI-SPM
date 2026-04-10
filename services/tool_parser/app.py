"""
Tool Parser — sanitizes and validates tool output before the agent sees it.

Prevents tool results from being used as an indirect prompt injection vector.
Applies:
1. Direct injection pattern detection (regex)
2. Base64/hex/URL-encoded injection detection
3. Output schema validation (known tools have expected output shapes)
4. Recursive sanitization of nested dicts/lists/strings
"""
from __future__ import annotations
import base64
import binascii
import logging
import re
import urllib.parse
from platform_shared.base_service import ConsumerService
from platform_shared.models import ToolResult, ToolObservation
from platform_shared.topics import topics_for_tenant
from platform_shared.audit import emit_audit
from platform_shared.kafka_utils import safe_send, send_event

log = logging.getLogger("tool-parser")

# ─────────────────────────────────────────────────────────────────────────────
# Injection patterns
# ─────────────────────────────────────────────────────────────────────────────

_INJECTION_RE = re.compile(
    r"(ignore\s+(all\s+)?previous\s+instructions"
    r"|developer\s+message"
    r"|system\s+prompt"
    r"|act\s+as\s+if"
    r"|pretend\s+you\s+are"
    r"|you\s+are\s+now\s+(?!a\s+helpful)"
    r"|new\s+instructions?\s*:"
    r"|override\s+(your\s+)?instructions?"
    r"|disregard\s+(the\s+)?context"
    r"|forget\s+everything"
    r"|jailbreak"
    r"|do\s+anything\s+now)",
    re.IGNORECASE,
)

# ─────────────────────────────────────────────────────────────────────────────
# Known tool output schemas (allowed top-level keys)
# ─────────────────────────────────────────────────────────────────────────────

_TOOL_SCHEMAS: dict[str, set[str]] = {
    "calendar.read":    {"date", "range", "events"},
    "calendar.write":   {"status", "event_id", "title", "time", "created_at"},
    "gmail.send_email": {"status", "message_id", "to", "subject", "sent_at", "note"},
    "gmail.read":       {"messages", "total"},
    "file.read":        {"path", "content", "size_bytes", "last_modified"},
    "file.write":       {"status", "path", "bytes_written", "note"},
    "security.review":  {"status", "ticket_id", "details", "queue_time", "estimated_review_hours"},
    "db.query":         {"status", "query", "rows", "row_count", "note"},
    "web.search":       {"query", "results", "total_results"},
}


# ─────────────────────────────────────────────────────────────────────────────
# Sanitization logic
# ─────────────────────────────────────────────────────────────────────────────

def _try_decode_b64(s: str) -> str | None:
    """Attempt base64 decode. Returns decoded string if injection found, else None."""
    try:
        padding = "=" * (-len(s) % 4)
        decoded = base64.b64decode(s + padding).decode("utf-8", errors="ignore")
        if _INJECTION_RE.search(decoded):
            return decoded
    except (binascii.Error, ValueError):
        pass
    return None


def _try_decode_hex(s: str) -> str | None:
    """Attempt hex decode for short hex-like strings."""
    if re.match(r"^[0-9a-fA-F]{20,}$", s):
        try:
            decoded = bytes.fromhex(s).decode("utf-8", errors="ignore")
            if _INJECTION_RE.search(decoded):
                return decoded
        except ValueError:
            pass
    return None


def _try_decode_url(s: str) -> str | None:
    """URL-decode and check for injection."""
    try:
        decoded = urllib.parse.unquote(s)
        if decoded != s and _INJECTION_RE.search(decoded):
            return decoded
    except Exception:
        pass
    return None


def _sanitize_string(s: str, notes: list[str]) -> str:
    """Sanitize a single string value. Mutates notes list."""
    # Direct match
    if _INJECTION_RE.search(s):
        notes.append("direct_injection_redacted")
        return "[redacted-injection]"

    # Base64 encoded injection
    decoded_b64 = _try_decode_b64(s)
    if decoded_b64 is not None:
        notes.append("base64_encoded_injection_redacted")
        return "[redacted-encoded-injection:base64]"

    # Hex encoded injection
    decoded_hex = _try_decode_hex(s)
    if decoded_hex is not None:
        notes.append("hex_encoded_injection_redacted")
        return "[redacted-encoded-injection:hex]"

    # URL encoded injection
    decoded_url = _try_decode_url(s)
    if decoded_url is not None:
        notes.append("url_encoded_injection_redacted")
        return "[redacted-encoded-injection:url]"

    return s


def _sanitize_value(val: object, notes: list[str], depth: int = 0) -> object:
    """Recursively sanitize a value. Max depth 10 to prevent unbounded recursion."""
    if depth > 10:
        return val

    if isinstance(val, str):
        return _sanitize_string(val, notes)

    if isinstance(val, dict):
        return {k: _sanitize_value(v, notes, depth + 1) for k, v in val.items()}

    if isinstance(val, list):
        return [_sanitize_value(item, notes, depth + 1) for item in val]

    return val  # int, float, bool, None — pass through


def _sanitize_output(output: dict, notes: list[str]) -> dict:
    """Sanitize all values in the tool output dict."""
    return {k: _sanitize_value(v, notes) for k, v in output.items()}


def _validate_schema(tool_name: str, output: dict, violations: list[str]) -> None:
    """Check output keys against known schema. Records violations but doesn't block."""
    expected = _TOOL_SCHEMAS.get(tool_name)
    if not expected:
        return  # Unknown tool — no schema to validate against

    extra_keys = set(output.keys()) - expected
    if extra_keys:
        violations.append(f"unexpected_keys:{','.join(sorted(extra_keys))}")

    # Check for missing required keys (optional enforcement)
    # For now: log only, don't block
    if extra_keys:
        log.warning(
            "Tool schema violation: tool=%s extra_keys=%s",
            tool_name, extra_keys,
        )


class ToolParser(ConsumerService):
    service_name = "tool-parser"

    def __init__(self):
        t = topics_for_tenant("t1")
        super().__init__([t.tool_result, t.freeze_control], "cpm-tool-parser")

    def handle(self, payload: dict) -> None:
        if "scope" in payload:
            return

        result = ToolResult(**payload)
        topics = topics_for_tenant(result.tenant_id)

        sanitization_notes: list[str] = []
        schema_violations: list[str] = []

        # Sanitize output
        clean_output = _sanitize_output(result.output or {}, sanitization_notes)

        # Schema validation
        _validate_schema(result.tool_name, clean_output, schema_violations)

        # Build observation
        obs = ToolObservation(
            event_id=result.event_id,
            tenant_id=result.tenant_id,
            user_id=result.user_id,
            session_id=result.session_id,
            tool_name=result.tool_name,
            observation={
                "status": result.status,
                "output": clean_output,
                "error": result.error,
                "execution_ms": result.execution_ms,
            },
            sanitization_notes=sanitization_notes,
            schema_violations=schema_violations,
        )

        send_event(
            self.producer, topics.tool_observation, obs,
            event_type="tool.observation",
            source_service="tool-parser",
        )

        emit_audit(
            result.tenant_id, self.service_name, "tool_output_parsed",
            event_id=result.event_id, principal=result.user_id,
            session_id=result.session_id,
            correlation_id=result.event_id,
            details={
                "tool_name": result.tool_name,
                "sanitization_notes": sanitization_notes,
                "schema_violations": schema_violations,
            },
        )


if __name__ == "__main__":
    ToolParser().run()
