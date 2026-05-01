#!/usr/bin/env bash
# deploy/scripts/aispm-cluster.sh
# ──────────────────────────────────────────────────────────────────────
# Day-to-day lifecycle helpers for the kind aispm cluster on Docker
# Desktop. Companion to kind-cluster.sh (which handles init/destroy).
#
# Subcommands:
#   pause     docker pause all 4 kind containers. Cluster freezes in
#             place — TCP connections preserved, leader leases hold,
#             etcd doesn't notice. Run before stepping away when
#             Docker Desktop will keep running.
#
#   resume    docker unpause same containers. Picks up exactly where
#             paused. Survives Mac sleep/wake. Does NOT recover from
#             Docker Quit or Mac reboot — for that you need restore.
#
#   snapshot  Save an etcd snapshot to ~/.aispm/snapshots/. Include
#             in a 10-min cron for safety-net coverage. Does NOT
#             snapshot PV data — that's host-mounted under
#             /tmp/kind-vols and survives independently.
#
#   restore <snapshot-file>
#             Rebuild the 3-node etcd cluster from a snapshot. Use
#             after Docker stop/start leaves the cluster in 'tls:
#             bad certificate' / quorum-lost state (the IP-shuffle
#             scenario). Wipes current etcd data and rebuilds with
#             current container IPs. App state inside K8s comes
#             back from the snapshot; PVs are unaffected.
#
# One-time setup:
#   mkdir -p ~/.aispm/snapshots
#
# Recommended cron entry (while cluster is up):
#   */10 * * * * "$AISPM/deploy/scripts/aispm-cluster.sh" snapshot \
#                  >> ~/.aispm/snapshots.log 2>&1
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

# macOS cron inherits a minimal PATH (/usr/bin:/bin) that does not
# include the typical install paths for docker (/usr/local/bin or
# Apple-Silicon homebrew /opt/homebrew/bin) or kubectl. When this
# script runs from cron without a PATH set, every `docker` call
# returns 127 ("command not found") and the inherited error path
# would misleadingly report "container does not exist". Prefix the
# common locations explicitly so the script behaves the same whether
# launched from an interactive shell or cron.
export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH:-/usr/bin:/bin:/usr/sbin:/sbin}"

CLUSTER_NAME="${CLUSTER_NAME:-aispm}"
SNAPSHOT_DIR="${SNAPSHOT_DIR:-${HOME}/.aispm/snapshots}"
KEEP_SNAPSHOTS="${KEEP_SNAPSHOTS:-50}"
RESTORE_TIMEOUT_SEC="${RESTORE_TIMEOUT_SEC:-180}"

KIND_NODES=(
  "${CLUSTER_NAME}-control-plane"
  "${CLUSTER_NAME}-control-plane2"
  "${CLUSTER_NAME}-control-plane3"
)
KIND_LB="${CLUSTER_NAME}-external-load-balancer"

