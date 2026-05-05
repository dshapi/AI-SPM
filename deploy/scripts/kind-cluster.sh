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
  # Idempotent against every "registry is already up" state. NEVER fails
  # the script when a working registry is reachable on REGISTRY_PORT —
  # even if it's a container we don't own.
  #
  # Cases handled, in order:
  #   1. Our named container is running       → log + return
  #   2. Our named container exists, stopped  → start + return
  #   3. Some OTHER process serves /v2/ on    → log + reuse + return
  #      our port (different container, an
  #      already-running registry from a
  #      previous setup, etc.)
  #   4. Port appears free                    → docker run a fresh container
  #   5. docker run failed BUT port is held   → warn + return 0
  #      (something is on the port we can't  (don't fail the script just
  #      probe; treat as "registry is up")    because we can't probe it)
  #   6. docker run failed AND port is free   → return 1 (real docker error)

  # Case 1: our container running
  if docker ps --format '{{.Names}}' | grep -qx "$REGISTRY_NAME"; then
    _log "registry '${REGISTRY_NAME}' already running on localhost:${REGISTRY_PORT}"
    return 0
  fi

  # Case 2: our container exists but is stopped
  if docker ps -a --format '{{.Names}}' | grep -qx "$REGISTRY_NAME"; then
    if docker start "$REGISTRY_NAME" >/dev/null 2>&1; then
      _log "started existing registry container '${REGISTRY_NAME}'"
      return 0
    fi
    _warn "container '${REGISTRY_NAME}' exists but won't start; falling through to live-port detection"
  fi

  # Case 3: a Docker registry is already serving on our port (different
  # container name, or hand-rolled). Reuse it instead of fighting the
  # port. This is the case the user hit: "don't fail if the registry is up".
  if command -v curl >/dev/null 2>&1 \
       && curl -fsS -o /dev/null --max-time 3 "http://localhost:${REGISTRY_PORT}/v2/" 2>/dev/null; then
    _log "registry already responding on localhost:${REGISTRY_PORT} (not the '${REGISTRY_NAME}' container)"
    _warn "  reusing the existing registry as-is; pushes still go to localhost:${REGISTRY_PORT}/<image>"
    _warn "  note: \`docker network connect kind '${REGISTRY_NAME}'\` will be skipped — wire it up"
    _warn "  manually if kind nodes need to pull from this registry."
    return 0
  fi

  # Case 4: port appears free, start a fresh container.
  _log "starting local registry on localhost:${REGISTRY_PORT}"
  if docker run -d --restart=always \
       -p "127.0.0.1:${REGISTRY_PORT}:5000" \
       --name "$REGISTRY_NAME" \
       registry:2 >/dev/null 2>&1; then
    return 0
  fi

  # Case 5: docker run failed. If the port is in use we treat it as
  # "registry is up under something we can't probe" and continue —
  # explicit user request: don't fail the script when the registry is up.
  if command -v lsof >/dev/null 2>&1 \
       && lsof -i ":${REGISTRY_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
    _warn "port ${REGISTRY_PORT} is held by something but doesn't speak the v2 registry API."
    _warn "  Continuing anyway (you asked us not to fail when a registry is up)."
    _warn "  If image pushes break, free the port (\`lsof -i :${REGISTRY_PORT}\`) or set"
    _warn "  REGISTRY_PORT=<other port> and re-run."
    return 0
  fi

  # Case 6: real failure (docker daemon down, etc).
  _warn "docker run for '${REGISTRY_NAME}' failed and port ${REGISTRY_PORT} appears free."
  _warn "  Likely the docker daemon isn't running. Try: docker info"
  return 1
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
  # If our named registry container doesn't exist (because _ensure_registry
  # detected a foreign registry on the port and reused it), there's nothing
  # to wire on the kind docker network — skip the whole step. Image pushes
  # still work via the host port; only kind-internal pulls of
  # localhost:5001/* won't resolve through the container DNS, which the
  # foreign registry's owner is responsible for.
  if ! docker ps --format '{{.Names}}' | grep -qx "$REGISTRY_NAME"; then
    _warn "registry container '${REGISTRY_NAME}' not found — skipping containerd mirror wiring."
    _warn "  (a foreign registry is serving localhost:${REGISTRY_PORT}; if kind nodes need to"
    _warn "  pull from it, wire that container's network/DNS yourself.)"
    return 0
  fi

  _log "registering localhost:${REGISTRY_PORT} as a containerd mirror on each node"
  # IMPORTANT: filter out the haproxy load-balancer in HA mode.
  # `kind get nodes` returns ALL containers in the cluster, including
  # `${CLUSTER_NAME}-external-load-balancer` which is an HAProxy image
  # (not kindest/node). docker exec on it to write a containerd mirror
  # file fails — haproxy doesn't ship /etc/containerd or /usr/bin/tee.
  # Under set -e that silently kills the whole init (33s gap with no
  # error message in the user-visible output, May 2026 again).
  #
  # Filter via docker label `io.x-k8s.kind.role=control-plane` (or
  # `worker`) — the load balancer has role `external-load-balancer`
  # and is excluded.
  #
  # We use `tee` rather than `sh -c 'cat > ...'` because some kindest/node
  # images don't expose `sh` on PATH (we hit "exec: sh: executable file not
  # found" during init). `tee` IS shipped under /usr/bin/tee on every
  # kindest/node image. The `capabilities = ["pull", "resolve"]` line is
  # REQUIRED — without it containerd silently ignores the mirror config
  # and falls back to localhost:5001 which is unreachable from inside the
  # node.
  local _node_filter='label=io.x-k8s.kind.cluster='"${CLUSTER_NAME}"
  local _real_nodes
  _real_nodes="$(docker ps --filter "$_node_filter" --format '{{.Names}}' \
                  | grep -Ev '^'"${CLUSTER_NAME}"'-external-load-balancer$' || true)"
  if [ -z "$_real_nodes" ]; then
    _warn "no kind cluster-role nodes found for cluster '${CLUSTER_NAME}'; skipping containerd mirror wiring"
    return 0
  fi
  for node in $_real_nodes; do
    if ! docker exec "$node" mkdir -p "/etc/containerd/certs.d/localhost:${REGISTRY_PORT}" 2>&1; then
      _warn "  ✗ docker exec mkdir on '$node' failed (non-fatal — mirror may not work for this node)"
      continue
    fi
    if ! cat <<EOF | docker exec -i "$node" tee "/etc/containerd/certs.d/localhost:${REGISTRY_PORT}/hosts.toml" >/dev/null 2>&1
