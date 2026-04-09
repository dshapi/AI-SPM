"""
services/audit_service.py
──────────────────────────
Async-compatible wrapper around platform_shared.audit.

platform_shared.emit_audit is synchronous (fire-and-forget Kafka).
We run it in a thread pool executor so it doesn't block the FastAPI
event loop. Failures are swallowed — audit must never crash business logic.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class AuditService:
    """
    Injectable audit emitter bound to a tenant and service component.

    Args:
        tenant_id: Tenant scope for audit events.
        component: Service name stamped on every event.
    """

    def __init__(self, tenant_id: str, component: str = "agent-orchestrator"):
        self.tenant_id = tenant_id
        self.component = component

    async def emit(
        self,
        event_type: str,
        *,
        session_id: Optional[str] = None,
        principal: Optional[str] = None,
        severity: str = "info",
        details: Optional[dict] = None,
        ttp_codes: Optional[List[str]] = None,
        event_id: Optional[str] = None,
    ) -> None:
        """Emit a standard audit event (non-blocking)."""
        try:
            from platform_shared.audit import emit_audit
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                lambda: emit_audit(
                    tenant_id=self.tenant_id,
                    component=self.component,
                    event_type=event_type,
                    event_id=event_id,
                    principal=principal,
                    session_id=session_id,
                    details=details or {},
                    severity=severity,
                    ttp_codes=ttp_codes or [],
                ),
            )
        except Exception as exc:
            # Audit failure must never propagate
            logger.warning("AuditService.emit failed: %s", exc)

    async def security_alert(
        self,
        event_type: str,
        ttp_codes: List[str],
        *,
        session_id: Optional[str] = None,
        principal: Optional[str] = None,
        details: Optional[dict] = None,
        event_id: Optional[str] = None,
    ) -> None:
        """Emit a critical-severity security alert."""
        await self.emit(
            event_type,
            session_id=session_id,
            principal=principal,
            severity="critical",
            details=details,
            ttp_codes=ttp_codes,
            event_id=event_id,
        )