_log()  { printf '\033[1;36m▶ %s\033[0m\n' "$*"; }
_warn() { printf '\033[1;33m! %s\033[0m\n' "$*"; }
_die()  { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

_all_containers() {
  printf '%s\n' "${KIND_NODES[@]}" "$KIND_LB"
}

_assert_containers_exist() {
  # Surface a clear error when docker itself isn't reachable BEFORE
  # falling through to the per-container inspect loop — otherwise a
  # missing docker on PATH (common in cron) is misreported as a
  # missing container, sending operators down the wrong rabbit hole.
  command -v docker >/dev/null 2>&1 \
    || _die "docker not found on PATH (PATH=$PATH). If running from cron, set PATH at the top of the crontab or use the absolute path to this script."
  docker info >/dev/null 2>&1 \
    || _die "docker daemon is not responding. Is Docker Desktop running?"

  local c
  for c in $(_all_containers); do
    docker inspect -f '{{.State.Status}}' "$c" >/dev/null 2>&1 \
      || _die "Container $c does not exist. Run ./kind-cluster.sh init first."
  done
}

_node_ip() {
  docker inspect -f '{{.NetworkSettings.Networks.kind.IPAddress}}' "$1"
}

_running_etcd_id() {
  # Running etcd container ID inside a kind node, or empty.
  docker exec "$1" crictl ps -q --name etcd 2>/dev/null | head -1 || true
}

_ensure_etcdctl_on_nodes() {
  # kind node base image does NOT include etcdctl/etcdutl on host PATH —
  # they live inside the etcd container image only. Extract them from
  # the etcd image to the host once, then docker-cp into each node.
  local n img tmp
  local need=0
  for n in "${KIND_NODES[@]}"; do
    if ! docker exec "$n" test -x /usr/local/bin/etcdutl 2>/dev/null; then
      need=1; break
    fi
  done
  [ "$need" -eq 1 ] || return 0

  # Determine etcd image from a node's containerd cache.
  for n in "${KIND_NODES[@]}"; do
    img=$(docker exec "$n" crictl images 2>/dev/null \
            | awk '/etcd/ {print $1":"$2; exit}')
    [ -n "$img" ] && break
  done
  [ -n "${img:-}" ] || _die "Cannot determine etcd image from any kind node."
  _log "etcd image: $img"

  _log "Pulling $img on host (one-time, for binary extraction)"
  docker pull "$img" >/dev/null

  tmp=$(docker create "$img" /bin/true)
  trap "docker rm -f $tmp >/dev/null 2>&1 || true" RETURN
  docker cp "$tmp:/usr/local/bin/etcdctl" /tmp/aispm-etcdctl
  docker cp "$tmp:/usr/local/bin/etcdutl" /tmp/aispm-etcdutl 2>/dev/null \
    || _warn "etcdutl not in this etcd image — etcdctl-only fallback will be used"
  docker rm "$tmp" >/dev/null
  trap - RETURN

  for n in "${KIND_NODES[@]}"; do
    _log "Installing etcdctl on $n"
    docker cp /tmp/aispm-etcdctl "$n:/usr/local/bin/etcdctl"
    docker exec "$n" chmod +x /usr/local/bin/etcdctl
    if [ -f /tmp/aispm-etcdutl ]; then
      docker cp /tmp/aispm-etcdutl "$n:/usr/local/bin/etcdutl"
      docker exec "$n" chmod +x /usr/local/bin/etcdutl
    fi
  done
}

# ── pause / resume ────────────────────────────────────────────────────

cmd_pause() {
  _assert_containers_exist
  local c state
  for c in $(_all_containers); do
    state=$(docker inspect -f '{{.State.Status}}' "$c")
    case "$state" in
      paused)  _warn "$c already paused" ;;
      running) docker pause "$c" >/dev/null && _log "paused  $c" ;;
      *)       _warn "$c is in state '$state' — skipping" ;;
    esac
  done
  _log "Cluster paused. Resume with: $0 resume"
  _warn "Pause does NOT survive Docker Quit or Mac reboot."
}

cmd_resume() {
  _assert_containers_exist
  local c state any_exited=0
  for c in $(_all_containers); do
    state=$(docker inspect -f '{{.State.Status}}' "$c")
    case "$state" in
      running) _warn "$c already running" ;;
      paused)  docker unpause "$c" >/dev/null && _log "resumed $c" ;;
      exited)  any_exited=1; _warn "$c is exited (cold-stopped, not paused)" ;;
      *)       _warn "$c is in state '$state' — skipping" ;;
    esac
  done
  if [ "$any_exited" -eq 1 ]; then
    _die "One or more containers were fully stopped, not paused. Run: $0 restore <latest-snapshot>"
  fi
  _log "Cluster resumed. Verify with: kubectl get nodes"
}

# ── snapshot ──────────────────────────────────────────────────────────

