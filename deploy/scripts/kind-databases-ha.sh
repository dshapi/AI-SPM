#!/usr/bin/env bash
# deploy/scripts/kind-databases-ha.sh
# ─────────────────────────────────────────────────────────────────────────
# Install Postgres + Redis as HA stateful workloads BEFORE running the
# AISPM bootstrap. Replaces the chart's single-pod spm-db / redis
# StatefulSets.
#
# What gets installed:
#
#   1. CloudNativePG operator + a 3-instance Postgres Cluster.
#      - 1 primary + 2 hot-standby replicas, streaming replication.
#      - PVCs use the default StorageClass (Longhorn after kind-storage.sh).
#      - Operator handles failover automatically: if the primary's pod
#        dies, a standby gets promoted within ~10s.
#      - Connection endpoints (Services that the operator manages):
#          spm-db-rw  — read/write, always points at the current primary
#          spm-db-r   — read-only, any replica
#          spm-db-ro  — read-only, replicas only (excludes primary)
#      - Pre-creates the `spm` database and `spm_rw` superuser with the
#        password we already use in platform-secrets.
#
#   2. Bitnami Redis chart in replication + Sentinel mode.
#      - 1 master + 2 replicas + 3 sentinels (sidecars on each Redis pod).
#      - Sentinels monitor the master and elect a new one on failure.
#      - Connection: clients use the Sentinel-aware service `redis`
#        which proxies to the current master.
#
# After this script:
#   - Set spmDb.enabled=false and redis.enabled=false in values.dev-multinode.yaml
#     so the chart's built-in single-pod versions are skipped.
#   - Override SPM_DB_URL / SPM_DB_URL_ASYNC / REDIS_URL via platformEnv.
#
# Subcommands:
#   up      Install CNPG + Postgres cluster + Redis HA. Idempotent.
#   status  Show CNPG cluster + Redis sentinel status.
#   down    Uninstall both (DESTROYS data).
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

CNPG_VERSION="${CNPG_VERSION:-1.24.1}"
PG_NAMESPACE="${PG_NAMESPACE:-aispm}"
PG_CLUSTER_NAME="${PG_CLUSTER_NAME:-spm-db}"
PG_INSTANCES="${PG_INSTANCES:-3}"
PG_DB_NAME="${PG_DB_NAME:-spm}"
PG_DB_OWNER="${PG_DB_OWNER:-spm_rw}"
PG_DB_PASSWORD="${PG_DB_PASSWORD:-spmpass}"
PG_STORAGE_SIZE="${PG_STORAGE_SIZE:-2Gi}"
PG_STORAGE_CLASS="${PG_STORAGE_CLASS:-standard}"   # kind's local-path

REDIS_NAMESPACE="${REDIS_NAMESPACE:-aispm}"
REDIS_CHART_VERSION="${REDIS_CHART_VERSION:-20.13.4}"
REDIS_PASSWORD="${REDIS_PASSWORD:-}"       # empty = no auth (dev)

_log()  { printf '\033[1;36m▶ %s\033[0m\n' "$*"; }
_warn() { printf '\033[1;33m! %s\033[0m\n' "$*"; }

# ── 1. CloudNativePG operator + Postgres cluster ────────────────────────

_install_cnpg_operator() {
  _log "installing CloudNativePG operator ${CNPG_VERSION}"
  kubectl apply --server-side --force-conflicts \
    -f "https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-${CNPG_VERSION%.*}/releases/cnpg-${CNPG_VERSION}.yaml" \
    >/dev/null

  _log "  waiting for CNPG operator to be Ready..."
  kubectl -n cnpg-system wait --for=condition=Available deploy/cnpg-controller-manager --timeout=180s
}

