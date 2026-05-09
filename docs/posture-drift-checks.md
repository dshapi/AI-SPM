# AI Agent Posture Drift Checks

AI-SPM needs to know when an approved agent, model route, tool surface, or RAG
source has moved outside the security boundary that was reviewed at onboarding.
Posture drift checks compare a baseline snapshot with the current observed
runtime state and produce deterministic findings that can be routed to an owner,
review queue, or policy gate.

## Snapshot Inputs

The comparison engine accepts dictionaries so it can be used by API routes,
database jobs, CI fixtures, or runtime observers without a database dependency.
A posture snapshot can include these sections:

| Section | Example fields | Why it matters |
| --- | --- | --- |
| `model` | provider, name, version, route, risk tier, retention mode, logging mode, region | Detects provider/model/region/logging changes after approval. |
| `tools` | name, category, schema hash, endpoint, command, capabilities, approval requirement | Detects new MCP tools, side-effect tools, endpoint changes, and schema drift. |
| `identity` | OAuth scopes, token audience, service account, token lifetime | Detects broader authorization or delegated token changes. |
| `runtime` | shell access, browser profile access, container socket, privileged mode, network egress, mounts | Detects escape-prone runtime boundary changes. |
| `rag_sources` or `memory.sources` | source name, approved flag, classification, index version, embedding model, trust score | Detects unapproved or high-sensitivity retrieval sources. |
| `guardrails` | policy bundle hash, prompt/output/tool policy versions, thresholds, approval settings | Detects policy weakening or unreviewed guardrail changes. |

## Output Finding Shape

Each finding includes:

| Field | Purpose |
| --- | --- |
| `baseline_id` | Approved posture snapshot being compared against. |
| `current_snapshot_id` | Current scan or observed runtime snapshot. |
| `drift_type` | `model`, `tool`, `identity`, `runtime`, `memory`, `guardrail`, `provider`, or `network`. |
| `changed_fields` | Bounded list of fields that moved from the baseline. |
| `risk_level` | `low`, `medium`, `high`, or `critical`. |
| `approval_required` | Whether owner/security re-approval is required. |
| `evidence_hash` | Stable hash of the compared evidence package. |
| `owner` | Accountable team or service owner. |
| `recommended_action` | `record_as_accepted_change`, `route_to_owner_for_reapproval`, `require_security_review_before_continued_operation`, or `disable_or_rollback_until_reapproved`. |

## Severity Guidance

| Drift signal | Default severity | Rationale |
| --- | --- | --- |
| Provider/model route, retention mode, logging mode, or fallback route changed | High | The data path and privacy/compliance boundary may have changed. |
| New write, shell, browser, deployment, database, email, Kubernetes, or filesystem tool | High | Side-effect tools can modify data, send messages, or widen blast radius. |
| Wildcard or administrator OAuth scope added | Critical | The agent can now act outside the approved authorization boundary. |
| Container socket, privileged runtime, host mount, or Docker socket access | Critical | These changes can collapse workload isolation. |
| External or wildcard network egress added | High | The agent can now reach a broader destination set. |
| Unapproved or restricted RAG source added | High | Context can introduce sensitive data or untrusted instructions. |
| Side-effect approval disabled | Critical | The human-in-the-loop safety boundary was weakened. |

## Example

```python
from platform_shared.posture_drift import compare_posture_snapshots

baseline = {
    "snapshot_id": "approved-2026-05-01",
    "owner": "ai-platform",
    "tools": [{"name": "security.review", "category": "read"}],
    "identity": {"scopes": ["agent:read"]},
}

current = {
    "snapshot_id": "scan-2026-05-09",
    "owner": "ai-platform",
    "tools": [
        {"name": "security.review", "category": "read"},
        {"name": "file.write", "category": "write", "approval_required": True},
    ],
    "identity": {"scopes": ["agent:read", "admin:*"]},
}

report = compare_posture_snapshots(baseline, current)
assert report.approval_required is True
```

The report can be persisted as compliance evidence, attached to an agent
inventory row, or used by a policy gate before an agent continues operation.

## Recommended Remediation Flow

1. For `low` findings, record the change as accepted operational drift.
2. For `medium` findings, route the change to the system owner for re-approval.
3. For `high` findings, require security review before continued operation.
4. For `critical` findings, disable, roll back, or freeze the affected agent until it is re-approved.

## Integration Path

The shared comparison engine is intentionally independent of FastAPI, SQLAlchemy,
Kafka, and Kubernetes. Suggested follow-up integrations:

1. Generate baseline snapshots when an agent or model route is approved.
2. Generate current snapshots from agent runtime metadata, MCP manifests, identity
   scopes, policy bundle hashes, and RAG source metadata.
3. Store `DriftReport` output as audit evidence and surface high/critical drift in
   the admin portal.
4. Add a policy gate that blocks or freezes agents when critical drift is detected.
