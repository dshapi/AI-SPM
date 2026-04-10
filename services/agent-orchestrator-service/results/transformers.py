# results/transformers.py
"""
results/transformers.py
────────────────────────
Pure transformation functions: Kafka/DB events → SessionResults.

Python port of ui/src/lib/sessionResults.js (commit 0660663).
No I/O, no async — call from ResultsService after fetching events.

Functions:
  canonicalise(event)            — normalise raw event_type to canonical form
  transform_session_events(events) — convert event list → SessionResults
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from results.schemas import (
    OutputSummary,
    PolicyImpact,
    RecommendationItem,
    RiskAnalysis,
    SessionResults,
    SessionResultsMeta,
    TraceStep,
)


# ── Canonical event type map ──────────────────────────────────────────────────
# Policy events are handled specially (split by payload.decision).

_POLICY_EVENT_TYPES: Set[str] = {
    "policy.decision",
    "policy.evaluated",
    "policy.enforced",
}

_RAW_TO_CANONICAL: Dict[str, str] = {
    # orchestrator native
    "prompt.received":    "prompt.received",
    "risk.calculated":    "risk.calculated",
    "session.created":    "session.created",
    "session.blocked":    "session.blocked",
    "session.completed":  "session.completed",
    "llm.response":       "agent.response.ready",
    "output.scanned":     "output.scanned",
    # legacy pipeline vocabulary
    "risk.scored":        "risk.calculated",
    "risk.enriched":      "risk.enriched",
    "posture.enriched":   "risk.enriched",
    "tool.result":        "tool.completed",
    "tool.invoked":       "tool.invoked",
    "tool.observed":      "tool.observed",
    "output.generated":   "output.generated",
    "audit.logged":       "audit.logged",
    "session.started":    "session.started",
    "session.failed":     "session.failed",
    "context.retrieved":  "context.retrieved",
}

_TERMINAL_TYPES: Set[str] = {"session.completed", "session.blocked", "session.failed"}


def canonicalise(event: Dict[str, Any]) -> str:
    """
    Return the canonical event_type string for an event dict.

    Policy events are split by payload.decision (allow / block / escalate).
    Unknown types are returned verbatim.
    """
    raw: str = event.get("event_type", "")
    if raw in _POLICY_EVENT_TYPES:
        decision = ""
        payload = event.get("payload")
        if isinstance(payload, dict):
            decision = (payload.get("decision") or "").lower()
        elif isinstance(payload, str):
            try:
                decision = (json.loads(payload).get("decision") or "").lower()
            except (json.JSONDecodeError, AttributeError):
                pass
        if decision == "block":
            return "policy.blocked"
        if decision == "escalate":
            return "policy.escalated"
        return "policy.allowed"
    return _RAW_TO_CANONICAL.get(raw, raw)


def _parse_payload(event: Dict[str, Any]) -> Dict[str, Any]:
    """Return event payload as a dict (handles JSON string or dict)."""
    p = event.get("payload", {})
    if isinstance(p, str):
        try:
            return json.loads(p)
        except (json.JSONDecodeError, ValueError):
            return {}
    return p if isinstance(p, dict) else {}


def _parse_ts(ts: Any) -> Optional[datetime]:
    if not ts:
        return None
    if isinstance(ts, datetime):
        return ts
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt
    except (ValueError, TypeError):
        return None


def _build_recommendations(
    signals: List[str],
    decision: str,
    risk_score: float,
    output_verdict: Optional[str],
    tools_blocked: bool,
    output_flagged: bool,
    pii_redacted: bool,
) -> List[RecommendationItem]:
    """
    17-rule deterministic recommendations engine.
    Evaluated in priority order (urgent → high → medium → low).
    Each rule fires at most once per session.
    """
    recs: List[RecommendationItem] = []
    fired: Set[str] = set()

    def add(rec_id: str, priority: str, title: str, detail: str, action: str) -> None:
        if rec_id not in fired:
            fired.add(rec_id)
            recs.append(RecommendationItem(
                id=rec_id, priority=priority, title=title, detail=detail, action=action,
            ))

    sig_set = {s.lower() for s in signals}

    # ── Urgent ──────────────────────────────────────────────────────────────
    if "injection_detected" in sig_set or "prompt_injection" in sig_set:
        add("injection-detected", "urgent",
            "Prompt Injection Detected",
            "A prompt injection attempt was identified. Block and audit immediately.",
            "Escalate to security team and block this agent configuration.")

    if "jailbreak" in sig_set or "jailbreak_attempt" in sig_set:
        add("jailbreak-attempt", "urgent",
            "Jailbreak Attempt Detected",
            "The prompt attempts to override system instructions.",
            "Harden system prompt and add injection guard layer.")

    if "pii_exfiltration" in sig_set or "data_exfiltration" in sig_set:
        add("pii-exfiltration", "urgent",
            "PII Exfiltration Attempt",
            "Agent attempted to extract personally identifiable information.",
            "Block agent, rotate credentials, notify DPO.")

    # ── High ────────────────────────────────────────────────────────────────
    if decision == "allow" and risk_score >= 0.7:
        add("upgrade-to-block", "high",
            "Consider Upgrading to Block",
            f"Risk score {risk_score:.2f} is high but policy allowed. Review threshold.",
            "Lower the block threshold or add a manual escalation step.")

    if "role_escalation" in sig_set or "privilege_escalation" in sig_set:
        add("role-escalation", "high",
            "Role Escalation Detected",
            "Agent requested permissions beyond its assigned role.",
            "Audit role bindings and apply least-privilege constraints.")

    if tools_blocked:
        add("tool-blocked", "high",
            "Tool Invocation Blocked",
            "One or more tool calls were denied by policy.",
            "Review tool ACL and adjust agent's allowed tool set.")

    if risk_score >= 0.65:
        add("high-behavioral-risk", "high",
            "High Behavioral Risk Score",
            f"Behavioral risk score {risk_score:.2f} exceeds safe threshold.",
            "Add a human-in-the-loop approval gate for this agent.")

    if output_flagged:
        add("output-flagged", "high",
            "Output Security Flag",
            "The agent output triggered a security scan flag.",
            "Review output filter rules and tighten scan thresholds.")

    if "memory_denied" in sig_set or "memory_access_denied" in sig_set:
        add("memory-denied", "high",
            "Memory Access Denied",
            "Agent was denied access to memory/context store.",
            "Verify memory permissions and agent identity claims.")

    # ── Medium ──────────────────────────────────────────────────────────────
    if risk_score >= 0.5 and decision == "allow":
        add("tighten-threshold", "medium",
            "Consider Tightening Block Threshold",
            "Session was allowed but risk score is in medium range.",
            "Review policy thresholds for this agent class.")

    if output_verdict == "flag" and not output_flagged:
        add("lower-flag-threshold", "medium",
            "Output Flagged at Low Severity",
            "Output was flagged but not blocked — consider tighter controls.",
            "Lower the output flag threshold for sensitive agents.")

    if "schema_violation" in sig_set:
        add("schema-violation", "medium",
            "Schema Violation in Payload",
            "Event payload contained unexpected or malformed fields.",
            "Validate agent output schema and add input sanitisation.")

    if "tool_approval_required" in sig_set:
        add("approval-gate", "medium",
            "Tool Approval Gate Triggered",
            "A tool invocation required human approval.",
            "Audit which tools require approval and streamline the workflow.")

    if "intent_drift" in sig_set:
        add("intent-drift", "medium",
            "Intent Drift Detected",
            "Agent behaviour deviated from its stated intent.",
            "Add intent alignment checks to the evaluation pipeline.")

    # ── Low ─────────────────────────────────────────────────────────────────
    if pii_redacted:
        add("pii-redacted", "low",
            "PII Was Redacted",
            "Personally identifiable information was detected and redacted.",
            "Confirm redaction rules cover all relevant PII types.")

    if decision == "allow" and risk_score < 0.3:
        add("policy-working", "low",
            "Policy Operating Normally",
            "Risk score is low and policy allowed the session.",
            "No action required. Continue monitoring.")

    if not recs:
        add("no-action", "low",
            "No Action Required",
            "No anomalies detected in this session.",
            "Continue monitoring and review periodically.")

    return recs


def transform_session_events(events: List[Dict[str, Any]]) -> SessionResults:
    """
    Convert a list of raw event dicts (from DB or EventStore) into a
    structured SessionResults object.

    Events may be in any order; they are sorted by timestamp then step.
    Duplicate event_types are collapsed — first occurrence after sorting wins.
    Returns partial=True when no terminal event (session.completed /
    session.blocked / session.failed) has been seen.
    """
    if not events:
        return SessionResults(
            meta=SessionResultsMeta(session_id="", event_count=0, partial=True),
            status="unknown",
            decision="unknown",
        )

    # ── 1. Sort by timestamp then step ──────────────────────────────────────
    def _sort_key(e: Dict[str, Any]):
        ts = _parse_ts(e.get("timestamp"))
        t = ts.timestamp() if ts else 0.0
        step = e.get("step", 0)
        return (t, step)

    sorted_events = sorted(events, key=_sort_key)

    # ── 2. Dedup by canonical event_type (first occurrence wins) ────────────
    seen_canonical: Set[str] = set()
    deduped: List[Dict[str, Any]] = []
    for ev in sorted_events:
        ctype = canonicalise(ev)
        if ctype not in seen_canonical:
            seen_canonical.add(ctype)
            deduped.append({**ev, "_canonical": ctype})

    # ── 3. Extract state from events ────────────────────────────────────────
    session_id = ""
    agent_id: Optional[str] = None
    risk_score: float = 0.0
    risk_tier: str = "unknown"
    signals: List[str] = []
    policy_decision: str = "unknown"
    policy_reason: str = ""
    policy_version: str = ""
    risk_score_at_decision: Optional[float] = None
    output_verdict: Optional[str] = None
    pii_types: List[str] = []
    secret_types: List[str] = []
    scan_notes: List[str] = []
    llm_model: Optional[str] = None
    response_length: Optional[int] = None
    llm_latency_ms: Optional[int] = None
    status: str = "unknown"
    terminal_reached: bool = False
    tools_blocked: bool = False
    output_flagged: bool = False
    pii_redacted: bool = False

    for ev in deduped:
        ctype = ev["_canonical"]
        p = _parse_payload(ev)
        sid = p.get("session_id") or ev.get("session_id") or ""
        if sid and not session_id:
            session_id = str(sid)
        if not agent_id:
            agent_id = p.get("agent_id")

        if ctype == "risk.calculated":
            risk_score = float(p.get("risk_score", 0.0))
            risk_tier = p.get("risk_tier", "unknown")
            signals = list(p.get("signals", []))

        elif ctype in ("policy.allowed", "policy.blocked", "policy.escalated"):
            policy_decision = {
                "policy.allowed": "allow",
                "policy.blocked": "block",
                "policy.escalated": "escalate",
            }[ctype]
            policy_reason = p.get("reason", "")
            policy_version = p.get("policy_version", "")
            risk_score_at_decision = p.get("risk_score_at_decision")

        elif ctype == "session.created":
            status = "active"

        elif ctype == "session.blocked":
            status = "blocked"
            terminal_reached = True

        elif ctype == "session.completed":
            final = p.get("final_status", "")
            if final in ("blocked", "failed"):
                status = final
            else:
                status = "completed"
            terminal_reached = True

        elif ctype == "session.failed":
            status = "failed"
            terminal_reached = True

        elif ctype in ("tool.completed", "tool.invoked"):
            if p.get("blocked") or p.get("status") == "blocked":
                tools_blocked = True

        elif ctype == "output.scanned":
            output_verdict = p.get("verdict")
            pii_types = list(p.get("pii_types", []))
            secret_types = list(p.get("secret_types", []))
            scan_notes = list(p.get("scan_notes", []))
            if output_verdict == "flag":
                output_flagged = True

        elif ctype == "agent.response.ready":
            llm_model = p.get("model")
            response_length = p.get("response_length")
            llm_latency_ms = p.get("latency_ms")

        if "pii_redacted" in signals or "pii_detected" in str(p):
            pii_redacted = True

    # ── 4. Build decision_trace ──────────────────────────────────────────────
    trace_steps: List[TraceStep] = []
    prev_ts: Optional[float] = None
    for i, ev in enumerate(deduped):
        ts = _parse_ts(ev.get("timestamp"))
        ts_epoch = ts.timestamp() if ts else None
        latency_ms: Optional[int] = None
        if ts_epoch is not None and prev_ts is not None:
            latency_ms = max(0, int((ts_epoch - prev_ts) * 1000))
        if ts_epoch is not None:
            prev_ts = ts_epoch

        trace_steps.append(TraceStep(
            step=i + 1,
            event_type=ev["_canonical"],
            status=ev.get("status", "ok"),
            summary=ev.get("summary", ""),
            timestamp=ts or datetime.now(timezone.utc),
            latency_ms=latency_ms,
            payload=_parse_payload(ev),
        ))

    # ── 5. Anomaly flags ─────────────────────────────────────────────────────
    anomaly_flags: List[str] = []
    sig_lower = {s.lower() for s in signals}
    if "injection_detected" in sig_lower or "prompt_injection" in sig_lower:
        anomaly_flags.append("injection")
    if "jailbreak" in sig_lower:
        anomaly_flags.append("jailbreak")
    if "pii_exfiltration" in sig_lower:
        anomaly_flags.append("pii_exfiltration")
    if output_flagged:
        anomaly_flags.append("output_flagged")

    # ── 6. Recommendations ───────────────────────────────────────────────────
    recommendations = _build_recommendations(
        signals=signals,
        decision=policy_decision,
        risk_score=risk_score,
        output_verdict=output_verdict,
        tools_blocked=tools_blocked,
        output_flagged=output_flagged,
        pii_redacted=pii_redacted,
    )

    # ── 7. Assemble result ───────────────────────────────────────────────────
    return SessionResults(
        meta=SessionResultsMeta(
            session_id=session_id,
            agent_id=agent_id,
            event_count=len(deduped),
            partial=not terminal_reached,
        ),
        status=status,
        decision=policy_decision,
        decision_trace=trace_steps,
        risk=RiskAnalysis(
            score=risk_score,
            tier=risk_tier,
            signals=signals,
            anomaly_flags=anomaly_flags,
        ),
        policy=PolicyImpact(
            decision=policy_decision,
            reason=policy_reason,
            policy_version=policy_version,
            risk_score_at_decision=risk_score_at_decision,
        ),
        output=OutputSummary(
            verdict=output_verdict,
            pii_types=pii_types,
            secret_types=secret_types,
            scan_notes=scan_notes,
            llm_model=llm_model,
            response_length=response_length,
            latency_ms=llm_latency_ms,
        ),
        recommendations=recommendations,
    )
