#!/usr/bin/env bash
# deploy/scripts/kind-cluster.sh
# ─────────────────────────────────────────────────────────────────────────
# Lifecycle helper for a 3-control-plane kind cluster on Docker Desktop.
# Drop-in replacement for orb-k3s.sh after the move off OrbStack.
#
# Why this design:
#   - 3 control-plane nodes give HA api-server + etcd quorum (tolerates
#     1 node loss). All 3 can also schedule workloads (kind does NOT
#     taint control-plane by default in HA mode).
#   - Each node has an extraMount to a host directory under /tmp/kind-vols
#     so storage CSI drivers (Longhorn, Rook-Ceph, etc.) can write OSD
#     data outside the container's overlay filesystem — important for
#     IO performance and for surviving `kind delete cluster`.
#   - A local Docker registry on localhost:5000 is wired into containerd
#     as a mirror. AISPM service images push there; kind pulls from
#     there. No host.orb.internal hacks needed.
#
# Subcommands:
#   init      Create kind cluster + local registry + kubeconfig.
#             Idempotent.
#   up        Start a previously stopped cluster (alias for `init`).
#   down      kind delete cluster + remove the local registry container.
#   status    Show kind node containers + kubectl get nodes.
#   destroy   Same as `down` plus removes the per-node host volumes
#             at /tmp/kind-vols.
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-aispm}"
KIND_NODE_IMAGE="${KIND_NODE_IMAGE:-kindest/node:v1.31.0}"
REGISTRY_NAME="${REGISTRY_NAME:-aispm-registry}"
REGISTRY_PORT="${REGISTRY_PORT:-5001}"   # NOT 5000 — Docker Desktop hijacks 5000.
KUBECONFIG_PATH="${KUBECONFIG_PATH:-${HOME}/.kube/kind-aispm.yaml}"
HOST_VOLUMES_ROOT="${HOST_VOLUMES_ROOT:-/tmp/kind-vols}"

_log()  { printf '\033[1;36m▶ %s\033[0m\n' "$*"; }
_warn() { printf '\033[1;33m! %s\033[0m\n' "$*"; }

# ── Local registry container (kind-recommended pattern) ─────────────────

_ensure_registry() {
  if docker ps --format '{{.Names}}' | grep -qx "$REGISTRY_NAME"; then
    _log "registry already running on localhost:${REGISTRY_PORT}"
    return
  fi
  if docker ps -a --format '{{.Names}}' | grep -qx "$REGISTRY_NAME"; then
    docker start "$REGISTRY_NAME" >/dev/null
    _log "started existing registry container"
    return
  fi
  _log "starting local registry on localhost:${REGISTRY_PORT}"
  docker run -d --restart=always \
    -p "127.0.0.1:${REGISTRY_PORT}:5000" \
    --name "$REGISTRY_NAME" \
    registry:2 >/dev/null
}

# ── Per-node host volumes for storage CSI drivers ───────────────────────

_ensure_host_volumes() {
  for n in control-plane-1 control-plane-2 control-plane-3; do
    mkdir -p "${HOST_VOLUMES_ROOT}/${n}"
  done
}

# ── kind cluster config ────────────────────────────────────────────────

_write_kind_config() {
  local cfg=/tmp/kind-aispm-config.yaml
  cat > "$cfg" <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: ${CLUSTER_NAME}

# Pin the API-server LB port so the kubeconfig endpoint survives
# Docker Desktop restarts (otherwise kind picks a random host port
# each time and 'kubectl' breaks until 'kind export kubeconfig').
networking:
  apiServerAddress: 127.0.0.1
  apiServerPort: 6443

# Wire the local registry into containerd on every node so pulls of
# localhost:${REGISTRY_PORT}/* succeed without authentication.
containerdConfigPatches:
  - |-
    [plugins."io.containerd.grpc.v1.cri".registry]
      config_path = "/etc/containerd/certs.d"

# 3 control-plane nodes for etcd quorum + HA apiserver. kind allows
# scheduling workloads on control-plane in HA mode without explicit
# taint removal. No separate worker pool — keeps things simple.
nodes:
  - role: control-plane
    extraMounts:
      - hostPath: ${HOST_VOLUMES_ROOT}/control-plane-1
        containerPath: /mnt/storage
    extraPortMappings:
      - containerPort: 30443
        hostPort: 30443
        protocol: TCP
      - containerPort: 30080
        hostPort: 30080
        protocol: TCP
  - role: control-plane
    extraMounts:
      - hostPath: ${HOST_VOLUMES_ROOT}/control-plane-2
        containerPath: /mnt/storage
  - role: control-plane
    extraMounts:
      - hostPath: ${HOST_VOLUMES_ROOT}/control-plane-3
        containerPath: /mnt/storage
EOF
  echo "$cfg"
}

_cluster_exists() {
  kind get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"
}

# ── metrics-server (so Lens / kubectl top show CPU + memory) ────────────