[host."http://${REGISTRY_NAME}:5000"]
  capabilities = ["pull", "resolve"]
EOF
    then
      _warn "  ✗ writing hosts.toml on '$node' failed (non-fatal)"
      continue
    fi
    _log "  ✓ wired '$node'"
  done

  # Connect the registry container to the kind network so nodes can
  # resolve "${REGISTRY_NAME}".  The check below mis-greps on some
  # docker versions (the network inspect of `kind` lists *containers*
  # under .Containers, not under top-level "Name"); just always-attempt
  # connect with a tolerant error, which is idempotent.
  docker network connect "kind" "$REGISTRY_NAME" 2>/dev/null || true

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

_preflight() {
  # Hard-fail before doing anything if a prereq is missing.
  command -v kind    >/dev/null 2>&1 || { echo "kind is required: brew install kind"        >&2; exit 1; }
  command -v docker  >/dev/null 2>&1 || { echo "docker is required" >&2; exit 1; }
  command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required" >&2; exit 1; }
  if ! docker info >/dev/null 2>&1; then
    echo "docker daemon isn't responding — start Docker Desktop / colima / dockerd and re-run" >&2
    exit 1
  fi
}

cmd_init() {
  _log "── kind-cluster.sh init: cluster='${CLUSTER_NAME}' image='${KIND_NODE_IMAGE}' registry='${REGISTRY_NAME}:${REGISTRY_PORT}'"
  _preflight

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
  # Order matters here. Why each step:
  #
  #   1. Disconnect the registry from the kind docker network FIRST.
  #      `kind delete cluster` tries to remove its docker network when
  #      it tears down. If the registry is still attached, the network
  #      delete fails silently and a stale `kind` network lingers. On
  #      the next `init`, `kind create` then either uses the stale
  #      network or fails with "network kind already exists" depending
  #      on docker version. Disconnecting first sidesteps both.
  #
  #   2. Delete the kind cluster.
  #
  #   3. Force-prune any kind docker network that survived (Step 1
  #      should have made it deletable; this is belt-and-suspenders).
  #
  #   4. Remove the registry container itself. We do this AFTER the
  #      cluster delete so the registry is around to absorb pulls if
  #      anything in step 2 needs to fetch images. Nothing currently
  #      does, but it's free.
  #
  #   5. Drop the stale kubeconfig so subsequent `kubectl` calls don't
  #      try to reach an apiserver that no longer exists.
  #
  # All steps are tolerant — we keep going on failure and let cmd_init
  # surface real problems if any leftover state actually breaks bring-up.
  _preflight 2>/dev/null || true

  # 1. Disconnect registry from kind network (no-op if not attached)
  if docker ps -a --format '{{.Names}}' | grep -qx "$REGISTRY_NAME"; then
    if docker network inspect kind >/dev/null 2>&1; then
      docker network disconnect kind "$REGISTRY_NAME" 2>/dev/null \
        && _log "disconnected '${REGISTRY_NAME}' from kind network" \
        || true
    fi
  fi

  # 2. Delete the cluster
  if _cluster_exists; then
    _log "deleting kind cluster '${CLUSTER_NAME}'"
    kind delete cluster --name "$CLUSTER_NAME" || _warn "kind delete cluster returned non-zero"
  else
    _log "no kind cluster '${CLUSTER_NAME}' to delete"
  fi

  # 3. Prune stale kind docker network if it survived
  if docker network inspect kind >/dev/null 2>&1; then
    if docker network rm kind >/dev/null 2>&1; then
      _log "pruned stale 'kind' docker network"
    else
      _warn "'kind' docker network still has attached containers — manual cleanup may be needed:"
      _warn "  docker network inspect kind --format '{{range .Containers}}{{.Name}} {{end}}'"
    fi
  fi

  # 4. Remove the registry container
  if docker ps -a --format '{{.Names}}' | grep -qx "$REGISTRY_NAME"; then
    docker rm -f "$REGISTRY_NAME" >/dev/null && _log "removed registry container '${REGISTRY_NAME}'" \
      || _warn "failed to remove registry container '${REGISTRY_NAME}'"
  fi

  # 5. Drop stale kubeconfig
  rm -f "$KUBECONFIG_PATH" && _log "removed stale kubeconfig at $KUBECONFIG_PATH" || true
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

# cmd_clean — the nuclear option. cmd_destroy + extra cleanup of any
# stray docker objects labeled by kind, even when kind itself thinks
# nothing exists. Useful when a previous `kind delete` half-completed
# and left orphan containers / networks behind that confuse the next
# `kind create`. bootstrap-cluster.sh's Step 0 destroy path uses this.
cmd_clean() {
  _preflight 2>/dev/null || true
  cmd_destroy

  # Force-remove any container whose kind cluster label points at us
  # (covers the case where the cluster was deleted via `docker rm` but
  # the kind state file still references the nodes).
  local stragglers
  stragglers="$(docker ps -aq --filter "label=io.x-k8s.kind.cluster=${CLUSTER_NAME}" 2>/dev/null || true)"
  if [ -n "$stragglers" ]; then
    _log "removing $(echo "$stragglers" | wc -l | tr -d ' ') straggler kind container(s)"
    echo "$stragglers" | xargs -r docker rm -f >/dev/null 2>&1 || true
  fi

  # Same for the kind network (the one named `kind` is shared across
  # all kind clusters on the host; only delete it if it has no
  # remaining attached containers).
  if docker network inspect kind >/dev/null 2>&1; then
    local attached
    attached="$(docker network inspect kind --format '{{len .Containers}}' 2>/dev/null || echo 0)"
    if [ "$attached" = "0" ]; then
      docker network rm kind >/dev/null 2>&1 \
        && _log "pruned empty 'kind' docker network" || true
    fi
  fi

  _log "✓ cluster + registry + volumes + network all gone — ready for a clean init"
}

case "${1:-}" in
  init)    cmd_init ;;
  up)      cmd_up ;;
  down)    cmd_down ;;
  status)  cmd_status ;;
  destroy) cmd_destroy ;;
  clean)   cmd_clean ;;
  *) echo "usage: $0 {init|up|down|status|destroy}" >&2; exit 1 ;;
esac
