#!/usr/bin/env bash
# deploy/scripts/install-gvisor.sh
#
# Install gVisor (runsc) into the local Linux VM that hosts your k8s
# cluster, register it with containerd, restart the k8s service, and
# apply the RuntimeClass.
#
# Auto-detects the VM provider:
#   - Rancher Desktop (rdctl shell)  — k3s, containerd config rendered
#                                       from /var/lib/rancher/k3s/...
#   - OrbStack          (orb run)    — k8s ships with its own
#                                       containerd; config under /etc/containerd
#   - Manual fallback                — prints the install steps so you can
#                                       run them inside whatever VM you have
#
# Idempotent — safe to re-run.
#
# Usage:
#   bash deploy/scripts/install-gvisor.sh
#
# After it finishes, ``agentRuntime.runtimeClassName: gvisor`` in
# values.dev.yaml (already the default) takes effect on the next
# helm upgrade.

set -euo pipefail
log() { echo "$(date +%H:%M:%S) [gvisor] $*"; }
err() { echo "$(date +%H:%M:%S) [gvisor] ERROR: $*" >&2; }

# ── Detect VM provider ────────────────────────────────────────────────────
# Walk the candidates in priority order and pick the first one with both
# (a) a CLI on $PATH and (b) a Linux VM responding to a trivial command.
PROVIDER=""
SHELL_CMD=""
if command -v rdctl  >/dev/null 2>&1 && rdctl  shell -- true >/dev/null 2>&1; then
  PROVIDER="rancher-desktop"
  SHELL_CMD="rdctl shell --"
elif command -v orb   >/dev/null 2>&1 && orb run -- true     >/dev/null 2>&1; then
  PROVIDER="orbstack"
  SHELL_CMD="orb run --"
elif command -v limactl >/dev/null 2>&1 && limactl shell default true >/dev/null 2>&1; then
  PROVIDER="lima"
  SHELL_CMD="limactl shell default --"
else
  err "No supported VM provider detected (Rancher Desktop / OrbStack / Lima)."
  err "Manual steps for any Linux host running containerd:"
  err "  1) Drop runsc + containerd-shim-runsc-v1 into /usr/local/bin"
  err "  2) Append the runsc handler to the live containerd config"
  err "  3) Restart whichever process supervises containerd"
  exit 1
fi
log "VM provider: $PROVIDER (shell: $SHELL_CMD)"

# Helper — run a shell snippet inside the detected VM.
in_vm() { eval "$SHELL_CMD bash -se" <<<"$1"; }
in_vm_sudo() { eval "$SHELL_CMD sudo bash -se" <<<"$1"; }

# ── 1. Install runsc binaries inside the VM ──────────────────────────────
log "Installing runsc + containerd shim inside the $PROVIDER VM..."
$SHELL_CMD bash -se <<'EOS'
set -euo pipefail

ARCH=$(uname -m)
case "$ARCH" in
  x86_64)  RARCH=x86_64 ;;
  aarch64|arm64) RARCH=aarch64 ;;
  *) echo "unsupported arch: $ARCH" >&2; exit 1 ;;
esac

URL="https://storage.googleapis.com/gvisor/releases/release/latest/${RARCH}"

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

# Provide a runsc.toml that points the shim at the binary explicitly
# (some distros default to /usr/bin/runsc).
sudo mkdir -p /etc/containerd
sudo tee /etc/containerd/runsc.toml >/dev/null <<'TOML'
[runsc_config]
  binary_name = "/usr/local/bin/runsc"
TOML
EOS

# ── 2. Register runsc with the right containerd config ───────────────────
# Different k8s providers store containerd config in different places:
#   - Rancher Desktop: k3s renders from a *.tmpl that we have to extend.
#   - OrbStack:        k8s uses the system containerd at /etc/containerd/config.toml
#                      directly — patch that file and bounce containerd.
#   - Lima:            same as OrbStack — system containerd at /etc/containerd/.
RUNSC_BLOCK=$(cat <<'TOML'

# ── gVisor (runsc) — added by install-gvisor.sh ───────────────────────
[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runsc]
  runtime_type = "io.containerd.runsc.v1"
[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runsc.options]
  TypeUrl = "io.containerd.runsc.v1.options"
  ConfigPath = "/etc/containerd/runsc.toml"
TOML
)

if [[ "$PROVIDER" = "rancher-desktop" ]]; then
  log "Registering runsc with k3s containerd template..."
  $SHELL_CMD sudo bash -se <<EOS
set -euo pipefail
TPL=/var/lib/rancher/k3s/agent/etc/containerd/config.toml.tmpl
RENDERED=/var/lib/rancher/k3s/agent/etc/containerd/config.toml
mkdir -p "\$(dirname "\$TPL")"
if [[ ! -f "\$TPL" ]]; then
  if [[ -f "\$RENDERED" ]]; then
    cp "\$RENDERED" "\$TPL"
  else
    touch "\$TPL"
  fi
fi
if grep -q 'runtimes.runsc' "\$TPL"; then
  echo "  runsc handler already in \$TPL"
else
  cat >>"\$TPL" <<'TOML'
$RUNSC_BLOCK
TOML
  echo "  appended runsc handler to \$TPL"
fi
EOS
else
  # OrbStack / Lima — patch the live system containerd config.
  log "Registering runsc with system containerd..."
  $SHELL_CMD sudo bash -se <<EOS
set -euo pipefail
CFG=/etc/containerd/config.toml
[ -f "\$CFG" ] || { echo "MISSING \$CFG"; exit 1; }
if grep -q 'runtimes.runsc' "\$CFG"; then
  echo "  runsc handler already in \$CFG"
else
  cp "\$CFG" "\${CFG}.bak.\$(date +%s)"
  cat >>"\$CFG" <<'TOML'
$RUNSC_BLOCK
TOML
  echo "  appended runsc handler to \$CFG"
fi
EOS
fi

# ── 3. Restart whichever process supervises containerd ───────────────────
log "Restarting containerd / k8s service so the new handler is loaded..."
$SHELL_CMD sudo bash -c '
  if systemctl list-unit-files 2>/dev/null | grep -q "^k3s.service"; then
    systemctl restart k3s && echo "  restarted k3s via systemd"
  elif [ -x /etc/init.d/k3s ]; then
    /etc/init.d/k3s restart && echo "  restarted k3s via init.d"
  elif systemctl list-unit-files 2>/dev/null | grep -q "^containerd.service"; then
    systemctl restart containerd && echo "  restarted containerd via systemd"
  elif command -v rc-service >/dev/null 2>&1 && rc-service -e containerd 2>/dev/null; then
    rc-service containerd restart && echo "  restarted containerd via openrc"
  else
    echo "  WARNING: no known supervisor for containerd; restart Rancher Desktop / OrbStack manually"
  fi
'

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
