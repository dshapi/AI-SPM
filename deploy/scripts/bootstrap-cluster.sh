#!/usr/bin/env bash
# deploy/scripts/bootstrap-cluster.sh
#
# Single-command cluster setup. Provider-aware (Rancher Desktop /
# OrbStack / Lima); idempotent; safe to re-run on an existing cluster.
#
# What this does, in order:
#   1.  Sanity-check kubectl context + container runtime
#   2.  Create namespaces (aispm, aispm-agents) with the right labels
#   3.  Build all images into the cluster's containerd image store
#   4.  Install gVisor runtime (if requested, on by default in dev)
#   5.  Install cluster-level addons (helm):
#         cert-manager, ingress-nginx, istio-cni (optional),
#         falco + falcosidekick, tetragon, kyverno
#   6.  Render the AISPM helm chart with values.yaml + values.dev.yaml
#       and apply (skipping helm release tracking — see comment in
#       step 6 for why this is the simpler path on dev)
#   7.  Apply Kyverno cluster policies (admission gating)
#   8.  Wait for the platform to be healthy
#   9.  Print next steps (chat URL, agent upload, etc.)
#
# Usage:
#   bash deploy/scripts/bootstrap-cluster.sh           # full install
#   SKIP_GVISOR=1 bash deploy/scripts/bootstrap-cluster.sh
#   SKIP_RUNTIME_SECURITY=1 bash deploy/scripts/bootstrap-cluster.sh
#   bash deploy/scripts/bootstrap-cluster.sh chart     # only re-apply chart
#   bash deploy/scripts/bootstrap-cluster.sh policies  # only re-apply Kyverno
#
# Env knobs (all optional):
#   SKIP_GVISOR=1            don't install runsc
#   SKIP_RUNTIME_SECURITY=1  skip Falco + Tetragon
#   SKIP_KYVERNO=1           skip Kyverno + cluster policies
#   SKIP_INGRESS=1           skip ingress-nginx
#   SKIP_CERT_MANAGER=1      skip cert-manager
#   ENABLE_ISTIO_CNI=1       install istio-cni (default OFF — on OrbStack
#                            and many local k8s providers istio-cni
#                            corrupts pod networking; the legacy
#                            istio-init initContainer is more reliable
#                            for dev. Set to 1 only for prod kubeadm/GKE.)
#   VALUES_FILE=values.dev.yaml      override which values file to render
#
# Designed to make the OrbStack migration a one-liner — quit Rancher
# Desktop, install OrbStack, enable its k8s, run this script.

set -euo pipefail

# ── Path setup ───────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEPLOY="$REPO_ROOT/deploy"
HELM_CHART="$DEPLOY/helm/aispm"
VALUES_FILE="${VALUES_FILE:-$HELM_CHART/values.dev.yaml}"
TARGET="${1:-all}"

log()  { echo "$(date +%H:%M:%S) [bootstrap] $*"; }
warn() { echo "$(date +%H:%M:%S) [bootstrap] WARN: $*" >&2; }
err()  { echo "$(date +%H:%M:%S) [bootstrap] ERROR: $*" >&2; }
section() { echo; echo "═══ $* ═══"; }

# ── 1. Sanity ────────────────────────────────────────────────────────────
section "Step 1: sanity"

require() {
  command -v "$1" >/dev/null 2>&1 || { err "missing required command: $1"; exit 1; }
}
require kubectl
require helm

CTX="$(kubectl config current-context 2>/dev/null || true)"
[ -n "$CTX" ] || { err "no kubectl context set"; exit 1; }
log "kubectl context: $CTX"

NODE_RUNTIME="$(kubectl get nodes -o jsonpath='{.items[0].status.nodeInfo.containerRuntimeVersion}' 2>/dev/null || true)"
log "container runtime: ${NODE_RUNTIME:-unknown}"

case "$NODE_RUNTIME" in
  containerd*) log "  ok — containerd is supported";;
  docker*)     log "  ok — docker (OrbStack) ships containerd internally; gvisor in-cluster Job handles its config";;
  *)           warn "  unrecognized runtime ($NODE_RUNTIME) — proceeding anyway";;
esac