cmd_snapshot() {
  _assert_containers_exist
  mkdir -p "$SNAPSHOT_DIR"
  local ts file primary cid n
  ts=$(date +%Y%m%d-%H%M%S)
  file="$SNAPSHOT_DIR/etcd-${ts}.db"

  # Find a control-plane whose etcd container is at least running.
  primary=""
  for n in "${KIND_NODES[@]}"; do
    cid=$(_running_etcd_id "$n")
    [ -n "$cid" ] || continue
    primary="$n"
    break
  done
  [ -n "$primary" ] || _die "No etcd container is running. Cluster needs restore: $0 restore <snapshot>"

  cid=$(_running_etcd_id "$primary")
  _log "Snapshotting etcd on $primary → $file"

  docker exec "$primary" crictl exec "$cid" \
    etcdctl \
      --endpoints=https://127.0.0.1:2379 \
      --cacert=/etc/kubernetes/pki/etcd/ca.crt \
      --cert=/etc/kubernetes/pki/etcd/server.crt \
      --key=/etc/kubernetes/pki/etcd/server.key \
      snapshot save /var/lib/etcd/_aispm-snapshot.db

  docker cp "$primary:/var/lib/etcd/_aispm-snapshot.db" "$file"
  docker exec "$primary" rm -f /var/lib/etcd/_aispm-snapshot.db
  _log "Saved: $file ($(du -h "$file" | cut -f1))"

  # Rotate older snapshots.
  ls -1t "$SNAPSHOT_DIR"/etcd-*.db 2>/dev/null \
    | tail -n +$((KEEP_SNAPSHOTS + 1)) \
    | xargs -r rm --
}

# ── restore ───────────────────────────────────────────────────────────

