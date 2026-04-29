#!/usr/bin/env python3
"""
deploy/scripts/split-by-tier.py

Split the rendered AISPM Helm chart into per-tier YAML files for the
phased-rollout flow in bootstrap-cluster.sh.

Tiers (applied in this order by the bootstrap script, with hard waits
between phases):

    infra        → ConfigMaps, Secrets, Services, RBAC, NetworkPolicies,
                   Istio config (Gateway, VirtualService, AuthZ, PeerAuth),
                   Kyverno policies, PVCs, Ingresses. Config only — no pods.
                   Applied first; no wait gate (nothing to be Ready for).

    data         → kafka, redis, spm-db StatefulSets. The data plane.
                   Wait gate: all 3 rollouts Ready.

    data-init    → db-seed Job, startup-orchestrator Job. Prep the data
                   plane (seed Postgres, create Kafka topics).
                   Wait gate: both Jobs Complete.

    platform     → 22 backend Deployments (api, spm-api, opa, guard-model,
                   processor, agent, executor, etc.). Everything that
                   talks to the data plane.
                   Wait gate: all Deployment rollouts Ready.

    compute      → flink-jobmanager StatefulSet + flink-taskmanager
                   Deployment. The Flink cluster.
                   Wait gate: both rollouts Ready.

    compute-init → flink-pyjob-submitter Job. Submits the CEP PyFlink
                   job to the running JobManager.
                   Wait gate: Job Complete.

    frontend     → ui Deployment. Last because it depends on the api/
                   spm-api Services from the platform tier.
                   Wait gate: rollout Ready.

Usage:
    python3 split-by-tier.py <rendered.yaml> <out_dir>

Outputs:
    <out_dir>/infra.yaml
    <out_dir>/data.yaml
    <out_dir>/data-init.yaml
    <out_dir>/platform.yaml
    <out_dir>/compute.yaml
    <out_dir>/compute-init.yaml
    <out_dir>/frontend.yaml

    Plus a JSON summary printed to stdout: {"infra": 32, "data": 5, ...}
    so the bootstrap script can echo per-tier counts.

Why a python script and not chart labels:
    Adding `aispm.io/tier` labels to all ~50 chart templates would be a
    large diff and would couple the chart to the bootstrap orchestration
    (the chart shouldn't have to know how it's applied). Keeping the tier
    map here keeps the chart pure and the orchestration logic in one
    place. If a future invocation goes through `helm install` directly
    (no bootstrap), the chart still works — just without phasing.
"""

import json
import os
import sys
import yaml


# ── Tier mapping ────────────────────────────────────────────────────────
# Single source of truth. Keyed by (kind, name) so we can be precise
# (e.g. only flink-jobmanager StatefulSet → compute, not every StatefulSet).

_EXPLICIT = {
    # data plane
    ("StatefulSet", "kafka"):    "data",
    ("StatefulSet", "redis"):    "data",
    ("StatefulSet", "spm-db"):   "data",

    # data plane init Jobs (seeded by bootstrap, formerly helm hooks)
    ("Job", "db-seed"):                "data-init",
    ("Job", "startup-orchestrator"):   "data-init",

    # compute plane
    ("StatefulSet", "flink-jobmanager"):    "compute",
    ("Deployment",  "flink-taskmanager"):   "compute",

    # compute plane init Job
    ("Job", "flink-pyjob-submitter"):  "compute-init",

    # frontend (depends on platform-tier Services)
    ("Deployment", "ui"):  "frontend",
}

# Kinds that always go to infra (config / RBAC / routing — no pods).
_INFRA_KINDS = {
    "ConfigMap",
    "Secret",
    "Service",
    "ServiceAccount",
    "Role",
    "RoleBinding",
    "ClusterRole",
    "ClusterRoleBinding",
    "NetworkPolicy",
    "PersistentVolumeClaim",
    "Ingress",
    "Gateway",
    "VirtualService",
    "PeerAuthentication",
    "AuthorizationPolicy",
    "TracingPolicy",
    "ClusterPolicy",
    "ResourceQuota",
    "PodDisruptionBudget",
    "PriorityClass",
}

# Tier order — matches the bootstrap-cluster.sh apply order.
TIER_ORDER = [
    "infra",
    "data",
    "data-init",
    "platform",
    "compute",
    "compute-init",
    "frontend",
]


def tier_of(doc):
    """Return the tier name for a single rendered manifest, or None for empty docs."""
    if doc is None:
        return None
    kind = doc.get("kind", "")
    name = (doc.get("metadata", {}) or {}).get("name", "")

    # Explicit (kind, name) wins.
    explicit = _EXPLICIT.get((kind, name))
    if explicit:
        return explicit

    # Config-kind fallback.
    if kind in _INFRA_KINDS:
        return "infra"

    # Unknown Deployment / StatefulSet → platform tier (the catch-all for
    # backend services). New backend deployments don't need code changes
    # here; they just naturally land in `platform`.
    if kind in ("Deployment", "StatefulSet"):
        return "platform"

    # Unknown Job → platform (so it runs alongside the backend services
    # and the bootstrap waits for it). If a future Job needs special
    # ordering, add an explicit entry above.
    if kind == "Job":
        return "platform"

    # Anything else is treated as config.
    return "infra"


def main():
    if len(sys.argv) != 3:
        sys.stderr.write("usage: split-by-tier.py <rendered.yaml> <out_dir>\n")
        sys.exit(2)

    rendered_path = sys.argv[1]
    out_dir = sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)

    with open(rendered_path) as f:
        docs = list(yaml.safe_load_all(f))

    by_tier = {t: [] for t in TIER_ORDER}
    unknown = []
    for doc in docs:
        if doc is None:
            continue
        t = tier_of(doc)
        if t is None:
            continue
        if t not in by_tier:
            # Defensive: should never happen given tier_of()'s logic, but
            # if it does, surface it loudly rather than silently dropping.
            unknown.append((t, doc.get("kind"), (doc.get("metadata", {}) or {}).get("name", "")))
            continue
        by_tier[t].append(doc)

    if unknown:
        sys.stderr.write(f"split-by-tier: unknown tier returned for {len(unknown)} doc(s): {unknown}\n")
        sys.exit(1)

    # Write one file per tier (always, even if empty — the bootstrap
    # script can apply zero-resource files harmlessly).
    summary = {}
    for t in TIER_ORDER:
        out_path = os.path.join(out_dir, f"{t}.yaml")
        with open(out_path, "w") as f:
            if by_tier[t]:
                yaml.safe_dump_all(by_tier[t], f, default_flow_style=False, sort_keys=False)
        summary[t] = len(by_tier[t])

    print(json.dumps(summary))


if __name__ == "__main__":
    main()
