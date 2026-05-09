"""Agent posture drift comparison primitives.

The functions in this module compare an approved baseline snapshot with a
current runtime snapshot and return deterministic findings that other services
can persist, render, or turn into approval gates.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any, Iterable, Literal, Mapping


RiskLevel = Literal["low", "medium", "high", "critical"]
DriftType = Literal[
    "model",
    "tool",
    "identity",
    "runtime",
    "memory",
    "network",
    "guardrail",
    "provider",
]

_RISK_RANK: dict[str, int] = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}

_SENSITIVE_SCOPE_HINTS = (
    "*",
    "admin",
    "delete",
    "impersonate",
    "root",
    "secret",
    "send",
    "token",
    "write",
)

_HIGH_RISK_TOOL_HINTS = (
    "browser",
    "container",
    "db",
    "delete",
    "deploy",
    "email",
    "exec",
    "file.write",
    "filesystem",
    "kubernetes",
    "shell",
    "write",
)


@dataclass(frozen=True)
class DriftFinding:
    """Single posture-drift finding."""

    baseline_id: str
    current_snapshot_id: str
    drift_type: DriftType
    changed_fields: list[str]
    risk_level: RiskLevel
    approval_required: bool
    evidence_hash: str
    owner: str
    summary: str
    recommended_action: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DriftReport:
    """Aggregate comparison result for one baseline/current pair."""

    baseline_id: str
    current_snapshot_id: str
    risk_level: RiskLevel
    approval_required: bool
    findings: list[DriftFinding]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["findings"] = [finding.to_dict() for finding in self.findings]
        return data


def compare_posture_snapshots(
    baseline: Mapping[str, Any],
    current: Mapping[str, Any],
    *,
    owner: str | None = None,
) -> DriftReport:
    """Compare two agent posture snapshots.

    Parameters
    ----------
    baseline:
        Previously approved posture snapshot.
    current:
        Freshly observed runtime snapshot.
    owner:
        Optional owning team or service name. When omitted, the value is
        inferred from the snapshots and falls back to ``"unknown"``.
    """

    baseline_id = _snapshot_id(baseline, "baseline")
    current_id = _snapshot_id(current, "current")
    finding_owner = (
        owner
        or _string_or_none(current.get("owner"))
        or _string_or_none(baseline.get("owner"))
        or "unknown"
    )

    findings: list[DriftFinding] = []
    findings.extend(_compare_model_route(baseline, current, baseline_id, current_id, finding_owner))
    findings.extend(_compare_tools(baseline, current, baseline_id, current_id, finding_owner))
    findings.extend(_compare_identity(baseline, current, baseline_id, current_id, finding_owner))
    findings.extend(_compare_runtime(baseline, current, baseline_id, current_id, finding_owner))
    findings.extend(_compare_memory_sources(baseline, current, baseline_id, current_id, finding_owner))
    findings.extend(_compare_guardrails(baseline, current, baseline_id, current_id, finding_owner))

    risk_level = _max_risk([finding.risk_level for finding in findings])
    return DriftReport(
        baseline_id=baseline_id,
        current_snapshot_id=current_id,
        risk_level=risk_level,
        approval_required=any(finding.approval_required for finding in findings),
        findings=findings,
    )


def _compare_model_route(
    baseline: Mapping[str, Any],
    current: Mapping[str, Any],
    baseline_id: str,
    current_id: str,
    owner: str,
) -> list[DriftFinding]:
    fields = (
        "model_id",
        "model.provider",
        "model.name",
        "model.version",
        "model.route",
        "model.risk_tier",
        "model.retention_mode",
        "model.logging_mode",
        "model.region",
        "provider",
        "provider_route",
        "fallback_providers",
    )
    changed = _changed_paths(baseline, current, fields)
    if not changed:
        return []

    risk = "high" if any(_is_sensitive_model_field(path) for path in changed) else "medium"
    return [
        _finding(
            baseline_id,
            current_id,
            "model",
            changed,
            risk,
            "Model or provider route changed from the approved posture baseline.",
            owner,
        )
    ]


def _compare_tools(
    baseline: Mapping[str, Any],
    current: Mapping[str, Any],
    baseline_id: str,
    current_id: str,
    owner: str,
) -> list[DriftFinding]:
    baseline_tools = _index_named(_collect_items(baseline, "tools", "mcp.tools", "agent.tools"))
    current_tools = _index_named(_collect_items(current, "tools", "mcp.tools", "agent.tools"))

    changed: list[str] = []
    risk_levels: list[RiskLevel] = []
    for name in sorted(current_tools.keys() - baseline_tools.keys()):
        changed.append(f"tools.{name}:added")
        risk_levels.append(_tool_risk(current_tools[name]))

    for name in sorted(baseline_tools.keys() - current_tools.keys()):
        changed.append(f"tools.{name}:removed")
        risk_levels.append("low")

    watched_fields = (
        "description",
        "schema_hash",
        "command",
        "endpoint",
        "package_version",
        "capabilities",
        "category",
        "side_effect",
        "approval_required",
    )
    for name in sorted(baseline_tools.keys() & current_tools.keys()):
        for field in watched_fields:
            if _canonical(baseline_tools[name].get(field)) != _canonical(current_tools[name].get(field)):
                changed.append(f"tools.{name}.{field}")
                risk_levels.append(_changed_tool_field_risk(field, current_tools[name].get(field)))

    if not changed:
        return []

    return [
        _finding(
            baseline_id,
            current_id,
            "tool",
            changed,
            _max_risk(risk_levels),
            "MCP or agent tool surface changed after approval.",
            owner,
        )
    ]


def _compare_identity(
    baseline: Mapping[str, Any],
    current: Mapping[str, Any],
    baseline_id: str,
    current_id: str,
    owner: str,
) -> list[DriftFinding]:
    baseline_scopes = _scope_set(baseline)
    current_scopes = _scope_set(current)
    added_scopes = sorted(current_scopes - baseline_scopes)
    removed_scopes = sorted(baseline_scopes - current_scopes)

    changed = [f"identity.scopes.+{scope}" for scope in added_scopes]
    changed.extend(f"identity.scopes.-{scope}" for scope in removed_scopes)
    changed.extend(
        _changed_paths(
            baseline,
            current,
            (
                "identity.token_audience",
                "identity.token_lifetime_minutes",
                "identity.service_account",
                "service_account",
            ),
        )
    )

    if not changed:
        return []

    risk: RiskLevel = "medium"
    if any(_looks_sensitive_scope(scope) for scope in added_scopes):
        risk = "high"
    if any(scope == "*" or scope.endswith(":*") for scope in added_scopes):
        risk = "critical"

    return [
        _finding(
            baseline_id,
            current_id,
            "identity",
            changed,
            risk,
            "Identity, token, or authorization scope changed from the approved baseline.",
            owner,
        )
    ]


def _compare_runtime(
    baseline: Mapping[str, Any],
    current: Mapping[str, Any],
    baseline_id: str,
    current_id: str,
    owner: str,
) -> list[DriftFinding]:
    changed = _changed_paths(
        baseline,
        current,
        (
            "runtime.shell_access",
            "runtime.browser_profile_access",
            "runtime.container_socket_access",
            "runtime.privileged",
            "runtime.filesystem_mounts",
            "runtime.env_secret_refs",
            "runtime.network_egress",
            "network_egress",
            "filesystem_mounts",
        ),
    )
    if not changed:
        return []

    runtime = _as_mapping(current.get("runtime"))
    risk: RiskLevel = "medium"
    if (
        runtime.get("shell_access") is True
        or runtime.get("browser_profile_access") is True
        or _new_network_egress_is_external(baseline, current)
    ):
        risk = "high"
    if runtime.get("container_socket_access") is True or runtime.get("privileged") is True:
        risk = "critical"
    if _has_critical_mount(current):
        risk = "critical"

    return [
        _finding(
            baseline_id,
            current_id,
            "runtime",
            changed,
            risk,
            "Runtime boundary changed from the approved execution posture.",
            owner,
        )
    ]


def _compare_memory_sources(
    baseline: Mapping[str, Any],
    current: Mapping[str, Any],
    baseline_id: str,
    current_id: str,
    owner: str,
) -> list[DriftFinding]:
    baseline_sources = _index_named(_collect_items(baseline, "rag_sources", "memory.sources", "rag.sources"))
    current_sources = _index_named(_collect_items(current, "rag_sources", "memory.sources", "rag.sources"))

    changed: list[str] = []
    risk_levels: list[RiskLevel] = []

    for name in sorted(current_sources.keys() - baseline_sources.keys()):
        changed.append(f"memory.sources.{name}:added")
        risk_levels.append(_source_risk(current_sources[name]))

    for name in sorted(baseline_sources.keys() - current_sources.keys()):
        changed.append(f"memory.sources.{name}:removed")
        risk_levels.append("low")

    for name in sorted(baseline_sources.keys() & current_sources.keys()):
        for field in ("approved", "classification", "index_version", "embedding_model", "trust_score"):
            if _canonical(baseline_sources[name].get(field)) != _canonical(current_sources[name].get(field)):
                changed.append(f"memory.sources.{name}.{field}")
                risk_levels.append("high" if field == "approved" and not current_sources[name].get(field) else "medium")

    if not changed:
        return []

    return [
        _finding(
            baseline_id,
            current_id,
            "memory",
            changed,
            _max_risk(risk_levels),
            "RAG or memory source posture changed from the approved baseline.",
            owner,
        )
    ]


def _compare_guardrails(
    baseline: Mapping[str, Any],
    current: Mapping[str, Any],
    baseline_id: str,
    current_id: str,
    owner: str,
) -> list[DriftFinding]:
    changed = _changed_paths(
        baseline,
        current,
        (
            "guardrails.policy_bundle_hash",
            "guardrails.prompt_policy_version",
            "guardrails.output_policy_version",
            "guardrails.tool_policy_version",
            "guardrails.memory_policy_version",
            "guardrails.decision_thresholds",
            "guardrails.approval_required_for_side_effects",
            "policy_bundle_hash",
        ),
    )
    if not changed:
        return []

    risk: RiskLevel = "high"
    if "guardrails.approval_required_for_side_effects" in changed:
        current_guardrails = _as_mapping(current.get("guardrails"))
        if current_guardrails.get("approval_required_for_side_effects") is False:
            risk = "critical"

    return [
        _finding(
            baseline_id,
            current_id,
            "guardrail",
            changed,
            risk,
            "Guardrail or policy bundle changed after posture approval.",
            owner,
        )
    ]


def _finding(
    baseline_id: str,
    current_id: str,
    drift_type: DriftType,
    changed_fields: list[str],
    risk_level: RiskLevel,
    summary: str,
    owner: str,
) -> DriftFinding:
    approval_required = risk_level in {"medium", "high", "critical"}
    recommended_action = _recommended_action(risk_level)
    evidence = _evidence_hash(
        {
            "baseline_id": baseline_id,
            "current_snapshot_id": current_id,
            "drift_type": drift_type,
            "changed_fields": changed_fields,
            "risk_level": risk_level,
        }
    )
    return DriftFinding(
        baseline_id=baseline_id,
        current_snapshot_id=current_id,
        drift_type=drift_type,
        changed_fields=changed_fields,
        risk_level=risk_level,
        approval_required=approval_required,
        evidence_hash=evidence,
        owner=owner,
        summary=summary,
        recommended_action=recommended_action,
    )


def _recommended_action(risk_level: RiskLevel) -> str:
    if risk_level == "critical":
        return "disable_or_rollback_until_reapproved"
    if risk_level == "high":
        return "require_security_review_before_continued_operation"
    if risk_level == "medium":
        return "route_to_owner_for_reapproval"
    return "record_as_accepted_change"


def _snapshot_id(snapshot: Mapping[str, Any], fallback: str) -> str:
    value = snapshot.get("snapshot_id") or snapshot.get("id") or fallback
    return str(value)


def _string_or_none(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _changed_paths(
    baseline: Mapping[str, Any],
    current: Mapping[str, Any],
    paths: Iterable[str],
) -> list[str]:
    changed: list[str] = []
    for path in paths:
        if _canonical(_get_path(baseline, path)) != _canonical(_get_path(current, path)):
            changed.append(path)
    return changed


def _get_path(data: Mapping[str, Any], path: str) -> Any:
    value: Any = data
    for part in path.split("."):
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return value


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, set):
        return sorted(_canonical(item) for item in value)
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def _evidence_hash(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(_canonical(payload), sort_keys=True, separators=(",", ":"))
    return sha256(raw.encode("utf-8")).hexdigest()


def _max_risk(levels: Iterable[str]) -> RiskLevel:
    ordered = list(levels)
    if not ordered:
        return "low"
    return max(ordered, key=lambda level: _RISK_RANK.get(level, 0))  # type: ignore[return-value]


def _collect_items(snapshot: Mapping[str, Any], *paths: str) -> list[Any]:
    for path in paths:
        items = _get_path(snapshot, path)
        if items:
            if isinstance(items, Mapping):
                return [{"name": key, **_as_mapping(value)} for key, value in items.items()]
            if isinstance(items, list):
                return items
    return []


def _index_named(items: list[Any]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for item in items:
        if isinstance(item, str):
            indexed[item] = {"name": item}
            continue
        data = _as_mapping(item)
        name = data.get("name") or data.get("id") or data.get("source") or data.get("tool_name")
        if name:
            indexed[str(name)] = data
    return indexed


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _scope_set(snapshot: Mapping[str, Any]) -> set[str]:
    values: list[Any] = []
    for path in ("identity.scopes", "auth_context.scopes", "oauth_scopes", "service_account.scopes"):
        item = _get_path(snapshot, path)
        if isinstance(item, list):
            values.extend(item)
        elif isinstance(item, str):
            values.append(item)
    return {str(value) for value in values}


def _looks_sensitive_scope(scope: str) -> bool:
    lower = scope.lower()
    return any(hint in lower for hint in _SENSITIVE_SCOPE_HINTS)


def _tool_risk(tool: Mapping[str, Any]) -> RiskLevel:
    text = " ".join(str(value).lower() for value in tool.values())
    if "container socket" in text or "docker.sock" in text:
        return "critical"
    if any(hint in text for hint in _HIGH_RISK_TOOL_HINTS):
        return "high"
    return "medium"


def _changed_tool_field_risk(field: str, value: Any) -> RiskLevel:
    if field == "approval_required" and value is False:
        return "high"
    if field in {"command", "endpoint", "capabilities", "side_effect"}:
        return "high"
    if field == "category" and _tool_risk({"category": value}) == "high":
        return "high"
    return "medium"


def _source_risk(source: Mapping[str, Any]) -> RiskLevel:
    if source.get("approved") is False:
        return "high"
    classification = str(source.get("classification") or "").lower()
    if classification in {"restricted", "secret", "confidential"}:
        return "high"
    if str(source.get("owner") or "").lower() in {"external", "third-party", "untrusted"}:
        return "high"
    return "medium"


def _is_sensitive_model_field(path: str) -> bool:
    return path in {
        "model.provider",
        "model.name",
        "model.route",
        "model.risk_tier",
        "model.retention_mode",
        "model.logging_mode",
        "provider",
        "provider_route",
        "fallback_providers",
    }


def _new_network_egress_is_external(
    baseline: Mapping[str, Any],
    current: Mapping[str, Any],
) -> bool:
    baseline_egress = _egress_set(baseline)
    current_egress = _egress_set(current)
    added = current_egress - baseline_egress
    return any(target in {"*", "0.0.0.0/0", "internet"} or "." in target for target in added)


def _egress_set(snapshot: Mapping[str, Any]) -> set[str]:
    values: list[Any] = []
    for path in ("runtime.network_egress", "network_egress"):
        item = _get_path(snapshot, path)
        if isinstance(item, list):
            values.extend(item)
        elif isinstance(item, str):
            values.append(item)
    return {str(value).lower() for value in values}


def _has_critical_mount(snapshot: Mapping[str, Any]) -> bool:
    mounts: list[Any] = []
    for path in ("runtime.filesystem_mounts", "filesystem_mounts"):
        item = _get_path(snapshot, path)
        if isinstance(item, list):
            mounts.extend(item)
    for mount in mounts:
        data = _as_mapping(mount)
        target = str(data.get("path") or data.get("mount") or mount).lower()
        if target in {"/", "/host", "/var/run/docker.sock"} or "docker.sock" in target:
            return True
    return False