_install_metrics_server() {
  _log "installing metrics-server (--kubelet-insecure-tls for kind's self-signed certs)"
  KUBECONFIG="$KUBECONFIG_PATH" kubectl apply \
    -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml \
    >/dev/null

  # kind's kubelet uses self-signed certs that metrics-server rejects by
  # default — patch in --kubelet-insecure-tls.
  KUBECONFIG="$KUBECONFIG_PATH" kubectl -n kube-system patch \
    deployment metrics-server --type=json \
    -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]' \
    >/dev/null

  KUBECONFIG="$KUBECONFIG_PATH" kubectl -n kube-system rollout status \
    deploy/metrics-server --timeout=180s >/dev/null
  _log "  ✓ metrics-server Ready (kubectl top + Lens metrics will populate)"
}

_wire_registry_into_nodes() {
  _log "registering localhost:${REGISTRY_PORT} as a containerd mirror on each node"
  for node in $(kind get nodes --name "$CLUSTER_NAME"); do
    docker exec "$node" mkdir -p "/etc/containerd/certs.d/localhost:${REGISTRY_PORT}"
    docker exec "$node" sh -c "cat > /etc/containerd/certs.d/localhost:${REGISTRY_PORT}/hosts.toml <<EOF
[host.\"http://${REGISTRY_NAME}:5000\"]
EOF"
  done

  # Connect the registry container to the kind network so nodes can
  # resolve "${REGISTRY_NAME}".
  if ! docker network inspect kind | grep -q "\"Name\": \"${REGISTRY_NAME}\""; then
    docker network connect "kind" "$REGISTRY_NAME" 2>/dev/null || true
  fi

  # Advertise the registry to the cluster (used by some tools).
  cat <<EOF | KUBECONFIG="$KUBECONFIG_PATH" kubectl apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: local-registry-hosting
  namespace: kube-public
data:
  localRegistryHosting.v1: |
    host: "localhost:${REGISTRY_PORT}"
    help: "https://kind.sigs.k8s.io/docs/user/local-registry/"
EOF
}

# ── Subcommands ─────────────────────────────────────────────────────────

cmd_init() {
  command -v kind    >/dev/null 2>&1 || { echo "kind is required: brew install kind"        >&2; exit 1; }
  command -v docker  >/dev/null 2>&1 || { echo "docker is required" >&2; exit 1; }
  command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required" >&2; exit 1; }

  _ensure_host_volumes
  _ensure_registry

  if _cluster_exists; then
    _log "kind cluster '${CLUSTER_NAME}' already exists — skipping create"
  else
    local cfg
    cfg=$(_write_kind_config)
    _log "creating kind cluster '${CLUSTER_NAME}' (${KIND_NODE_IMAGE})"
    kind create cluster \
      --name "$CLUSTER_NAME" \
      --image "$KIND_NODE_IMAGE" \
      --config "$cfg" \
      --kubeconfig "$KUBECONFIG_PATH"
  fi

  _wire_registry_into_nodes

  # kind HA mode taints all control-plane nodes NoSchedule by default;
  # with no workers, nothing schedules anywhere. Untaint so the 3 cp
  # nodes also act as workers.
  _log "removing control-plane NoSchedule taint (cp nodes also schedule workloads)"
  KUBECONFIG="$KUBECONFIG_PATH" kubectl taint nodes --all \
    node-role.kubernetes.io/control-plane:NoSchedule- 2>/dev/null || true

  _install_metrics_server

  _log "cluster ready. set:"
  echo "    export KUBECONFIG=$KUBECONFIG_PATH"
  echo "then:"
  echo "    kubectl get nodes -o wide"
}

cmd_up() { cmd_init; }

cmd_down() {
  if _cluster_exists; then
    _log "deleting kind cluster '${CLUSTER_NAME}'"
    kind delete cluster --name "$CLUSTER_NAME"
  fi
  if docker ps -a --format '{{.Names}}' | grep -qx "$REGISTRY_NAME"; then
    docker rm -f "$REGISTRY_NAME" >/dev/null
    _log "removed registry container"
  fi
  rm -f "$KUBECONFIG_PATH"
}

cmd_status() {
  _log "kind nodes (Docker containers):"
  docker ps --filter "label=io.x-k8s.kind.cluster=${CLUSTER_NAME}" \
    --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
  echo
  _log "kubectl get nodes:"
  if [[ -f "$KUBECONFIG_PATH" ]]; then
    KUBECONFIG="$KUBECONFIG_PATH" kubectl get nodes -o wide 2>&1 || true
  else
    echo "  (no kubeconfig at $KUBECONFIG_PATH — run '$0 init')"
  fi
}

cmd_destroy() {
  cmd_down
  rm -rf "${HOST_VOLUMES_ROOT}"
  _log "removed host volumes at ${HOST_VOLUMES_ROOT}"
}

case "${1:-}" in
  init)    cmd_init ;;
  up)      cmd_up ;;
  down)    cmd_down ;;
  status)  cmd_status ;;
  destroy) cmd_destroy ;;
  *) echo "usage: $0 {init|up|down|status|destroy}" >&2; exit 1 ;;
esac
