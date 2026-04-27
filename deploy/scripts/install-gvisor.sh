#!/usr/bin/env bash
# deploy/scripts/install-gvisor.sh
#
# Install gVisor (runsc) into the Rancher Desktop / Lima VM that
# hosts your k3s cluster, register it with containerd, restart k3s,
# and apply the RuntimeClass.
#
# Idempotent — safe to re-run.
#
# Usage:
#   bash deploy/scripts/install-gvisor.sh
#
# After it finishes, set agentRuntime.runtimeClassName: gvisor in
# values.dev.yaml (already the default) and `helm upgrade` to roll
# spm-api with AGENT_RUNTIME_CLASS=gvisor.

set -euo pipefail
log() { echo "$(date +%H:%M:%S) [gvisor] $*"; }
err() { echo "$(date +%H:%M:%S) [gvisor] ERROR: $*" >&2; }

if ! command -v rdctl >/dev/null 2>&1; then
  err "rdctl not found — Rancher Desktop CLI required to enter the Lima VM."
  err "Install Rancher Desktop, or run the steps below manually inside the VM:"
  err "  1) Drop runsc + containerd-shim-runsc-v1 into /usr/local/bin"
  err "  2) sudo runsc install"
  err "  3) sudo systemctl restart k3s    (or whichever supervises containerd)"
  exit 1
fi

# ── 1. Install runsc binaries + register with k3s's containerd ────────────
log "Installing runsc + containerd shim inside the Lima VM..."
rdctl shell -- bash -se <<'EOS'
set -euo pipefail

ARCH=$(uname -m)
case "$ARCH" in
  x86_64)  RARCH=x86_64 ;;
  aarch64|arm64) RARCH=aarch64 ;;
  *) echo "unsupported arch: $ARCH" >&2; exit 1 ;;
esac

URL="https://storage.googleapis.com/gvisor/releases/release/latest/${RARCH}"

# Binaries land in /usr/local/bin so containerd can exec them.
NEED_REINSTALL=0
for f in /usr/local/bin/runsc /usr/local/bin/containerd-shim-runsc-v1; do
  if [[ ! -x "$f" ]]; then NEED_REINSTALL=1; break; fi
done

if [[ $NEED_REINSTALL -eq 1 ]]; then
  echo "  fetching $URL ..."
  sudo curl -fsSL "$URL/runsc"                    -o /usr/local/bin/runsc
  sudo curl -fsSL "$URL/containerd-shim-runsc-v1" -o /usr/local/bin/containerd-shim-runsc-v1
  sudo chmod 755 /usr/local/bin/runsc /usr/local/bin/containerd-shim-runsc-v1
  echo "  installed runsc $(/usr/local/bin/runsc --version 2>/dev/null | head -1 || echo 'unknown')"
else
  echo "  runsc already present — skipping download"
fi

# ── k3s containerd config ────────────────────────────────────────────────
# k3s does NOT honor /etc/containerd/config.toml. It regenerates its own
# config from /var/lib/rancher/k3s/agent/etc/containerd/config.toml.tmpl
# on every k3s restart. To register the runsc handler we must extend
# the template — appending a runtimes.runsc block — then restart k3s
# so the new config gets rendered + loaded.
TPL=/var/lib/rancher/k3s/agent/etc/containerd/config.toml.tmpl
RENDERED=/var/lib/rancher/k3s/agent/etc/containerd/config.toml
TPL_DIR=$(dirname "$TPL")

sudo mkdir -p "$TPL_DIR"

# Seed the template from the rendered config the first time.
if [[ ! -f "$TPL" ]]; then
  if [[ -f "$RENDERED" ]]; then
    echo "  seeding $TPL from current rendered config"
    sudo cp "$RENDERED" "$TPL"
  else
    echo "  no existing containerd config found — k3s will regenerate one"
    sudo touch "$TPL"
  fi
fi

if sudo grep -q 'plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runsc' "$TPL"; then
  echo "  runsc handler already in $TPL — skipping append"
else
  echo "  appending runsc handler to $TPL"
  sudo tee -a "$TPL" >/dev/null <<'TOML'

# ── gVisor (runsc) — added by install-gvisor.sh ───────────────────────
[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runsc]
  runtime_type = "io.containerd.runsc.v1"
[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runsc.options]
  TypeUrl = "io.containerd.runsc.v1.options"
  ConfigPath = "/etc/containerd/runsc.toml"
TOML
fi

# Provide a runsc.toml that points the shim at the binary explicitly
# (some distros default to /usr/bin/runsc).
sudo tee /etc/containerd/runsc.toml >/dev/null <<'TOML'
[runsc_config]
  binary_name = "/usr/local/bin/runsc"
TOML
EOS

# ── 3. Restart k3s so containerd picks up the new shim ────────────────────
log "Restarting k3s so containerd reloads its runtime registry..."
rdctl shell -- bash -c "sudo systemctl restart k3s 2>/dev/null || sudo /etc/init.d/k3s restart"

# Give the API server a moment to come back
log "Waiting for kube-apiserver to be reachable..."
for i in {1..30}; do
  if kubectl get --raw=/healthz >/dev/null 2>&1; then
    log "  kube-apiserver healthy"
    break
  fi
  sleep 2
done

# ── 4. Apply the RuntimeClass manifest ────────────────────────────────────
log "Applying gvisor RuntimeClass..."
kubectl apply -f "$(dirname "$0")/../k8s/runtime/gvisor-runtimeclass.yaml"

# ── 5. Smoke test — schedule a one-shot pod with runtimeClassName: gvisor
log "Smoke test — running a tiny pod under runsc..."
cat <<'EOF' | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: gvisor-smoketest
  namespace: default
spec:
  runtimeClassName: gvisor
  restartPolicy: Never
  containers:
    - name: t
      image: docker.io/library/alpine:3.19
      command: ["sh","-c","uname -a; cat /proc/version; echo OK; exit 0"]
EOF

kubectl wait --for=condition=Ready --timeout=60s pod/gvisor-smoketest 2>/dev/null || true
log "Smoke test pod log:"
kubectl logs gvisor-smoketest 2>&1 | sed 's/^/  /'
kubectl delete pod gvisor-smoketest --ignore-not-found --grace-period=0 --force 2>/dev/null || true

log "Done. Set agentRuntime.runtimeClassName: gvisor in values.dev.yaml"
log "and 'helm upgrade aispm ...' to roll spm-api."