cmd_restore() {
  local snapshot="${1:-}"
  [ -n "$snapshot" ]    || _die "Usage: $0 restore <snapshot-file>"
  [ -f "$snapshot" ]    || _die "Snapshot not found: $snapshot"
  _assert_containers_exist

  _warn "This will WIPE etcd on all 3 control-plane nodes and restore from:"
  _warn "  $snapshot"
  _warn "PV data and host-mounted volumes are NOT touched."
  _warn "Press Ctrl+C in 5s to abort."
  sleep 5

  # Make sure etcdctl/etcdutl exist on each kind node (one-time install).
  _ensure_etcdctl_on_nodes

  # Discover current IPs and build the initial-cluster string.
  # macOS bash 3.2 has no associative arrays — use parallel arrays
  # indexed positionally with KIND_NODES.
  local idx n ip ic=""
  local NODE_IPS=()
  for n in "${KIND_NODES[@]}"; do
    ip=$(_node_ip "$n")
    [ -n "$ip" ] || _die "Could not get IP for $n. Is the kind network up?"
    NODE_IPS+=("$ip")
    ic+="${n}=https://${ip}:2380,"
    _log "$n → $ip"
  done
  ic="${ic%,}"

  # 1. Pull etcd manifests aside on all 3 nodes; kubelet stops the pods.
  _log "Stopping etcd pods on all 3 nodes (kubelet will follow)"
  for n in "${KIND_NODES[@]}"; do
    docker exec "$n" bash -c '
      if [ -f /etc/kubernetes/manifests/etcd.yaml ]; then
        mv /etc/kubernetes/manifests/etcd.yaml /etc/kubernetes/etcd.yaml.bak
      elif [ ! -f /etc/kubernetes/etcd.yaml.bak ]; then
        echo "no etcd manifest found" >&2; exit 1
      fi
    '
  done
  _log "Waiting 20s for etcd containers to terminate"
  sleep 20

  # 2. On each node: wipe data, restore snapshot, regenerate certs.
  for idx in "${!KIND_NODES[@]}"; do
    n="${KIND_NODES[$idx]}"
    ip="${NODE_IPS[$idx]}"
    _log "Restoring on $n (ip=$ip)"
    docker cp "$snapshot" "$n:/root/aispm-snapshot.db"

    docker exec -e NODE="$n" -e IP="$ip" -e IC="$ic" "$n" bash -c '
      set -euo pipefail
      rm -rf /var/lib/etcd

      if [ -x /usr/local/bin/etcdutl ]; then
        RESTORE_CMD=(/usr/local/bin/etcdutl snapshot restore)
      else
        RESTORE_CMD=(env ETCDCTL_API=3 /usr/local/bin/etcdctl snapshot restore)
      fi

      # --skip-hash-check lets us restore raw /var/lib/etcd/member/snap/db
      # files (no snapshot footer) when an in-band snapshot save could not run.
      "${RESTORE_CMD[@]}" /root/aispm-snapshot.db \
        --name "$NODE" \
        --initial-cluster "$IC" \
        --initial-cluster-token aispm-etcd \
        --initial-advertise-peer-urls "https://${IP}:2380" \
        --skip-hash-check \
        --data-dir /var/lib/etcd

      # Regenerate etcd peer + server certs against the CURRENT node IP.
      # This is the part that fixes the SAN-mismatch failure mode.
      rm -f /etc/kubernetes/pki/etcd/server.crt \
            /etc/kubernetes/pki/etcd/server.key \
            /etc/kubernetes/pki/etcd/peer.crt   \
            /etc/kubernetes/pki/etcd/peer.key
      kubeadm init phase certs etcd-server >/dev/null
      kubeadm init phase certs etcd-peer   >/dev/null

      rm -f /root/aispm-snapshot.db
      echo "  restore complete on $NODE"
    '
  done

  # 3. Rewrite each etcd.yaml with the current IPs & cluster string.
  for idx in "${!KIND_NODES[@]}"; do
    n="${KIND_NODES[$idx]}"
    ip="${NODE_IPS[$idx]}"
    docker exec -e IP="$ip" -e IC="$ic" "$n" bash -c '
      m=/etc/kubernetes/etcd.yaml.bak
      sed -i \
        -e "s|--initial-cluster=[^ \"]*|--initial-cluster=${IC}|" \
        -e "s|--initial-advertise-peer-urls=https://[^ \"]*|--initial-advertise-peer-urls=https://${IP}:2380|" \
        -e "s|--listen-peer-urls=https://[^ \"]*|--listen-peer-urls=https://${IP}:2380|" \
        -e "s|--listen-client-urls=https://[^ \"]*|--listen-client-urls=https://127.0.0.1:2379,https://${IP}:2379|" \
        -e "s|--advertise-client-urls=https://[^ \"]*|--advertise-client-urls=https://${IP}:2379|" \
        -e "s|--initial-cluster-state=existing|--initial-cluster-state=new|" \
        "$m"
    '
  done

  # 4. Put manifests back; kubelet starts etcd as a fresh 3-node cluster.
  _log "Re-enabling etcd manifests"
  for n in "${KIND_NODES[@]}"; do
    docker exec "$n" mv /etc/kubernetes/etcd.yaml.bak /etc/kubernetes/manifests/etcd.yaml
  done

  # 5. Wait for kube-apiserver to come back through the LB.
  _log "Waiting up to ${RESTORE_TIMEOUT_SEC}s for kubectl to respond"
  local i deadline=$((RESTORE_TIMEOUT_SEC / 5))
  for i in $(seq 1 "$deadline"); do
    if kubectl get nodes >/dev/null 2>&1; then
      _log "Cluster is up:"
      kubectl get nodes
      return
    fi
    sleep 5
  done
  _die "Cluster did not come up within ${RESTORE_TIMEOUT_SEC}s. Check: docker exec ${KIND_NODES[0]} crictl logs \$(docker exec ${KIND_NODES[0]} crictl ps -a -q --name etcd | head -1)"
}

# ── dispatch ──────────────────────────────────────────────────────────

case "${1:-}" in
  pause)    cmd_pause ;;
  resume)   cmd_resume ;;
  snapshot) cmd_snapshot ;;
  restore)  shift; cmd_restore "$@" ;;
  *)        _die "Usage: $0 {pause|resume|snapshot|restore <file>}" ;;
esac
