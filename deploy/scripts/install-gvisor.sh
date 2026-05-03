#!/usr/bin/env bash
# deploy/scripts/install-gvisor.sh
#
# Install gVisor (runsc) into every kind node, register it with each
# node's containerd, restart containerd, then apply the RuntimeClass
# to the cluster.
#
# kind is the only supported cluster runtime since May 2026.  Each
# kind node is a Docker container with its own filesystem and its own
# containerd; this script iterates `docker ps --filter
# label=io.x-k8s.kind.cluster` and `docker exec`s the install +
# config patch into each one.
#
# Idempotent — safe to re-run.  Nodes that already have runsc + the
# containerd handler block are skipped.
#
# Usage:
#   bash deploy/scripts/install-gvisor.sh
#
# After it finishes, `agentRuntime.runtimeClassName: gvisor` (already
# the default for the dev-multinode chart) takes effect on the next
# helm upgrade.

set -euo pipefail
log() { echo "$(date +%H:%M:%S) [gvisor] $*"; }
err() { echo "$(date +%H:%M:%S) [gvisor] ERROR: $*" >&2; }

# Detection: any container with the kind cluster label.
KIND_NODES=$(docker ps --filter "label=io.x-k8s.kind.cluster" --format "{{.Names}}" 2>/dev/null || true)

if [[ -z "$KIND_NODES" ]]; then
  err "No kind cluster detected.  This script only supports kind."
  err "Run 'deploy/scripts/kind-cluster.sh init' first to bring up the"
  err "3-node cluster, then re-run this script."
  exit 1
fi

log "Installing gVisor into kind nodes:"
echo "$KIND_NODES" | sed 's/^/  /'

ARCH=$(docker exec "$(echo "$KIND_NODES" | head -1)" uname -m)
case "$ARCH" in
  x86_64)        RARCH=x86_64 ;;
  aarch64|arm64) RARCH=aarch64 ;;
  *) err "unsupported arch: $ARCH"; exit 1 ;;
esac
URL="https://storage.googleapis.com/gvisor/releases/release/latest/${RARCH}"

# Download once on the host, then docker cp into every node — saves
# bandwidth and keeps the binary identical across nodes.
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

log "  fetching runsc binaries from $URL ..."
curl -fsSL "$URL/runsc"                    -o "$TMPDIR/runsc"
curl -fsSL "$URL/containerd-shim-runsc-v1" -o "$TMPDIR/containerd-shim-runsc-v1"
chmod 755 "$TMPDIR/runsc" "$TMPDIR/containerd-shim-runsc-v1"

cat >"$TMPDIR/runsc.toml" <<'TOML'
[runsc_config]
  binary_name = "/usr/local/bin/runsc"
TOML

RUNSC_BLOCK=$(cat <<'TOML'

# ── gVisor (runsc) — added by install-gvisor.sh ───────────────────────
[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runsc]
  runtime_type = "io.containerd.runsc.v1"
[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runsc.options]
  TypeUrl = "io.containerd.runsc.v1.options"
  ConfigPath = "/etc/containerd/runsc.toml"
TOML
)

for n in $KIND_NODES; do
  log "  patching $n ..."

  # Idempotency check — skip nodes that already have everything.
  if docker exec "$n" test -x /usr/local/bin/runsc \
     && docker exec "$n" test -f /etc/containerd/runsc.toml \
     && [[ "$(docker exec "$n" grep -c 'runtimes\.runsc' /etc/containerd/config.toml 2>/dev/null || echo 0)" -ge 2 ]]; then
    echo "    already patched — skipping"
    continue
  fi

  # Push binaries.
  docker cp "$TMPDIR/runsc"                    "$n:/usr/local/bin/runsc"
  docker cp "$TMPDIR/containerd-shim-runsc-v1" "$n:/usr/local/bin/containerd-shim-runsc-v1"
  docker cp "$TMPDIR/runsc.toml"               "$n:/etc/containerd/runsc.toml"
  docker exec "$n" chmod 755 /usr/local/bin/runsc /usr/local/bin/containerd-shim-runsc-v1

  # Append the runsc block only if not already present.
  if ! docker exec "$n" grep -q 'runtimes\.runsc' /etc/containerd/config.toml; then
    echo "$RUNSC_BLOCK" | docker exec -i "$n" tee -a /etc/containerd/config.toml >/dev/null
    echo "    appended runsc handler to /etc/containerd/config.toml"
  else
    echo "    runsc handler already in /etc/containerd/config.toml"
  fi

  # Restart containerd so the new runtime is registered with the CRI
  # plugin.  kubelet auto-reconnects within a few seconds.
  docker exec "$n" systemctl restart containerd
  echo "    restarted containerd"
done

# Wait for the API server to come back (3 control-plane nodes
# restarting in series can briefly take all kube-apiserver instances
# down at once).
log "Waiting for kube-apiserver to be reachable..."
for i in {1..30}; do
  if kubectl get --raw=/healthz >/dev/null 2>&1; then
    log "  kube-apiserver healthy"
    break
  fi
  sleep 2
done

log "Applying gvisor RuntimeClass..."
kubectl apply -f "$(dirname "$0")/../k8s/runtime/gvisor-runtimeclass.yaml"

log "Install complete.  Custom-agent pods spawned by spm-api with"
log "AGENT_RUNTIME_CLASS=gvisor will now sandbox via runsc."
