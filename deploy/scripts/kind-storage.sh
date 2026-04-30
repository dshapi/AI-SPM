#!/usr/bin/env bash
# deploy/scripts/kind-storage.sh
# ─────────────────────────────────────────────────────────────────────────
# Storage layer for the kind cluster on Docker Desktop.
#
# Why no Longhorn / Ceph / SeaweedFS:
#   Docker Desktop's LinuxKit kernel lacks `iscsi_tcp` and other modules
#   these CSI drivers need. Same wall we hit on OrbStack. After enough
#   debugging we realized: replicated block storage isn't actually
#   needed for our workloads. Every stateful app we run (CNPG Postgres,
#   Redis Sentinel, MinIO, Kafka) does its OWN replication at the
#   application level — each replica wants its own local PVC, period.
#
# Architecture:
#   - local-path (kind's default `standard` StorageClass) for every
#     PVC. Each pod's PVC lives on its node's /mnt/storage extraMount
#     (a host directory under /tmp/kind-vols/<node-name>).
#   - MinIO: 4 pods, each its own local-path PVC, erasure coding across
#     pods (survives 1 node loss at the app layer).
#   - Pre-creates the `flink` bucket on MinIO.
#
# This script only deploys MinIO. Longhorn is no longer installed.
#
# Subcommands:
#   up      Deploy distributed MinIO + create flink bucket. Idempotent.
#   status  Show MinIO pods + buckets.
#   down    Uninstall MinIO (DESTROYS object data).
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

LONGHORN_VERSION="${LONGHORN_VERSION:-1.7.2}"
MINIO_NAMESPACE="${MINIO_NAMESPACE:-minio}"
MINIO_REPLICAS="${MINIO_REPLICAS:-4}"
MINIO_VOLUME_SIZE="${MINIO_VOLUME_SIZE:-5Gi}"
MINIO_ROOT_USER="${MINIO_ROOT_USER:-minioadmin}"
MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-minioadmin}"

_log()  { printf '\033[1;36m▶ %s\033[0m\n' "$*"; }
_warn() { printf '\033[1;33m! %s\033[0m\n' "$*"; }

# Longhorn is no longer installed (LinuxKit lacks iscsi_tcp). The kind
# cluster's built-in `standard` StorageClass (rancher/local-path) backs
# every PVC. App-level replication (CNPG, Sentinel, MinIO erasure
# coding, Kafka rep-factor=3) provides HA, not the storage layer.
_ensure_default_storageclass() {
  if ! kubectl get storageclass standard >/dev/null 2>&1; then
    _warn "no 'standard' StorageClass found — kind should ship one. Check 'kubectl get storageclass'."
    return 1
  fi
  _log "using kind's built-in 'standard' (local-path) StorageClass for all PVCs"
}

# ── 2. MinIO (distributed) ──────────────────────────────────────────────

