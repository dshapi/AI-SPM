#!/usr/bin/env bash
# deploy/scripts/kind-cluster.sh
# ─────────────────────────────────────────────────────────────────────────
# Lifecycle helper for a 3-control-plane kind cluster.
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
REGISTRY_PORT="${REGISTRY_PORT:-5001}"   # 5001 because 5000 is often already in use on the host.
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
# Docker daemon restarts (otherwise kind picks a random host port
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
  # We use `tee` rather than `sh -c 'cat > ...'` because some kindest/node
  # images don't expose `sh` on PATH (we hit "exec: sh: executable file not
  # found" during init).  `tee` is shipped under /usr/bin/tee on every
  # kindest/node image.  The `capabilities = ["pull", "resolve"]` line is
  # REQUIRED — without it containerd silently ignores the mirror config
  # and falls back to localhost:5001 which is unreachable from inside the
  # node (we lost an entire afternoon to this in May 2026).
  #
  # `kind get nodes` can transiently return nothing or exit non-zero
  # immediately after cluster creation while the node containers are still
  # starting.  Retry up to 30s before giving up.
  local nodes=""
  local node_retries=0
  local node_max_retries=15   # 15 × 2s = 30s
  until nodes=$(kind get nodes --name "$CLUSTER_NAME" 2>/dev/null) && [ -n "$nodes" ]; do
    node_retries=$((node_retries + 1))
    if [ "$node_retries" -ge "$node_max_retries" ]; then
      echo "ERROR: 'kind get nodes --name $CLUSTER_NAME' returned nothing after $((node_max_retries * 2))s — aborting." >&2
      exit 1
    fi
    sleep 2
  done

  for node in $nodes; do
    _log "  wiring registry mirror into node: $node"
    local exec_retries=0
    local exec_max_retries=10   # 10 × 2s = 20s per node
    until docker exec "$node" mkdir -p "/etc/containerd/certs.d/localhost:${REGISTRY_PORT}" 2>/dev/null; do
      exec_retries=$((exec_retries + 1))
      if [ "$exec_retries" -ge "$exec_max_retries" ]; then
        echo "ERROR: docker exec into $node failed after $((exec_max_retries * 2))s — node may not be running." >&2
        exit 1
      fi
      sleep 2
    done
    printf '[host."http://%s:5000"]\n  capabilities = ["pull", "resolve"]\n' "$REGISTRY_NAME" \
      | docker exec -i "$node" tee "/etc/containerd/certs.d/localhost:${REGISTRY_PORT}/hosts.toml" >/dev/null
  done

  # Connect the registry container to the kind network so nodes can
  # resolve "${REGISTRY_NAME}".  The check below mis-greps on some
  # docker versions (the network inspect of `kind` lists *containers*
  # under .Containers, not under top-level "Name"); just always-attempt
  # connect with a tolerant error, which is idempotent.
  docker network connect "kind" "$REGISTRY_NAME" 2>/dev/null || true

  # Advertise the registry to the cluster (used by some tools).
  # Retry the kubectl apply — the apiserver may not yet accept requests
  # immediately after `kind create cluster` returns.
  local cm_retries=0
  local cm_max_retries=15   # 15 × 2s = 30s
  until KUBECONFIG="$KUBECONFIG_PATH" kubectl apply -f - <<EOF 2>/dev/null
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
  do
    cm_retries=$((cm_retries + 1))
    if [ "$cm_retries" -ge "$cm_max_retries" ]; then
      echo "ERROR: kubectl apply for local-registry-hosting ConfigMap failed after $((cm_max_retries * 2))s." >&2
      exit 1
    fi
    _warn "  kubectl apply not ready yet (attempt $cm_retries/$cm_max_retries) — retrying in 2s..."
    sleep 2
  done
  _log "  ✓ registry mirror configured on all nodes"
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

  # Wait for nodes to actually be Ready before issuing kubectl commands.
  # `kind create cluster` returns once apiserver is reachable, but nodes
  # may still be NotReady for ~20s while the CNI initializes.  Issuing
  # taint/SC commands before nodes are Ready silently drops them.
  _log "waiting for all nodes to be Ready..."
  KUBECONFIG="$KUBECONFIG_PATH" kubectl wait --for=condition=Ready node --all --timeout=180s \
    || _warn "some nodes still NotReady after 3min — continuing anyway, but expect issues"

  # kind HA mode taints all control-plane nodes NoSchedule by default;
  # with no workers, nothing schedules anywhere. Untaint so the 3 cp
  # nodes also act as workers.  Verify the taint is actually gone after
  # the call — silent failure here cost us hours of debugging Pending
  # pods that "should have scheduled" (May 2026).
  _log "removing control-plane NoSchedule taint (cp nodes also schedule workloads)"
  KUBECONFIG="$KUBECONFIG_PATH" kubectl taint nodes --all \
    node-role.kubernetes.io/control-plane:NoSchedule- 2>/dev/null || true
  if KUBECONFIG="$KUBECONFIG_PATH" kubectl get nodes -o jsonpath='{.items[*].spec.taints}' \
       | grep -q 'node-role.kubernetes.io/control-plane'; then
    _warn "control-plane taint NOT removed — workloads will Pending forever."
    _warn "Re-run: kubectl taint nodes --all node-role.kubernetes.io/control-plane:NoSchedule-"
  else
    _log "  ✓ taint removed on all nodes"
  fi

  # The chart's PVC templates hardcode `storageClass: local-path`, but
  # kind's default provisioner ships a StorageClass named `standard`.
  # Create an alias so chart PVCs bind without intervention.  Used to
  # be a manual step in the runbook bring-up — moved here so a fresh
  # init produces a working cluster end-to-end.
  _log "applying local-path StorageClass alias (chart PVCs hardcode this name)"
  cat <<EOF | KUBECONFIG="$KUBECONFIG_PATH" kubectl apply -f -
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: local-path
provisioner: rancher.io/local-path
reclaimPolicy: Delete
volumeBindingMode: WaitForFirstConsumer
EOF

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
