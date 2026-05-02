"""
policies/opa_sync.py
─────────────────────
Live-sync of edited Rego policies into the running OPA instance via the
``opa-policies`` Kubernetes ConfigMap.

Why a ConfigMap, not OPA's policy API?
──────────────────────────────────────
The chart already mounts ``opa-policies`` into the OPA pod and OPA hot-
reloads on file-change events. Patching the ConfigMap is therefore the
single source of truth — both fresh installs (helm upgrade re-renders
files/policies/*.rego into the same map) and runtime edits (this module
patches the same map) end up in the same place. If we wrote directly to
OPA's ``PUT /v1/policies/{id}`` endpoint we'd get the policy active in
the running OPA but the next helm upgrade or pod restart would silently
revert to the chart-rendered version — drift that's invisible until an
operator notices the wrong rule firing in production.

Transactional contract
──────────────────────
``activate_with_opa_sync()`` is the public entry point. It guarantees
that the catalog DB and the OPA ConfigMap are either BOTH updated to the
new version, or BOTH remain on the previous version. The flow:

  1. Read the previous active version (snapshot for rollback).
  2. Set new version active in DB (commit).
  3. Patch ConfigMap with the new .rego content.
  4. If step 3 fails, revert DB to the previous active version.
     If the revert ALSO fails, log a hard error — the system is now in
     an inconsistent state and needs operator attention.
  5. Return the activated version.

The "both fail" path is rare (DB + k8s API both unavailable) but real,
so the error message names exactly what's inconsistent and which
``policy_id`` / ``version_number`` to reconcile.

Mapping policy_id → ConfigMap key
─────────────────────────────────
The chart bundles policies as ``deploy/helm/aispm/files/policies/<stem>.rego``,
which renders into ConfigMap keys like ``jailbreak_policy.rego``. Our
DB ``policy_id`` is ``<stem>-v1`` (see ``policies/rego_seed.py``). So the
map is ``policy_id="jailbreak_policy-v1" → key="jailbreak_policy.rego"``.

Policies created entirely via the UI (no .rego under files/policies/)
get a fresh key on first activate. They're added to the ConfigMap; the
next helm upgrade then ships them too because the chart re-reads the
configmap state on render.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

log = logging.getLogger("policies.opa_sync")

# ── Configuration ────────────────────────────────────────────────────────────

# Defaults match the chart layout. Override via env in tests / non-default
# deployments.
_NAMESPACE        = os.environ.get("OPA_CONFIGMAP_NAMESPACE", "aispm")
_CONFIGMAP_NAME   = os.environ.get("OPA_CONFIGMAP_NAME",      "opa-policies")
_PATCH_TIMEOUT_S  = float(os.environ.get("OPA_CONFIGMAP_PATCH_TIMEOUT_S", "10.0"))


class OpaConfigMapPatchError(RuntimeError):
    """Raised when the ConfigMap patch failed for any reason —
    network, RBAC, validation, or version-conflict.

    Callers catch this specifically so they can roll back the DB-side
    change. Other exceptions propagate as-is.
    """


class OpaSyncRollbackError(RuntimeError):
    """Raised when both the ConfigMap patch AND the DB rollback failed.

    Carries the ``policy_id`` and ``version_number`` of the activation
    attempt so an operator can reconcile manually:

        kubectl -n aispm get configmap opa-policies -o yaml
        # compare the .rego content with the policy_versions row that
        # has is_runtime_active=1, fix whichever is wrong, then either
        # patch the ConfigMap or rerun set_runtime_active by hand.
    """
    def __init__(self, policy_id: str, version_number: int,
                 patch_err: Exception, rollback_err: Exception):
        self.policy_id      = policy_id
        self.version_number = version_number
        self.patch_err      = patch_err
        self.rollback_err   = rollback_err
        super().__init__(
            f"OPA ConfigMap patch failed AND DB rollback failed for "
            f"policy_id={policy_id!r} version={version_number}. "
            f"patch_err={patch_err!r} rollback_err={rollback_err!r}. "
            "DB and ConfigMap are now inconsistent — manual reconciliation needed."
        )


# ── Policy ID → ConfigMap key ────────────────────────────────────────────────
# Strip a trailing "-v<N>" version suffix and append ".rego".
# "jailbreak_policy-v1" → "jailbreak_policy.rego"
# "custom_policy"       → "custom_policy.rego"   (no version suffix)
# "draft-v3"            → "draft.rego"

_VERSION_SUFFIX_RE = re.compile(r"-v\d+$")


def _configmap_key_for(policy_id: str) -> str:
    stem = _VERSION_SUFFIX_RE.sub("", policy_id)
    return f"{stem}.rego"


# ── Kubernetes client (lazy, cached) ─────────────────────────────────────────

_core_v1 = None  # cached kubernetes.client.CoreV1Api


def _get_k8s_core():
    """Return a CoreV1Api client. In-cluster config first, falls back to
    kubeconfig for local dev. Cached after first successful call so we
    don't re-load config on every patch.
    """
    global _core_v1
    if _core_v1 is not None:
        return _core_v1
    try:
        from kubernetes import client, config  # local import — optional dep
    except Exception as exc:
        raise OpaConfigMapPatchError(
            f"kubernetes client library not available: {exc}"
        ) from exc

    try:
        config.load_incluster_config()
    except Exception:
        try:
            config.load_kube_config()
        except Exception as exc:
            raise OpaConfigMapPatchError(
                f"could not load kubernetes config (in-cluster or kubeconfig): {exc}"
            ) from exc

    _core_v1 = client.CoreV1Api()
    return _core_v1


# ── ConfigMap patch ──────────────────────────────────────────────────────────

def patch_opa_configmap(policy_id: str, rego_content: str) -> str:
    """Update the ``opa-policies`` ConfigMap so the file matching
    ``policy_id`` carries ``rego_content``.

    Returns the ConfigMap key that was written (e.g. ``jailbreak_policy.rego``)
    so callers can include it in audit / log lines.

    Raises ``OpaConfigMapPatchError`` on any failure. Side-effect-free
    on failure — the live ConfigMap is unchanged.

    Reads the current ConfigMap, mutates the single relevant key, and
    submits a strategic-merge PATCH back. We avoid PUT (full replace)
    because the chart's own resource-name + label metadata must be
    preserved across updates; a PATCH on ``data.<key>`` only is the
    minimum-disruption operation.
    """
    key = _configmap_key_for(policy_id)
    try:
        from kubernetes.client.exceptions import ApiException  # local import
    except Exception as exc:
        raise OpaConfigMapPatchError(
            f"kubernetes client library not available: {exc}"
        ) from exc

    core = _get_k8s_core()

    # Strategic-merge patch: PATCH /api/v1/namespaces/{ns}/configmaps/{name}
    # with body {data: {<key>: <content>}}. The merge replaces only the
    # specified key; other policies in the same ConfigMap are untouched.
    body = {"data": {key: rego_content}}
    try:
        core.patch_namespaced_config_map(
            name=_CONFIGMAP_NAME,
            namespace=_NAMESPACE,
            body=body,
            _request_timeout=_PATCH_TIMEOUT_S,
        )
    except ApiException as exc:
        # 403 here means the agent-orchestrator ServiceAccount doesn't have
        # configmaps/update on the aispm namespace. Surface that
        # specifically so operators know to update RBAC, not chase a
        # mysterious "ConfigMap patch failed".
        if exc.status == 403:
            raise OpaConfigMapPatchError(
                f"forbidden patching configmap {_NAMESPACE}/{_CONFIGMAP_NAME} "
                f"(RBAC missing configmaps/update for the agent-orchestrator "
                f"ServiceAccount): {exc}"
            ) from exc
        if exc.status == 404:
            raise OpaConfigMapPatchError(
                f"configmap {_NAMESPACE}/{_CONFIGMAP_NAME} does not exist; "
                "is the chart deployed?"
            ) from exc
        raise OpaConfigMapPatchError(
            f"k8s API rejected patch on {_NAMESPACE}/{_CONFIGMAP_NAME}: "
            f"status={exc.status} body={exc.body!r}"
        ) from exc
    except Exception as exc:
        raise OpaConfigMapPatchError(
            f"unexpected error patching configmap {_NAMESPACE}/{_CONFIGMAP_NAME}: "
            f"{exc.__class__.__name__}: {exc}"
        ) from exc

    log.info(
        "opa_sync: patched configmap %s/%s key=%s (%d bytes)",
        _NAMESPACE, _CONFIGMAP_NAME, key, len(rego_content),
    )
    return key


# ── Transactional activate ───────────────────────────────────────────────────

def activate_with_opa_sync(repo, policy_id: str, version_number: int,
                            *, actor: str = "api-user") -> dict:
    """Atomically promote ``version_number`` to the runtime-active version
    AND push its .rego content into the live OPA ConfigMap.

    Either both writes succeed and a description dict is returned, or
    both writes are rolled back and ``OpaConfigMapPatchError`` is raised.
    The only path that leaves the system inconsistent is ConfigMap-patch
    failure followed by DB-rollback failure; that case raises
    ``OpaSyncRollbackError`` with enough context to reconcile manually.

    Returns
    -------
    dict
        ``{"policy_id": ..., "version_number": ..., "configmap_key": ...,
            "logic_bytes": int}`` for audit logging.

    Raises
    ------
    OpaConfigMapPatchError
        ConfigMap patch failed; DB has been rolled back.
    OpaSyncRollbackError
        ConfigMap patch failed AND DB rollback also failed; system is
        inconsistent.
    """
    # 1. Snapshot the previous active version (may be None on first promote).
    previous = repo.get_runtime_policy(policy_id)
    previous_version_number = previous.version_number if previous else None

    # 2. Set the new version active in DB. ``set_runtime_active`` validates
    #    that the version exists and is in a state allowed to be active
    #    (monitor or enforced); it raises ValueError otherwise — we let
    #    that propagate without ConfigMap touching anything.
    activated = repo.set_runtime_active(policy_id, version_number, actor=actor)

    # 3. Patch the ConfigMap. If this raises, we must roll back the DB.
    try:
        key = patch_opa_configmap(policy_id, activated.logic_code or "")
    except OpaConfigMapPatchError as patch_err:
        log.warning(
            "opa_sync: ConfigMap patch failed for policy_id=%s version=%d — "
            "rolling back DB to previous active=%s",
            policy_id, version_number, previous_version_number,
        )
        try:
            if previous_version_number is not None:
                repo.set_runtime_active(
                    policy_id, previous_version_number,
                    actor=f"rollback({actor})",
                )
            else:
                # No previous active — just clear the flag we just set.
                # ``set_runtime_active`` zeroes ALL active flags first, so
                # we re-fetch the row and zero its is_runtime_active
                # explicitly. Keeping this contained in the repo keeps
                # the rollback transactional and audited.
                repo._clear_runtime_active(policy_id, actor=f"rollback({actor})")
        except Exception as rollback_err:
            log.error(
                "opa_sync: DB ROLLBACK ALSO FAILED for policy_id=%s version=%d. "
                "DB and ConfigMap are inconsistent — manual reconciliation needed.",
                policy_id, version_number, exc_info=True,
            )
            raise OpaSyncRollbackError(
                policy_id, version_number, patch_err, rollback_err
            ) from patch_err
        # DB rolled back cleanly; surface the original ConfigMap error.
        raise

    # 4. Both writes succeeded.
    return {
        "policy_id":      policy_id,
        "version_number": version_number,
        "configmap_key":  key,
        "logic_bytes":    len(activated.logic_code or ""),
    }
