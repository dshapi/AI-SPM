#!/usr/bin/env bash
# adopt-existing-resources.sh
#
# Stamps all pre-existing cluster resources with the Helm ownership labels/
# annotations so that `helm upgrade --install aispm` can adopt them without
# the "invalid ownership metadata" error.
#
# Safe to run multiple times — every command uses --overwrite and || true
# so missing resources are silently skipped.
#
# Usage:
#   bash deploy/helm/adopt-existing-resources.sh
set -euo pipefail

RELEASE="aispm"
RELEASE_NS="default"
NS="aispm"

adopt() {
  local kind="$1" name="$2" ns_flag="${3:+-n $3}"
  kubectl annotate "$kind" "$name" $ns_flag \
    "meta.helm.sh/release-name=$RELEASE" \
    "meta.helm.sh/release-namespace=$RELEASE_NS" \
    --overwrite 2>/dev/null || true
  kubectl label "$kind" "$name" $ns_flag \
    "app.kubernetes.io/managed-by=Helm" \
    --overwrite 2>/dev/null || true
}

echo "Adopting cluster-scoped resources..."
adopt clusterissuer  selfsigned-cluster-issuer
adopt clusterissuer  letsencrypt-staging
adopt clusterissuer  letsencrypt-prod
adopt clusterpolicy  agent-verify-image-signature

echo "Adopting namespaced resources in $NS..."
# Istio / networking
adopt authorizationpolicy api-allow                   "$NS"
adopt authorizationpolicy deny-all-agents             "$NS"
adopt authorizationpolicy kafka-allow-mesh            "$NS"
adopt authorizationpolicy opa-allow-platform          "$NS"
adopt authorizationpolicy redis-allow-platform        "$NS"
adopt authorizationpolicy spm-api-allow               "$NS"
adopt authorizationpolicy spm-db-allow-platform       "$NS"
adopt authorizationpolicy spm-llm-proxy-allow-agents  "$NS"
adopt authorizationpolicy spm-mcp-allow-agents        "$NS"
adopt authorizationpolicy ui-allow-ingress            "$NS"
adopt destinationrule     api-http1                   "$NS"
adopt gateway             aispm-gateway               "$NS"
adopt peerauthentication  default                     "$NS"
adopt virtualservice      aispm-ui                    "$NS"
adopt networkpolicy       default-deny-all            "$NS"
adopt networkpolicy       agent-allow-egress          "$NS"

# cert-manager
adopt certificate         aispm-tls                   "$NS"

# Ingress
adopt ingress             aispm-api                   "$NS"
adopt ingress             aispm-orchestrator          "$NS"
adopt ingress             aispm-ui                    "$NS"

# Workloads
adopt deployment          agent                       "$NS"
adopt deployment          agent-orchestrator          "$NS"
adopt deployment          api                         "$NS"
adopt deployment          executor                    "$NS"
adopt deployment          flink-taskmanager           "$NS"
adopt deployment          freeze-controller           "$NS"
adopt deployment          garak-runner                "$NS"
adopt deployment          guard-model                 "$NS"
adopt deployment          keycloak                    "$NS"
adopt deployment          memory-service              "$NS"
adopt deployment          opa                         "$NS"
adopt deployment          output-guard                "$NS"
adopt deployment          policy-decider              "$NS"
adopt deployment          policy-simulator            "$NS"
adopt deployment          processor                   "$NS"
adopt deployment          retrieval-gateway           "$NS"
adopt deployment          spm-aggregator              "$NS"
adopt deployment          spm-api                     "$NS"
adopt deployment          spm-llm-proxy               "$NS"
adopt deployment          spm-mcp                     "$NS"
adopt deployment          threat-hunting-agent        "$NS"
adopt deployment          tool-parser                 "$NS"
adopt deployment          ui                          "$NS"
adopt statefulset         flink-jobmanager            "$NS"
adopt statefulset         kafka                       "$NS"
adopt statefulset         keycloak-postgres           "$NS"

# Jobs
adopt job                 db-seed                     "$NS"
adopt job                 flink-pyjob-submitter        "$NS"
adopt job                 keycloak-bootstrap          "$NS"
adopt job                 startup-orchestrator        "$NS"

# Services
adopt service             agent                       "$NS"
adopt service             agent-orchestrator          "$NS"
adopt service             api                         "$NS"
adopt service             executor                    "$NS"
adopt service             flink-jobmanager            "$NS"
adopt service             flink-taskmanager           "$NS"
adopt service             freeze-controller           "$NS"
adopt service             garak-runner                "$NS"
adopt service             guard-model                 "$NS"
adopt service             kafka                       "$NS"
adopt service             kafka-broker                "$NS"
adopt service             keycloak                    "$NS"
adopt service             keycloak-postgres           "$NS"
adopt service             memory-service              "$NS"
adopt service             opa                         "$NS"
adopt service             output-guard                "$NS"
adopt service             policy-decider              "$NS"
adopt service             policy-simulator            "$NS"
adopt service             processor                   "$NS"
adopt service             retrieval-gateway           "$NS"
adopt service             spm-aggregator              "$NS"
adopt service             spm-api                     "$NS"
adopt service             spm-db                      "$NS"
adopt service             spm-llm-proxy               "$NS"
adopt service             spm-mcp                     "$NS"
adopt service             threat-hunting-agent        "$NS"
adopt service             tool-parser                 "$NS"
adopt service             ui                          "$NS"

# Config / Secrets
adopt configmap           falco-agent-rules           "$NS"
adopt configmap           flink-conf                  "$NS"
adopt configmap           opa-policies                "$NS"
adopt configmap           platform-env                "$NS"
adopt secret              keycloak-postgres-secret    "$NS"
adopt secret              keycloak-secret             "$NS"
adopt secret              platform-secrets            "$NS"

# RBAC
adopt role                agent-orchestrator          "$NS"
adopt role                flink                       "$NS"
adopt rolebinding         agent-orchestrator          "$NS"
adopt rolebinding         flink                       "$NS"
adopt serviceaccount      agent-orchestrator          "$NS"
adopt serviceaccount      flink                       "$NS"

# Storage
adopt persistentvolumeclaim agent-orchestrator-data   "$NS"
adopt persistentvolumeclaim flink-checkpoints         "$NS"
adopt persistentvolumeclaim flink-ha                  "$NS"
adopt persistentvolumeclaim flink-savepoints          "$NS"
adopt persistentvolumeclaim flink-taskmanager-state   "$NS"
adopt persistentvolumeclaim spm-api-models            "$NS"

# Limits / Quotas
adopt limitrange          agent-runtime-limits        "$NS"
adopt resourcequota       agent-runtime-quota         "$NS"

# Tetragon / Falco
adopt tracingpolicy       agent-no-exec               "$NS"
adopt tracingpolicy       agent-no-proc-write         "$NS"
adopt tracingpolicy       agent-no-raw-socket         "$NS"

# aispm-agents namespace
adopt networkpolicy       default-deny-all            aispm-agents

echo ""
echo "Done. Run: helm upgrade --install aispm ./deploy/helm/aispm -f deploy/helm/aispm/values.local-secrets.yaml"
