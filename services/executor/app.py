"""
Executor — runs tools after OPA authorization.

Tool registry maps tool_name → (handler_fn, requires_human_approval).
Side-effect tools (send, write, delete) require human approval before execution.
Approval flow: emit to approval_request topic → wait for approval_result.
For demo: approval is auto-granted after logging. Replace with real approval workflow.
"""
from __future__ import annotations
import logging
import time
import uuid
from typing import Callable, Any

from platform_shared.base_service import ConsumerService
from platform_shared.models import ToolRequest, ToolResult, ApprovalRequest
from platform_shared.topics import topics_for_tenant
from platform_shared.opa_client import get_opa_client
from platform_shared.audit import emit_audit, emit_security_alert
from platform_shared.kafka_utils import safe_send

log = logging.getLogger("executor")


# ─────────────────────────────────────────────────────────────────────────────
# Tool implementations
# ─────────────────────────────────────────────────────────────────────────────

def _calendar_read(args: dict) -> dict:
    """Read calendar events for today."""
    return {
        "date": "today",
        "range": args.get("range", "today"),
        "events": [
            {
                "id": "evt-001",
                "title": "Architecture Review",
                "time": "10:00",
                "duration_min": 60,
                "attendees": ["engineering@company.com"],
                "location": "Conference Room B",
            },
            {
                "id": "evt-002",
                "title": "Security Sync",
                "time": "14:00",
                "duration_min": 30,
                "attendees": ["ciso@company.com", "security@company.com"],
                "location": "Virtual",
            },
        ],
    }


def _calendar_write(args: dict) -> dict:
    """Create a calendar event (requires approval)."""
    return {
        "status": "created",
        "event_id": f"evt-{uuid.uuid4().hex[:8]}",
        "title": args.get("title", "New Event"),
        "time": args.get("time", "TBD"),
        "created_at": int(time.time()),
    }


def _gmail_send(args: dict) -> dict:
    """Send an email (requires approval — side effect)."""
    return {
        "status": "simulated_send",
        "message_id": f"msg-{uuid.uuid4().hex[:12]}",
        "to": args.get("to", ""),
        "subject": args.get("subject", ""),
        "sent_at": int(time.time()),
        "note": "Production: replace with Gmail API call",
    }


def _gmail_read(args: dict) -> dict:
    """Read recent emails (read-only, no approval needed)."""
    return {
        "messages": [
            {
                "id": "msg-001",
                "from": "alice@company.com",
                "subject": "Project Nexus Update",
                "snippet": "Q3 milestones achieved...",
                "date": "today",
            }
        ],
        "total": 1,
    }


def _file_read(args: dict) -> dict:
    """Read a file (read-only)."""
    path = args.get("path", "/tmp/demo.txt")
    return {
        "path": path,
        "content": "Sample file content for demonstration purposes.",
        "size_bytes": 48,
        "last_modified": int(time.time()) - 3600,
    }


def _file_write(args: dict) -> dict:
    """Write to a file (requires approval — side effect)."""
    return {
        "status": "simulated_write",
        "path": args.get("path", "/tmp/output.txt"),
        "bytes_written": len(args.get("content", "")),
        "note": "Production: replace with real filesystem or storage API call",
    }


def _security_review(args: dict) -> dict:
    """Queue a request for security review (safe, no side effects)."""
    ticket_id = f"SEC-{uuid.uuid4().hex[:8].upper()}"
    return {
        "status": "queued",
        "ticket_id": ticket_id,
        "details": args,
        "queue_time": int(time.time()),
        "estimated_review_hours": 4,
    }


def _db_query(args: dict) -> dict:
    """Read-only database query (requires scope, no approval)."""
    return {
        "status": "ok",
        "query": args.get("query", "SELECT 1"),
        "rows": [],
        "row_count": 0,
        "note": "Production: replace with real database client",
    }