_create_pg_cluster() {
  _log "creating Postgres cluster ${PG_CLUSTER_NAME} (${PG_INSTANCES} instances) in ${PG_NAMESPACE}"
  kubectl get namespace "$PG_NAMESPACE" >/dev/null 2>&1 || \
    kubectl create namespace "$PG_NAMESPACE"

  # Auth secret consumed by the Cluster spec. The bootstrap.initdb.owner
  # below uses this credential.
  kubectl -n "$PG_NAMESPACE" create secret generic "${PG_CLUSTER_NAME}-app" \
    --from-literal=username="$PG_DB_OWNER" \
    --from-literal=password="$PG_DB_PASSWORD" \
    --type=kubernetes.io/basic-auth \
    --dry-run=client -o yaml | kubectl apply -f -

  # CNPG Cluster CR. The operator creates:
  #   - <name>-1, -2, -3 pods (StatefulSet behind the scenes)
  #   - Service <name>-rw  → primary
  #   - Service <name>-r   → any (round-robin)
  #   - Service <name>-ro  → replicas only
  local sc_clause=""
  [ -n "$PG_STORAGE_CLASS" ] && sc_clause="storageClass: ${PG_STORAGE_CLASS}"

  cat <<EOF | kubectl apply -f -
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: ${PG_CLUSTER_NAME}
  namespace: ${PG_NAMESPACE}
spec:
  instances: ${PG_INSTANCES}
  imageName: ghcr.io/cloudnative-pg/postgresql:16.4-bookworm

  # Spread instances across nodes so a node loss only takes one Postgres
  # replica down. Required topology spread, not preferred — we have 3
  # nodes and 3 instances so this fits exactly.
  topologySpreadConstraints:
    - maxSkew: 1
      topologyKey: kubernetes.io/hostname
      whenUnsatisfiable: DoNotSchedule
      labelSelector:
        matchLabels:
          cnpg.io/cluster: ${PG_CLUSTER_NAME}

  bootstrap:
    initdb:
      database: ${PG_DB_NAME}
      owner: ${PG_DB_OWNER}
      secret:
        name: ${PG_CLUSTER_NAME}-app

  storage:
    size: ${PG_STORAGE_SIZE}
    ${sc_clause}

  postgresql:
    parameters:
      max_connections: "200"
      shared_buffers: "256MB"
      # Replication tuning — pulled from CNPG's recommended defaults.
      max_wal_size: "1GB"
      wal_keep_size: "512MB"

  # Failover policy: primary unhealthy ≥ 30s → trigger switchover.
  primaryUpdateStrategy: unsupervised
  primaryUpdateMethod: switchover

  monitoring:
    enablePodMonitor: false
EOF

  _log "  waiting for Postgres cluster to be healthy (~2-3 min)..."
  for i in $(seq 1 60); do
    ready=$(kubectl -n "$PG_NAMESPACE" get cluster "$PG_CLUSTER_NAME" \
              -o jsonpath='{.status.readyInstances}' 2>/dev/null || echo 0)
    instances=$(kubectl -n "$PG_NAMESPACE" get cluster "$PG_CLUSTER_NAME" \
                  -o jsonpath='{.status.instances}' 2>/dev/null || echo 0)
    if [ "${ready:-0}" -ge "$PG_INSTANCES" ]; then
      _log "  ✓ ${ready}/${instances} Postgres instances Ready"
      return 0
    fi
    printf '\r    waiting (%s/60) — %s/%s Ready... ' "$i" "${ready:-0}" "${instances:-0}"
    sleep 10
  done
  _warn "Postgres cluster didn't reach ${PG_INSTANCES} Ready in 10 min"
}

# ── 2. Bitnami Redis with Sentinel ──────────────────────────────────────

_install_redis_ha() {
  _log "installing Bitnami Redis ${REDIS_CHART_VERSION} (replication + sentinel)"
  helm repo add bitnami https://charts.bitnami.com/bitnami >/dev/null 2>&1 || true
  helm repo update bitnami >/dev/null

  kubectl get namespace "$REDIS_NAMESPACE" >/dev/null 2>&1 || \
    kubectl create namespace "$REDIS_NAMESPACE"

  # Auth disabled by default for dev simplicity. Set REDIS_PASSWORD env
  # to enable. With sentinel.enabled=true the chart deploys:
  #   - StatefulSet `redis-node` with N replicas (each pod runs both
  #     redis-server and redis-sentinel containers)
  #   - Headless Service for sentinel discovery
  #   - Regular Service `redis` that exposes BOTH the redis port (6379)
  #     and the sentinel port (26379). Clients that speak the sentinel
  #     protocol find the current master via 26379.
  local auth_set="--set auth.enabled=false"
  [ -n "$REDIS_PASSWORD" ] && auth_set="--set auth.password=${REDIS_PASSWORD}"

  # Bitnami moved many public tags from `bitnami/*` to `bitnamilegacy/*`
  # in late 2025 as part of their image-licensing changes. Override
  # both the redis image and the sentinel image so we pull from the
  # still-public legacy namespace.
  helm upgrade --install redis bitnami/redis \
    --namespace "$REDIS_NAMESPACE" \
    --version "$REDIS_CHART_VERSION" \
    --set architecture=replication \
    --set sentinel.enabled=true \
    --set sentinel.quorum=2 \
    --set replica.replicaCount=3 \
    $auth_set \
    --set global.security.allowInsecureImages=true \
    --set image.repository=bitnamilegacy/redis \
    --set sentinel.image.repository=bitnamilegacy/redis-sentinel \
    --set master.persistence.enabled=true \
    --set master.persistence.size=2Gi \
    --set master.persistence.storageClass=standard \
    --set replica.persistence.enabled=true \
    --set replica.persistence.size=2Gi \
    --set replica.persistence.storageClass=standard \
    --wait --timeout=10m

  _log "  ✓ Redis HA Ready (1 master + 3 replicas + 3 sentinels)"

  # ── No master proxy: clients use Sentinel directly ───────────────────
  # Earlier versions deployed an HAProxy `redis-master-proxy` Deployment
  # + `redis-master` Service that probed `INFO replication` against each
  # redis-node and forwarded to whichever returned `role:master`. The
  # 1-second tcp-check cycle interacted badly with istio sidecar
  # connection pooling — backends flapped UP/DOWN with ECONNRESET at
  # PING, causing chat-path 500s. Rather than tune the haproxy check
  # interval (workaround), we moved master discovery into the
  # application clients via Redis Sentinel. See
  # platform_shared/redis.py:get_redis_client() — every service builds
  # its client through that helper, which uses redis.sentinel.Sentinel
  # to discover the current master from REDIS_SENTINEL_HOSTS exposed by
  # configmap-platform-env.yaml. Failover is transparent at the client
  # layer; no proxy needed.
}