_install_minio() {
  _log "deploying distributed MinIO (${MINIO_REPLICAS} pods × ${MINIO_VOLUME_SIZE} Longhorn)"
  if ! kubectl get namespace "$MINIO_NAMESPACE" >/dev/null 2>&1; then
    kubectl create namespace "$MINIO_NAMESPACE"
  fi

  kubectl -n "$MINIO_NAMESPACE" create secret generic minio-creds \
    --from-literal=root-user="$MINIO_ROOT_USER" \
    --from-literal=root-password="$MINIO_ROOT_PASSWORD" \
    --dry-run=client -o yaml | kubectl apply -f -

  cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Service
metadata:
  name: minio
  namespace: ${MINIO_NAMESPACE}
spec:
  clusterIP: None
  publishNotReadyAddresses: true
  selector: { app: minio }
  ports:
    - { name: api,     port: 9000, targetPort: 9000 }
    - { name: console, port: 9001, targetPort: 9001 }
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: minio
  namespace: ${MINIO_NAMESPACE}
spec:
  serviceName: minio
  replicas: ${MINIO_REPLICAS}
  podManagementPolicy: Parallel
  selector:
    matchLabels: { app: minio }
  template:
    metadata:
      labels: { app: minio }
    spec:
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchLabels: { app: minio }
                topologyKey: kubernetes.io/hostname
      containers:
        - name: minio
          image: quay.io/minio/minio:RELEASE.2025-01-20T14-49-07Z
          args:
            - server
            - --console-address
            - ":9001"
$(for i in $(seq 0 $((MINIO_REPLICAS-1))); do
  echo "            - http://minio-${i}.minio.${MINIO_NAMESPACE}.svc.cluster.local:9000/data"
done)
          env:
            - name: MINIO_ROOT_USER
              valueFrom: { secretKeyRef: { name: minio-creds, key: root-user } }
            - name: MINIO_ROOT_PASSWORD
              valueFrom: { secretKeyRef: { name: minio-creds, key: root-password } }
          ports:
            - { containerPort: 9000, name: api }
            - { containerPort: 9001, name: console }
          readinessProbe:
            httpGet: { path: /minio/health/ready, port: 9000 }
            initialDelaySeconds: 10
            periodSeconds: 5
            failureThreshold: 12
          livenessProbe:
            httpGet: { path: /minio/health/live, port: 9000 }
            initialDelaySeconds: 30
            periodSeconds: 30
          volumeMounts:
            - { name: data, mountPath: /data }
  volumeClaimTemplates:
    - metadata: { name: data }
      spec:
        accessModes: [ReadWriteOnce]
        storageClassName: standard
        resources:
          requests: { storage: ${MINIO_VOLUME_SIZE} }
EOF

  _log "  waiting for MinIO StatefulSet..."
  kubectl -n "$MINIO_NAMESPACE" rollout status statefulset/minio --timeout=300s

  _log "creating 'flink' bucket on MinIO"
  cat <<EOF | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: minio-init-buckets
  namespace: ${MINIO_NAMESPACE}
spec:
  ttlSecondsAfterFinished: 60
  template:
    spec:
      restartPolicy: OnFailure
      containers:
        - name: mc
          image: quay.io/minio/mc:RELEASE.2024-11-21T17-21-54Z
          env:
            - name: MC_HOST_local
              value: http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@minio.${MINIO_NAMESPACE}.svc.cluster.local:9000
          command:
            - sh
            - -c
            - |
              for i in 1 2 3 4 5 6 7 8 9 10; do
                if mc ls local >/dev/null 2>&1; then break; fi
                echo "  waiting for MinIO API (attempt \$i)..."; sleep 5
              done
              mc mb --ignore-existing local/flink
              mc ls local
EOF
  kubectl -n "$MINIO_NAMESPACE" wait --for=condition=complete \
    job/minio-init-buckets --timeout=120s || \
    _warn "bucket init didn't complete — check kubectl -n $MINIO_NAMESPACE logs job/minio-init-buckets"
}

# ── Subcommands ─────────────────────────────────────────────────────────

cmd_up() {
  command -v helm    >/dev/null 2>&1 || { echo "helm is required" >&2; exit 1; }
  command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required" >&2; exit 1; }
  _ensure_default_storageclass
  _install_minio
  echo
  _log "storage layer ready."
  echo "    Default StorageClass: standard (kind local-path)"
  echo "    S3 API:               minio.${MINIO_NAMESPACE}.svc.cluster.local:9000"
  echo "    S3 access key:        ${MINIO_ROOT_USER}"
  echo "    S3 secret key:        ${MINIO_ROOT_PASSWORD}"
  echo "    Pre-created bucket:   flink"
  echo
  echo "    Next:"
  echo "      ./deploy/scripts/kind-databases-ha.sh up   # CNPG + Redis Sentinel"
}

cmd_status() {
  _log "StorageClasses:"
  kubectl get storageclass
  echo
  _log "Longhorn pods:"
  kubectl -n longhorn-system get pods 2>&1 | head -20
  echo
  _log "MinIO pods:"
  kubectl -n "$MINIO_NAMESPACE" get pods -l app=minio -o wide 2>&1
}

cmd_down() {
  read -rp "⚠️  uninstall Longhorn + MinIO and DESTROY all data? [y/N] " ans
  [[ "$ans" =~ ^[Yy]$ ]] || { echo "aborted"; exit 0; }
  helm uninstall longhorn -n longhorn-system 2>/dev/null || true
  kubectl delete namespace longhorn-system --wait=false 2>/dev/null || true
  kubectl delete namespace "$MINIO_NAMESPACE" --wait=false 2>/dev/null || true
  kubectl get crd -o name | grep longhorn.io | xargs -r kubectl delete --wait=false
}

case "${1:-}" in
  up)     cmd_up ;;
  status) cmd_status ;;
  down)   cmd_down ;;
  *) echo "usage: $0 {up|status|down}" >&2; exit 1 ;;
esac
