"""
AI SPM — NIST AI RMF compliance evaluator.
Maps evaluation_rule names to functions that check CPM/SPM state.
"""
from __future__ import annotations
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Callable, Coroutine, Any, Dict

import requests
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spm.db.models import (
    AuditExport, ComplianceEvidence, ComplianceStatus,
    ModelRegistry, PostureSnapshot,
)

log = logging.getLogger("spm.compliance")

OPA_URL        = os.getenv("OPA_URL", "http://opa:8181")
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
OPA_POLICIES   = ["prompt_policy", "tool_policy", "output_policy", "memory_policy", "agent_policy"]


async def _rule_opa_policy_loaded(db: AsyncSession) -> ComplianceStatus:
    """Check all 5 OPA policies are loaded."""
    try:
        for policy in OPA_POLICIES:
            resp = requests.get(f"{OPA_URL}/v1/policies/{policy}", timeout=3.0)
            if resp.status_code != 200:
                return ComplianceStatus.partial
        return ComplianceStatus.satisfied
    except Exception:
        return ComplianceStatus.not_satisfied


async def _rule_model_approved_exists(db: AsyncSession) -> ComplianceStatus:
    """Check at least one model has an approved_by record."""
    result = await db.execute(
        select(func.count()).select_from(ModelRegistry)
        .where(ModelRegistry.approved_by.isnot(None))
    )
    count = result.scalar()
    return ComplianceStatus.satisfied if count > 0 else ComplianceStatus.partial


async def _rule_risk_fusion_active(db: AsyncSession) -> ComplianceStatus:
    """Check posture snapshots exist (indicates risk fusion is running)."""
    result = await db.execute(
        select(PostureSnapshot).order_by(PostureSnapshot.snapshot_at.desc()).limit(1)
    )
    snap = result.scalar_one_or_none()
    if snap is None:
        return ComplianceStatus.partial  # no data yet
    return ComplianceStatus.satisfied


async def _rule_models_have_risk_tier(db: AsyncSession) -> ComplianceStatus:
    """Check all registered models have a risk_tier set."""
    result = await db.execute(
        select(func.count()).select_from(ModelRegistry)
        .where(ModelRegistry.risk_tier.is_(None))
    )
    missing = result.scalar()
    return ComplianceStatus.satisfied if missing == 0 else ComplianceStatus.partial


async def _rule_snapshots_recent(db: AsyncSession) -> ComplianceStatus:
    """Check a snapshot was written in the last 10 minutes."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(minutes=10)
    result = await db.execute(
        select(func.count()).select_from(PostureSnapshot)
        .where(PostureSnapshot.snapshot_at >= cutoff)
    )
    count = result.scalar()
    return ComplianceStatus.satisfied if count > 0 else ComplianceStatus.partial


async def _rule_prometheus_reachable(db: AsyncSession) -> ComplianceStatus:
    """Check Prometheus is up."""
    try:
        resp = requests.get(f"{PROMETHEUS_URL}/-/healthy", timeout=3.0)
        return ComplianceStatus.satisfied if resp.status_code == 200 else ComplianceStatus.partial
    except Exception:
        return ComplianceStatus.not_satisfied


async def _rule_enforcement_action_exists(db: AsyncSession) -> ComplianceStatus:
    """Check at least one enforcement action in last 30 days."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=30)
    result = await db.execute(
        select(func.count()).select_from(AuditExport)
        .where(AuditExport.event_type.in_(["enforcement_block", "freeze_applied"]))
        .where(AuditExport.timestamp >= cutoff)
    )
    count = result.scalar()
    return ComplianceStatus.satisfied if count > 0 else ComplianceStatus.partial


RuleFunc = Callable[[AsyncSession], Coroutine[Any, Any, ComplianceStatus]]
RULE_MAP: Dict[str, RuleFunc] = {
    "opa_policy_loaded":         _rule_opa_policy_loaded,
    "model_approved_exists":     _rule_model_approved_exists,
    "risk_fusion_active":        _rule_risk_fusion_active,
    "models_have_risk_tier":     _rule_models_have_risk_tier,
    "snapshots_recent":          _rule_snapshots_recent,
    "prometheus_reachable":      _rule_prometheus_reachable,
    "enforcement_action_exists": _rule_enforcement_action_exists,
}


async def evaluate_all_controls(db: AsyncSession) -> None:
    """Re-evaluate all compliance controls and update their status in DB."""
    mapping_path = os.path.join(os.path.dirname(__file__), "nist_airm_mapping.json")
    with open(mapping_path) as f:
        controls_def = {c["category"]: c for c in json.load(f)}

    result = await db.execute(select(ComplianceEvidence))
    controls = result.scalars().all()

    for control in controls:
        rule_name = controls_def.get(control.category, {}).get("evaluation_rule")
        if rule_name and rule_name in RULE_MAP:
            new_status = await RULE_MAP[rule_name](db)
            control.status = new_status
            control.last_evaluated_at = datetime.now(tz=timezone.utc)

    await db.commit()
    log.info("Compliance evaluation complete — %d controls evaluated", len(controls))


def render_pdf(report: Dict) -> bytes:
    """Render compliance report to PDF via WeasyPrint."""
    from weasyprint import HTML

    template_path = os.path.join(os.path.dirname(__file__), "report_template.html")
    with open(template_path) as f:
        template = f.read()

    functions_html = ""
    for fn in report["functions"]:
        gaps_html = "".join(
            f"<li>{g['category']}: {g['control']} ({g['status']})</li>"
            for g in fn["gaps"]
        ) or "<li>None</li>"
        functions_html += f"""
        <div class="function">
            <h2>{fn['function']} — {fn['coverage_pct']}% coverage</h2>
            <p><strong>Gaps:</strong></p><ul>{gaps_html}</ul>
        </div>"""

    html = template.replace("{{generated_at}}", report["generated_at"])
    html = html.replace("{{overall_coverage_pct}}", str(report["overall_coverage_pct"]))
    html = html.replace("{{functions}}", functions_html)

    return HTML(string=html).write_pdf()