def _web_search(args: dict) -> dict:
    """Search the web (read-only, no approval)."""
    return {
        "query": args.get("query", ""),
        "results": [
            {"title": "Relevant result 1", "url": "https://example.com/1", "snippet": "..."},
            {"title": "Relevant result 2", "url": "https://example.com/2", "snippet": "..."},
        ],
        "total_results": 2,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Tool registry: tool_name → (handler, requires_approval)
# ─────────────────────────────────────────────────────────────────────────────

TOOL_REGISTRY: dict[str, tuple[Callable[[dict], dict], bool]] = {
    "calendar.read":     (_calendar_read,    False),
    "calendar.write":    (_calendar_write,   True),
    "gmail.send_email":  (_gmail_send,       True),
    "gmail.read":        (_gmail_read,       False),
    "file.read":         (_file_read,        False),
    "file.write":        (_file_write,       True),
    "security.review":   (_security_review,  False),
    "db.query":          (_db_query,         False),
    "web.search":        (_web_search,       False),
}


class Executor(ConsumerService):
    service_name = "executor"

    def __init__(self):
        t = topics_for_tenant("t1")
        super().__init__([t.tool_request, t.freeze_control], "cpm-executor")
        self._opa = get_opa_client()

    def _opa_check(self, req: ToolRequest) -> dict:
        return self._opa.eval(
            "/v1/data/spm/tools/allow",
            {
                "tool_name": req.tool_name,
                "posture_score": req.posture_score,
                "signals": req.signals,
                "intent": req.intent,
                "auth_context": req.auth_context.model_dump(),
                "requires_approval": req.requires_approval,
            },
        )

    def _emit_approval_request(self, req: ToolRequest, topics) -> ToolResult:
        """Emit an approval request and return a pending result."""
        approval_id = str(uuid.uuid4())
        approval = ApprovalRequest(
            approval_id=approval_id,
            event_id=req.event_id,
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            tool_name=req.tool_name,
            tool_args=req.tool_args,
            intent=req.intent,
            posture_score=req.posture_score,
        )
        safe_send(self.producer, topics.approval_request, approval.model_dump())
        emit_audit(
            req.tenant_id, self.service_name, "tool_approval_requested",
            event_id=req.event_id, principal=req.user_id,
            session_id=req.session_id,
            details={"tool_name": req.tool_name, "approval_id": approval_id, "intent": req.intent},
        )
        # For demo: auto-approve. In production, wait for approval_result topic.
        log.info(
            "Auto-approving tool=%s approval_id=%s (demo mode — replace with real approval flow)",
            req.tool_name, approval_id,
        )
        return None  # None = proceed with execution

    def handle(self, payload: dict) -> None:
        if "scope" in payload:
            return

        req = ToolRequest(**payload)
        topics = topics_for_tenant(req.tenant_id)
        t0 = time.time()

        # OPA authorization
        opa_result = self._opa_check(req)
        if opa_result.get("decision") != "allow":
            tool = ToolResult(
                event_id=req.event_id, tenant_id=req.tenant_id,
                user_id=req.user_id, session_id=req.session_id,
                tool_name=req.tool_name, status="blocked",
                error=opa_result.get("reason", "tool denied by policy"),
            )
            safe_send(self.producer, topics.tool_result, tool.model_dump())
            emit_audit(
                req.tenant_id, self.service_name, "tool_blocked",
                event_id=req.event_id, principal=req.user_id,
                session_id=req.session_id, severity="warning",
                details={"tool_name": req.tool_name, "reason": opa_result.get("reason"), "intent": req.intent},
            )
            return

        # Look up tool
        entry = TOOL_REGISTRY.get(req.tool_name)
        if entry is None:
            tool = ToolResult(
                event_id=req.event_id, tenant_id=req.tenant_id,
                user_id=req.user_id, session_id=req.session_id,
                tool_name=req.tool_name, status="error",
                error=f"tool '{req.tool_name}' not found in registry",
            )
            safe_send(self.producer, topics.tool_result, tool.model_dump())
            return

        handler_fn, needs_approval = entry

        # Human approval for side-effect tools
        if needs_approval or req.requires_approval:
            self._emit_approval_request(req, topics)
            # Demo: fall through to execution

        # Execute tool
        try:
            output = handler_fn(req.tool_args)
            tool = ToolResult(
                event_id=req.event_id, tenant_id=req.tenant_id,
                user_id=req.user_id, session_id=req.session_id,
                tool_name=req.tool_name, status="ok", output=output,
                execution_ms=int((time.time() - t0) * 1000),
            )
        except Exception as exc:
            log.error("Tool execution error: tool=%s error=%s", req.tool_name, exc, exc_info=True)
            tool = ToolResult(
                event_id=req.event_id, tenant_id=req.tenant_id,
                user_id=req.user_id, session_id=req.session_id,
                tool_name=req.tool_name, status="error",
                error=str(exc),
                execution_ms=int((time.time() - t0) * 1000),
            )

        safe_send(self.producer, topics.tool_result, tool.model_dump())
        emit_audit(
            req.tenant_id, self.service_name, "tool_executed",
            event_id=req.event_id, principal=req.user_id,
            session_id=req.session_id,
            details={
                "tool_name": req.tool_name,
                "status": tool.status,
                "intent": req.intent,
                "execution_ms": tool.execution_ms,
            },
        )


if __name__ == "__main__":
    Executor().run()
