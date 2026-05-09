from platform_shared.posture_drift import compare_posture_snapshots


def _baseline():
    return {
        "snapshot_id": "base-001",
        "owner": "ai-platform",
        "model": {
            "provider": "anthropic",
            "name": "claude-sonnet",
            "version": "2026-04",
            "route": "primary",
            "retention_mode": "zero-retention",
            "logging_mode": "metadata-only",
            "region": "eu",
        },
        "tools": [
            {
                "name": "security.review",
                "category": "read",
                "schema_hash": "schema-a",
                "approval_required": False,
            }
        ],
        "identity": {
            "scopes": ["agent:read"],
            "token_audience": "aispm",
            "token_lifetime_minutes": 30,
        },
        "runtime": {
            "shell_access": False,
            "browser_profile_access": False,
            "container_socket_access": False,
            "privileged": False,
            "network_egress": ["spm-api.aispm.svc.cluster.local"],
            "filesystem_mounts": [{"path": "/tmp"}],
        },
        "rag_sources": [
            {
                "name": "approved-security-playbooks",
                "approved": True,
                "classification": "internal",
                "index_version": "v1",
                "embedding_model": "text-embedding-3-small",
                "trust_score": 0.9,
            }
        ],
        "guardrails": {
            "policy_bundle_hash": "policy-a",
            "approval_required_for_side_effects": True,
            "decision_thresholds": {"block": 0.7, "escalate": 0.3},
        },
    }


def test_unchanged_posture_has_no_findings():
    report = compare_posture_snapshots(_baseline(), _baseline())

    assert report.risk_level == "low"
    assert report.approval_required is False
    assert report.findings == []


def test_model_route_change_requires_review():
    current = _baseline()
    current["snapshot_id"] = "cur-001"
    current["model"] = {**current["model"], "provider": "openai"}

    report = compare_posture_snapshots(_baseline(), current)

    assert report.risk_level == "high"
    assert report.approval_required is True
    assert report.findings[0].drift_type == "model"
    assert "model.provider" in report.findings[0].changed_fields


def test_new_write_tool_is_high_risk():
    current = _baseline()
    current["snapshot_id"] = "cur-002"
    current["tools"] = [
        *current["tools"],
        {
            "name": "file.write",
            "category": "write",
            "command": "write_file",
            "approval_required": True,
        },
    ]

    report = compare_posture_snapshots(_baseline(), current)
    finding = report.findings[0]

    assert finding.drift_type == "tool"
    assert finding.risk_level == "high"
    assert "tools.file.write:added" in finding.changed_fields


def test_wildcard_identity_scope_is_critical():
    current = _baseline()
    current["snapshot_id"] = "cur-003"
    current["identity"] = {**current["identity"], "scopes": ["agent:read", "admin:*"]}

    report = compare_posture_snapshots(_baseline(), current)
    finding = next(item for item in report.findings if item.drift_type == "identity")

    assert finding.risk_level == "critical"
    assert finding.recommended_action == "disable_or_rollback_until_reapproved"
    assert "identity.scopes.+admin:*" in finding.changed_fields


def test_runtime_container_socket_mount_is_critical():
    current = _baseline()
    current["snapshot_id"] = "cur-004"
    current["runtime"] = {
        **current["runtime"],
        "container_socket_access": True,
        "filesystem_mounts": [{"path": "/var/run/docker.sock"}],
    }

    report = compare_posture_snapshots(_baseline(), current)
    finding = next(item for item in report.findings if item.drift_type == "runtime")

    assert finding.risk_level == "critical"
    assert "runtime.container_socket_access" in finding.changed_fields
    assert "runtime.filesystem_mounts" in finding.changed_fields


def test_unapproved_rag_source_requires_security_review():
    current = _baseline()
    current["snapshot_id"] = "cur-005"
    current["rag_sources"] = [
        *current["rag_sources"],
        {
            "name": "team-drive-dump",
            "approved": False,
            "classification": "confidential",
            "index_version": "v1",
        },
    ]

    report = compare_posture_snapshots(_baseline(), current)
    finding = next(item for item in report.findings if item.drift_type == "memory")

    assert finding.risk_level == "high"
    assert "memory.sources.team-drive-dump:added" in finding.changed_fields
    assert finding.approval_required is True


def test_policy_bundle_approval_disabled_is_critical():
    current = _baseline()
    current["snapshot_id"] = "cur-006"
    current["guardrails"] = {
        **current["guardrails"],
        "policy_bundle_hash": "policy-b",
        "approval_required_for_side_effects": False,
    }

    report = compare_posture_snapshots(_baseline(), current)
    finding = next(item for item in report.findings if item.drift_type == "guardrail")

    assert finding.risk_level == "critical"
    assert "guardrails.policy_bundle_hash" in finding.changed_fields
    assert "guardrails.approval_required_for_side_effects" in finding.changed_fields


def test_evidence_hash_is_stable_for_same_change():
    current = _baseline()
    current["model"] = {**current["model"], "provider": "openai"}

    first = compare_posture_snapshots(_baseline(), current)
    second = compare_posture_snapshots(_baseline(), current)

    assert first.findings[0].evidence_hash == second.findings[0].evidence_hash