# ── Subcommands ─────────────────────────────────────────────────────────

cmd_up() {
  command -v helm    >/dev/null 2>&1 || { echo "helm is required" >&2; exit 1; }
  command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required" >&2; exit 1; }

  _install_cnpg_operator
  _create_pg_cluster
  _install_redis_ha

  echo
  _log "HA databases ready. AISPM should connect to:"
  echo
  echo "  Postgres (read-write, follows primary on failover):"
  echo "    SPM_DB_URL=postgresql://${PG_DB_OWNER}:${PG_DB_PASSWORD}@${PG_CLUSTER_NAME}-rw.${PG_NAMESPACE}.svc.cluster.local:5432/${PG_DB_NAME}"
  echo "    SPM_DB_URL_ASYNC=postgresql+asyncpg://${PG_DB_OWNER}:${PG_DB_PASSWORD}@${PG_CLUSTER_NAME}-rw.${PG_NAMESPACE}.svc.cluster.local:5432/${PG_DB_NAME}"
  echo
  echo "  Redis (Sentinel-aware service):"
  echo "    REDIS_URL=redis://redis.${REDIS_NAMESPACE}.svc.cluster.local:6379"
  echo "    SENTINEL_URL=redis://redis.${REDIS_NAMESPACE}.svc.cluster.local:26379"
  echo
  echo "  Next steps:"
  echo "    1. Set spmDb.enabled=false and redis.enabled=false in"
  echo "       deploy/helm/aispm/values.dev-multinode.yaml so the chart"
  echo "       doesn't try to deploy its built-in single-pod versions."
  echo "    2. Override platformEnv.SPM_DB_URL / SPM_DB_URL_ASYNC / REDIS_URL"
  echo "       in the same values file with the URLs above."
  echo "    3. Run bootstrap-cluster.sh as usual."
}

cmd_status() {
  _log "Postgres cluster:"
  kubectl -n "$PG_NAMESPACE" get cluster "$PG_CLUSTER_NAME" 2>&1
  echo
  kubectl -n "$PG_NAMESPACE" get pods -l "cnpg.io/cluster=${PG_CLUSTER_NAME}" -o wide 2>&1
  echo
  _log "Redis HA pods:"
  kubectl -n "$REDIS_NAMESPACE" get pods -l app.kubernetes.io/name=redis -o wide 2>&1
  echo
  _log "Sentinel master info:"
  kubectl -n "$REDIS_NAMESPACE" exec redis-node-0 -c sentinel -- \
    redis-cli -p 26379 sentinel get-master-addr-by-name mymaster 2>&1 || true
}

cmd_down() {
  read -rp "⚠️  uninstall CNPG + Redis HA and DESTROY all data? [y/N] " ans
  [[ "$ans" =~ ^[Yy]$ ]] || { echo "aborted"; exit 0; }

  kubectl -n "$PG_NAMESPACE" delete cluster "$PG_CLUSTER_NAME" --ignore-not-found
  kubectl -n "$PG_NAMESPACE" delete pvc -l "cnpg.io/cluster=${PG_CLUSTER_NAME}" --ignore-not-found
  kubectl delete -f \
    "https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-${CNPG_VERSION%.*}/releases/cnpg-${CNPG_VERSION}.yaml" \
    --ignore-not-found 2>/dev/null || true

  helm uninstall redis -n "$REDIS_NAMESPACE" 2>/dev/null || true
  kubectl -n "$REDIS_NAMESPACE" delete pvc -l app.kubernetes.io/name=redis --ignore-not-found
}

case "${1:-}" in
  up)     cmd_up ;;
  status) cmd_status ;;
  down)   cmd_down ;;
  *) echo "usage: $0 {up|status|down}" >&2; exit 1 ;;
esac