# ── 2. Namespaces + RBAC + secrets ───────────────────────────────────────
section "Step 2: namespaces, RBAC, jwt-keys"
if [ "$TARGET" = "all" ] || [ "$TARGET" = "namespaces" ]; then
  kubectl apply -f "$DEPLOY/k8s/namespaces/aispm.yaml"        2>/dev/null \
    || kubectl create namespace aispm        --dry-run=client -o yaml | kubectl apply -f -
  kubectl apply -f "$DEPLOY/k8s/namespaces/aispm-agents.yaml" 2>/dev/null \
    || kubectl create namespace aispm-agents --dry-run=client -o yaml | kubectl apply -f -
  log "  aispm + aispm-agents present"

  # ServiceAccounts that referenced-but-not-defined Deployments need.
  # spm-api SA carries the RBAC token to create pods/configmaps in
  # aispm-agents (the agent-runtime control plane). agent-runtime SA
  # is mounted on agent pods.
  for f in "$DEPLOY/k8s/rbac/spm-api-sa.yaml" \
           "$DEPLOY/k8s/rbac/agent-runtime-sa.yaml"; do
    if [ -f "$f" ]; then
      kubectl apply -f "$f"
      log "  applied $(basename "$f")"
    else
      warn "  missing $f — Deployments referencing those SAs will fail to schedule"
    fi
  done

  # jwt-keys secret — many platform services mount /keys read-only and
  # use the RSA private key to sign service JWTs. Generate a keypair
  # under ./keys if not present, then upsert the Secret.
  if [ ! -f "$REPO_ROOT/keys/private.pem" ]; then
    log "  generating fresh JWT keypair under $REPO_ROOT/keys/"
    mkdir -p "$REPO_ROOT/keys"
    openssl genpkey -algorithm RSA -out "$REPO_ROOT/keys/private.pem" \
      -pkeyopt rsa_keygen_bits:2048 >/dev/null 2>&1
    openssl rsa -pubout -in "$REPO_ROOT/keys/private.pem" \
      -out "$REPO_ROOT/keys/public.pem" >/dev/null 2>&1
  fi
  kubectl -n aispm create secret generic jwt-keys \
    --from-file=private.pem="$REPO_ROOT/keys/private.pem" \
    --from-file=public.pem="$REPO_ROOT/keys/public.pem" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  log "  jwt-keys secret upserted"

  # platform-secrets — LLM API keys + anything else the chart's
  # Secret expects. We read from $REPO_ROOT/.env (gitignored, see
  # .env.example for shape) and merge into the chart-rendered
  # Secret. Without this, every cluster reset would mean
  # re-pasting the Anthropic key.
  if [ -f "$REPO_ROOT/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$REPO_ROOT/.env"
    set +a
    PATCH_DATA=""
    for var in ANTHROPIC_API_KEY OPENAI_API_KEY OLLAMA_BASE_URL; do
      val="${!var:-}"
      [ -n "$val" ] || continue
      enc="$(printf '%s' "$val" | base64 | tr -d '\n')"
      PATCH_DATA="${PATCH_DATA}\"$var\":\"$enc\","
    done
    if [ -n "$PATCH_DATA" ]; then
      PATCH_DATA="${PATCH_DATA%,}"
      # Use create-or-merge: ensure secret exists first (chart may
      # not have applied yet on first run).
      kubectl -n aispm create secret generic platform-secrets \
        --dry-run=client -o yaml | kubectl apply -f - >/dev/null 2>&1 || true
      kubectl -n aispm patch secret platform-secrets --type=merge \
        -p "{\"data\":{$PATCH_DATA}}" >/dev/null
      log "  platform-secrets merged from .env (LLM keys)"
    fi
  else
    log "  no .env file at repo root — skipping platform-secrets merge (set ANTHROPIC_API_KEY etc. in .env to persist)"
  fi

  # PVCs (storage class, model upload PVC, flink checkpoints, etc.)
  # and NetworkPolicies live under deploy/k8s/. Helm chart references
  # them by name but doesn't create them — apply the directories.
  for dir in "$DEPLOY/k8s/storage" "$DEPLOY/k8s/network-policies" "$DEPLOY/k8s/runtime"; do
    if [ -d "$dir" ]; then
      kubectl apply -f "$dir" 2>&1 | grep -vE 'unchanged|created|configured' >&2 || true
      log "  applied $(ls "$dir" | wc -l | tr -d ' ') manifest(s) from $(basename "$dir")/"
    fi
  done
fi

# ── 3. Build images ──────────────────────────────────────────────────────
section "Step 3: build images"
if [ "$TARGET" = "all" ] || [ "$TARGET" = "images" ]; then
  # chmod +x in case the repo lost the executable bit (e.g. fresh
  # clone on a Windows-friendly filesystem, or zip extraction).
  chmod +x "$DEPLOY/scripts/build-images.sh" 2>/dev/null || true
  if [ -x "$DEPLOY/scripts/build-images.sh" ]; then
    bash "$DEPLOY/scripts/build-images.sh" || warn "image build returned non-zero — continuing"
  else
    warn "build-images.sh not executable — skipping image build"
  fi
fi

# ── 3.5. kube-dns IPv4 only ──────────────────────────────────────────────
# OrbStack's k8s is dual-stack. kube-dns ends up dual-stack too, but its
# IPv6 ClusterIP isn't actually routable, which makes Go-based clients
# (falcoctl, anything resolving via Go's net package) randomly fail with
# "connection refused" on the IPv6 nameserver. Force IPv4-only — saw it
# the hard way today.
if [ "$TARGET" = "all" ] || [ "$TARGET" = "addons" ]; then
  section "Step 3.5: kube-dns IPv4 SingleStack"
  CURRENT_FAMILIES=$(kubectl -n kube-system get svc kube-dns -o jsonpath='{.spec.ipFamilyPolicy}' 2>/dev/null || true)
  if [ "$CURRENT_FAMILIES" != "SingleStack" ]; then
    kubectl -n kube-system patch svc kube-dns --type=merge \
      -p '{"spec":{"ipFamilies":["IPv4"],"ipFamilyPolicy":"SingleStack"}}' \
      2>/dev/null && log "  patched kube-dns to IPv4 SingleStack" \
      || warn "  kube-dns ipFamilies patch failed (may need svc recreate — see deploy/scripts/diag-dns.sh)"
    kubectl -n kube-system rollout restart deploy/coredns >/dev/null 2>&1 || true
  else
    log "  kube-dns already SingleStack"
  fi
fi

# ── 4. gVisor runtime ────────────────────────────────────────────────────
section "Step 4: gVisor runtime"
if [ "$TARGET" = "all" ] || [ "$TARGET" = "gvisor" ]; then
  if [ "${SKIP_GVISOR:-0}" = "1" ]; then
    log "  SKIP_GVISOR=1 — skipping"
  elif printf '%s' "$NODE_RUNTIME" | grep -qi '^docker'; then
    # OrbStack and Docker Desktop k8s use Docker as the CRI. Docker
    # doesn't dispatch RuntimeClass to extra runtimes — it needs
    # /etc/docker/daemon.json edits that OrbStack doesn't expose.
    # We confirmed empirically: the in-cluster installer Job lays
    # down runsc but pod admission fails with "RuntimeHandler
    # 'runsc' not supported".
    warn "  Docker-based runtime detected — gVisor is unreachable on this cluster."
    warn "  Skipping. Defense-in-depth still applies (Restricted PSS,"
    warn "  NetworkPolicy, AuthorizationPolicy, Tetragon, Falco)."
    warn "  In prod set ENABLE_GVISOR=1 on a containerd cluster (kubeadm/GKE/EKS)."
  else
    # Containerd cluster: try host-side script first (works on
    # Rancher Desktop / Lima). Fall back to in-cluster Job for
    # any provider the script can't detect.
    if ! bash "$DEPLOY/scripts/install-gvisor.sh" 2>/dev/null; then
      warn "  host-side gvisor install failed — falling back to in-cluster Job"
      if [ -f "$DEPLOY/k8s/runtime/gvisor-installer-job.yaml" ]; then
        kubectl apply -f "$DEPLOY/k8s/runtime/gvisor-installer-job.yaml" \
          || warn "  gvisor-installer-job apply failed"
        kubectl -n kube-system wait --for=condition=Complete \
          --timeout=180s job/gvisor-installer 2>/dev/null \
          || warn "  gvisor-installer job didn't complete in 3m"
        kubectl apply -f "$DEPLOY/k8s/runtime/gvisor-runtimeclass.yaml" \
          || warn "  gvisor-runtimeclass apply failed"
      fi
    fi
  fi
fi

# ── helm-install helper — idempotent (upgrade --install) ─────────────────
helm_install() {
  local release="$1"; shift
  local repo="$1"; shift
  local chart="$1"; shift
  local namespace="$1"; shift
  log "  helm: $release ($repo $chart) → $namespace"
  helm repo add "$(echo "$repo" | cut -d/ -f1)" "https://$repo" >/dev/null 2>&1 || true
  helm repo update >/dev/null 2>&1 || true
  helm upgrade --install "$release" "$chart" \
    --namespace "$namespace" --create-namespace \
    --wait --timeout=5m "$@" || warn "    $release helm op returned non-zero — continuing"
}

# ── 5. Cluster-level addons ──────────────────────────────────────────────
if [ "$TARGET" = "all" ] || [ "$TARGET" = "addons" ]; then
  section "Step 5a: cert-manager"
  if [ "${SKIP_CERT_MANAGER:-0}" != "1" ]; then
    helm repo add jetstack https://charts.jetstack.io >/dev/null 2>&1 || true
    helm repo update jetstack >/dev/null 2>&1 || true
    helm upgrade --install cert-manager jetstack/cert-manager \
      -n cert-manager --create-namespace \
      --version v1.16.2 --set crds.enabled=true \
      --wait --timeout=5m \
      || warn "  cert-manager helm returned non-zero"
  fi

  section "Step 5a2: local-path-provisioner"
  # OrbStack ships the `local-path` StorageClass but NOT the
  # provisioner pod that actually creates PVs. Without this, every
  # PVC sits in Pending forever (saw it the hard way). Apply
  # rancher's stock provisioner manifest — idempotent.
  if [ "${SKIP_LOCAL_PATH:-0}" != "1" ]; then
    if ! kubectl -n local-path-storage get deploy local-path-provisioner >/dev/null 2>&1; then
      kubectl apply -f \
        https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.30/deploy/local-path-storage.yaml \
        || warn "  local-path-provisioner apply returned non-zero"
      kubectl -n local-path-storage rollout status deploy/local-path-provisioner --timeout=120s \
        || warn "  local-path-provisioner did not become ready"
    else
      log "  local-path-provisioner already installed"
    fi
  fi

  section "Step 5b: ingress-nginx"
  if [ "${SKIP_INGRESS:-0}" != "1" ]; then
    helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx >/dev/null 2>&1 || true
    helm repo update ingress-nginx >/dev/null 2>&1 || true
    helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
      -n ingress-nginx --create-namespace \
      --set controller.service.type=LoadBalancer \
      --wait --timeout=5m \
      || warn "  ingress-nginx helm returned non-zero"
  fi

  section "Step 5c: Istio (base + istiod + cni + ingress gateway)"
  if [ "${SKIP_ISTIO:-0}" != "1" ]; then
    ISTIO_VER="${ISTIO_VERSION:-1.24.3}"
    helm repo add istio https://istio-release.storage.googleapis.com/charts >/dev/null 2>&1 || true
    helm repo update istio >/dev/null 2>&1 || true

    # 1) base — installs the Istio CRDs and the istio-system namespace.
    helm upgrade --install istio-base istio/base \
      -n istio-system --create-namespace --version "$ISTIO_VER" \
      --wait --timeout=5m \
      || warn "    istio-base helm returned non-zero"

    # 2) istiod — control plane. When istio-cni is installed,
    # pilot.cni.enabled=true so the injector skips the istio-init
    # container. Without istio-cni, set it false so the injector
    # adds the init container (which needs Baseline PSS — fine for dev).
    PILOT_CNI=false
    [ "${ENABLE_ISTIO_CNI:-0}" = "1" ] && PILOT_CNI=true
    helm upgrade --install istiod istio/istiod \
      -n istio-system --version "$ISTIO_VER" \
      --set "pilot.cni.enabled=$PILOT_CNI" \
      --wait --timeout=5m \
      || warn "    istiod helm returned non-zero"

    # 3) istio-cni — opt-in. On OrbStack we observed it leaving
    # iptables in a state that blackholes pod-to-pod traffic. Skip
    # by default; rely on the istio-init initContainer instead.
    if [ "${ENABLE_ISTIO_CNI:-0}" = "1" ]; then
      # Path differs per provider:
      #   Rancher Desktop (k3s)        → /usr/libexec/cni
      #   OrbStack / kubeadm / GKE     → /opt/cni/bin
      if [ -z "${CNI_BIN_DIR:-}" ]; then
        for cand in /opt/cni/bin /usr/libexec/cni; do
          if $SHELL_CMD test -d "$cand" 2>/dev/null; then
            CNI_BIN_DIR="$cand"
            break
          fi
        done
        CNI_BIN_DIR="${CNI_BIN_DIR:-/opt/cni/bin}"
      fi
      log "  CNI binary directory: $CNI_BIN_DIR"
      helm upgrade --install istio-cni istio/cni \
        -n istio-system --version "$ISTIO_VER" \
        --set cni.cniBinDir="$CNI_BIN_DIR" \
        --wait --timeout=5m \
        || warn "    istio-cni helm returned non-zero — try CNI_BIN_DIR=/usr/libexec/cni or /opt/cni/bin"
    else
      log "  istio-cni: SKIPPED (set ENABLE_ISTIO_CNI=1 to install)"
    fi

    # 4) ingress gateway — OPTIONAL on dev. Istio's gateway chart in
    # 1.24.3 has a values-schema bug ("additional properties
    # '_internal_defaults_do_not_set' not allowed") when installed
    # alongside istiod via helm. Skip by default — the chart's
    # Gateway/VirtualService resources still apply and can be backed
    # by traefik (Rancher Desktop) or ingress-nginx (anywhere) for
    # dev. Set INSTALL_ISTIO_GATEWAY=1 to attempt the helm install
    # anyway (or use istioctl: `istioctl install --set
    # components.ingressGateways[0].enabled=true`).
    if [ "${INSTALL_ISTIO_GATEWAY:-0}" = "1" ]; then
      helm upgrade --install istio-ingressgateway istio/gateway \
        -n istio-system --version "$ISTIO_VER" \
        --wait --timeout=5m \
        || warn "    istio-gateway helm returned non-zero — try istioctl install instead"
    else
      log "  istio-ingressgateway skipped (dev uses traefik/ingress-nginx; set INSTALL_ISTIO_GATEWAY=1 to enable)"
    fi

    log "  Istio $ISTIO_VER installed (base + istiod${SKIP_ISTIO_CNI:+}${SKIP_ISTIO_CNI:-+ cni}${INSTALL_ISTIO_GATEWAY:++ gateway})"
  fi

  section "Step 5d: falco + falcosidekick"
  # Pin to chart 4.20.x / falco 0.42.x — falco 0.43.x has an upstream
  # duplicate-container-plugin bug that crashloops on every install
  # (https://github.com/falcosecurity/falco/issues/3257-style).
  # falcoctl.artifact.install/follow disabled because they hit
  # ghcr.io on every pod boot — flaky on first install. Rules
  # baked into the image are enough.
  if [ "${SKIP_RUNTIME_SECURITY:-0}" != "1" ]; then
    helm repo add falcosecurity https://falcosecurity.github.io/charts >/dev/null 2>&1 || true
    helm repo update falcosecurity >/dev/null 2>&1 || true
    FALCO_CHART_VERSION="${FALCO_CHART_VERSION:-4.20.5}"
    helm upgrade --install falco falcosecurity/falco \
      -n falco --create-namespace \
      --version "$FALCO_CHART_VERSION" \
      --set driver.kind=modern_ebpf \
      --set falcosidekick.enabled=true \
      --set falco.http_output.enabled=true \
      --set falco.http_output.url=http://falco-falcosidekick:2801/ \
      --set falcosidekick.config.kafka.hostport="kafka-broker.aispm.svc.cluster.local:9092" \
      --set falcosidekick.config.kafka.topic="security.falco.events" \
      --set falcoctl.artifact.install.enabled=false \
      --set falcoctl.artifact.follow.enabled=false \
      --wait --timeout=5m \
      || warn "  falco helm returned non-zero"
    # falcoctl.artifact.install/follow disabled because they hit
    # ghcr.io and falcosecurity.github.io on every pod boot, and on
    # OrbStack's flaky DNS that pinned the init container in
    # CrashLoopBackOff. Rules baked into the image are enough for
    # dev. Re-enable in prod (values.prod.yaml) where DNS is stable.
  fi

  section "Step 5e: tetragon"
  if [ "${SKIP_RUNTIME_SECURITY:-0}" != "1" ]; then
    helm repo add cilium https://helm.cilium.io >/dev/null 2>&1 || true
    helm repo update cilium >/dev/null 2>&1 || true
    helm upgrade --install tetragon cilium/tetragon \
      -n kube-system \
      --set tetragon.enabled=true \
      --set tetragon.bpf.autoMount.enabled=false \
      --wait --timeout=5m \
      || warn "  tetragon helm returned non-zero (often needs 'mount --make-rshared /sys' inside the VM first)"
  fi

  section "Step 5f: kyverno"
  if [ "${SKIP_KYVERNO:-0}" != "1" ]; then
    helm repo add kyverno https://kyverno.github.io/kyverno >/dev/null 2>&1 || true
    helm repo update kyverno >/dev/null 2>&1 || true
    # Pin to 3.3.7 — newer chart's CRDs use selectableFields (k8s 1.30+).
    helm upgrade --install kyverno kyverno/kyverno \
      -n kyverno --create-namespace --version 3.3.7 \
      --set admissionController.replicas=1 \
      --set backgroundController.replicas=1 \
      --set cleanupController.replicas=1 \
      --set reportsController.replicas=1 \
      --wait --timeout=5m \
      || warn "  kyverno helm returned non-zero"
  fi
fi

# ── 6. Render + apply the AISPM chart ────────────────────────────────────
# We do `helm template | kubectl apply` rather than `helm upgrade` because:
#   - The chart includes CRDs gated by .Capabilities.APIVersions.Has(...);
#     `helm template` lets us pass --api-versions explicitly so Istio /
#     Kyverno / Cilium CRD-conditional templates render even on a fresh
#     install where those CRDs were just added in the same script run.
#   - kubectl apply tolerates partial resources better than helm release
#     tracking on a dev cluster that gets reset frequently.
#   - PVC / StatefulSet data persists across runs because kubectl apply
#     never touches them on update.
if [ "$TARGET" = "all" ] || [ "$TARGET" = "chart" ]; then
  section "Step 6: AISPM chart"
  RENDERED=/tmp/aispm-rendered.yaml
  helm template aispm "$HELM_CHART" -n aispm \
    -f "$HELM_CHART/values.yaml" \
    -f "$VALUES_FILE" \
    --api-versions security.istio.io/v1beta1 \
    --api-versions cilium.io/v1alpha1 \
    --api-versions kyverno.io/v1 \
    > "$RENDERED"
  log "  rendered → $RENDERED ($(wc -l <"$RENDERED" | tr -d ' ') lines)"
  kubectl apply -f "$RENDERED" || warn "kubectl apply on rendered chart returned non-zero"
fi

# ── 7. Kyverno cluster policies ──────────────────────────────────────────
if [ "$TARGET" = "all" ] || [ "$TARGET" = "policies" ]; then
  section "Step 7: Kyverno cluster policies"
  POLICIES_FILE="$DEPLOY/k8s/kyverno/cluster-policies.yaml"
  if [ -f "$POLICIES_FILE" ]; then
    kubectl apply -f "$POLICIES_FILE" || warn "policies apply returned non-zero"
    log "  applied $(grep -c '^kind:' "$POLICIES_FILE") policies"
  else
    log "  no policy file at $POLICIES_FILE — skipping"
  fi
fi

# ── 8. Wait for platform health ─────────────────────────────────────────
if [ "$TARGET" = "all" ]; then
  section "Step 8: platform readiness"
  log "  waiting up to 5m for spm-api to be ready..."
  kubectl -n aispm rollout status deploy/spm-api --timeout=5m \
    || warn "spm-api didn't reach ready in time"
  log "  waiting up to 2m for kafka..."
  kubectl -n aispm rollout status statefulset/kafka --timeout=2m \
    || warn "kafka not ready"
fi

# ── 9. Done ─────────────────────────────────────────────────────────────
section "DONE"
INGRESS_HOST="$(yq -r '.ingress.host' "$VALUES_FILE" 2>/dev/null || echo aispm.local)"
cat <<EOF
Cluster bootstrap complete.

  UI:             http://${INGRESS_HOST}
  Agents page:    http://${INGRESS_HOST}/admin/inventory
  Integrations:   http://${INGRESS_HOST}/admin/integrations

Next:
  1. (one-time) Add to /etc/hosts:  127.0.0.1  ${INGRESS_HOST}
  2. Open the UI, upload an agent.py from Example agents/.
  3. Verify chat round-trip from the agent panel.

Re-run this script to upgrade. Idempotent. Data in PVCs persists.

Useful targeted runs:
  bash $0 chart     — re-render and apply AISPM only
  bash $0 policies  — re-apply Kyverno policies only
  bash $0 addons    — re-install cert-manager / ingress-nginx / kyverno
  SKIP_GVISOR=1 SKIP_RUNTIME_SECURITY=1 bash $0   — fast minimal install
EOF
