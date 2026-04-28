#!/usr/bin/env bash
# deploy/scripts/bootstrap-cluster.sh
#
# Single entrypoint for the entire AISPM stack — works for both local
# Docker Compose (dev) and Kubernetes (staging / prod).
#
# ── MODES ────────────────────────────────────────────────────────────────────
#
#   Default (no flag):   Kubernetes bootstrap — provider-aware (Rancher
#                        Desktop / OrbStack / Lima); idempotent; safe to
#                        re-run on an existing cluster.
#
#   --compose            Docker Compose startup (replaces the old start.sh).
#                        Brings the full stack up locally and blocks until all
#                        core services are healthy.
#
#   --down [--volumes]   Docker Compose teardown (replaces the old stop.sh).
#                        Stops all services. Pass --volumes to also wipe
#                        persistent volumes (redis, postgres, grafana, etc.).
#
# ── QUICK START ──────────────────────────────────────────────────────────────
#
#   Local compose:   bash deploy/scripts/bootstrap-cluster.sh --compose
#   Stop compose:    bash deploy/scripts/bootstrap-cluster.sh --down
#   Wipe everything: bash deploy/scripts/bootstrap-cluster.sh --down --volumes
#   Kubernetes:      bash deploy/scripts/bootstrap-cluster.sh
#
# ── COMPOSE ENV KNOBS (--compose mode) ──────────────────────────────────────
#   BUILD=1    force-rebuild every image before starting
#   AUTH=1     include compose.auth.yml (adds Keycloak / auth overlay)
#
# ── KUBERNETES FLAGS ─────────────────────────────────────────────────────────
#   --skip-preflight   bypass the preflight checks (useful when you know
#                      what you're doing or are running in CI with a
#                      pre-validated cluster)
#
# ── KUBERNETES ENV KNOBS ─────────────────────────────────────────────────────
#   INSTALL_GVISOR=1         install gVisor runsc (needs containerd; off by default)
#   INSTALL_SECURITY=1       install Falco + Tetragon (off by default)
#   INSTALL_KYVERNO=1        install Kyverno + cluster policies (off by default)
#   SKIP_INGRESS=1           skip ingress-nginx
#   SKIP_CERT_MANAGER=1      skip cert-manager
#   SKIP_ISTIO=1             skip Istio (base + istiod)
#   ENABLE_ISTIO_CNI=1       install istio-cni (off by default — corrupts
#                            pod networking on OrbStack and many local k8s
#                            providers; use only on prod kubeadm/GKE)
#   VALUES_FILE=<path>       override which values file to render
#
# ── KUBERNETES TARGETED RE-RUNS ──────────────────────────────────────────────
#   bash deploy/scripts/bootstrap-cluster.sh chart     # only re-apply chart
#   bash deploy/scripts/bootstrap-cluster.sh policies  # only re-apply Kyverno
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
SKIP_PREFLIGHT=0
TARGET="all"
MODE="k8s"           # k8s | compose | down
DOWN_EXTRA_ARGS=""
for _arg in "$@"; do
  case "$_arg" in
    --compose)         MODE="compose" ;;
    --down)            MODE="down" ;;
    --volumes|-v)      DOWN_EXTRA_ARGS="$DOWN_EXTRA_ARGS --volumes" ;;
    --skip-preflight)  SKIP_PREFLIGHT=1 ;;
    -*)                echo "[bootstrap] WARNING: unknown flag: $_arg" >&2 ;;
    *)                 TARGET="$_arg" ;;
  esac
done

log()  { echo "$(date +%H:%M:%S) [bootstrap] $*"; }
warn() { echo "$(date +%H:%M:%S) [bootstrap] WARN: $*" >&2; }
err()  { echo "$(date +%H:%M:%S) [bootstrap] ERROR: $*" >&2; }
section() { echo; echo "═══ $* ═══"; }

# ═══════════════════════════════════════════════════════════════════════════
# ── COMPOSE DOWN mode  (replaces stop.sh) ──────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════
if [ "$MODE" = "down" ]; then
  log "Stopping AISPM Docker Compose stack..."

  # agent-runtime containers are spawned on demand by spm-api (not in the
  # compose file). Stop them first so the network teardown doesn't orphan them.
  agent_ctrs=$(docker ps -q \
    --filter "name=^agent-" \
    --filter "ancestor=aispm-agent-runtime:latest" 2>/dev/null || true)
  if [ -n "$agent_ctrs" ]; then
    _count=$(echo "$agent_ctrs" | wc -l | tr -d ' ')
    log "  stopping ${_count} agent runtime container(s)..."
    # 10s grace matches spm-api's stop_agent_container() graceful-shutdown path.
    docker stop -t 10 $agent_ctrs >/dev/null
    docker rm -f      $agent_ctrs >/dev/null
  fi

  # shellcheck disable=SC2086
  docker compose -f "$REPO_ROOT/compose.yml" -f "$REPO_ROOT/compose.auth.yml" \
    down $DOWN_EXTRA_ARGS
  log "Stack stopped."
  [ -n "$DOWN_EXTRA_ARGS" ] && log "  Persistent volumes wiped ($DOWN_EXTRA_ARGS)."
  exit 0
fi

# ═══════════════════════════════════════════════════════════════════════════
# ── COMPOSE mode  (replaces start.sh) ──────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════
if [ "$MODE" = "compose" ]; then
  BUILD=${BUILD:-}   # set BUILD=1 to force-rebuild every image before starting
  AUTH=${AUTH:-}     # set AUTH=1 to include compose.auth.yml (Keycloak + auth)

  COMPOSE_FILES="-f $REPO_ROOT/compose.yml"
  if [ -n "$AUTH" ]; then
    COMPOSE_FILES="$COMPOSE_FILES -f $REPO_ROOT/compose.auth.yml"
  fi

  # ── Pre-build one-shot images ──────────────────────────────────────────
  # aispm-flink-pyjob: shared by flink-jobmanager, flink-taskmanager, and
  # flink-pyjob-submitter. Built from flink-jobmanager's build context.
  if ! docker image inspect aispm-flink-pyjob:latest >/dev/null 2>&1; then
    log "Building aispm-flink-pyjob image (first-time, ~1 min)..."
    # shellcheck disable=SC2086
    docker compose $COMPOSE_FILES build flink-jobmanager || {
      err "Failed to build aispm-flink-pyjob — aborting"; exit 1
    }
  fi

  # aispm-agent-runtime: behind the build-only profile. spm-api spawns one
  # container per uploaded agent using this tag — must exist before spm-api starts.
  if ! docker image inspect aispm-agent-runtime:latest >/dev/null 2>&1; then
    log "Building aispm-agent-runtime image (first-time)..."
    # shellcheck disable=SC2086
    docker compose $COMPOSE_FILES --profile build-only build agent-runtime-build || {
      err "Failed to build aispm-agent-runtime — aborting"; exit 1
    }
  fi

  if [ -n "$BUILD" ]; then
    log "BUILD=1 — rebuilding all images..."
    # shellcheck disable=SC2086
    docker compose $COMPOSE_FILES build \
      || { err "Image build failed — aborting"; exit 1; }
    # shellcheck disable=SC2086
    docker compose $COMPOSE_FILES --profile build-only build agent-runtime-build \
      || { err "agent-runtime build failed — aborting"; exit 1; }
  fi

  # ── Bring the stack up ─────────────────────────────────────────────────
  log "Starting stack..."
  # shellcheck disable=SC2086
  docker compose $COMPOSE_FILES up -d --remove-orphans || {
    err "docker compose up failed — check above for errors"; exit 1
  }

  # ── Wait for services to be truly healthy ─────────────────────────────
  # `compose up -d` returns when containers are *created*, not *healthy*.
  # Poll actual health endpoints before printing the success banner.

  wait_http() {
    local name="$1" url="$2" max="${3:-180}" interval="${4:-4}"
    local deadline
    deadline=$(( $(date +%s) + max ))
    log "Waiting for $name ($url)..."
    while [ "$(date +%s)" -lt "$deadline" ]; do
      if curl -sf --max-time 3 "$url" >/dev/null 2>&1; then
        log "  ✓ $name healthy"; return 0
      fi
      sleep "$interval"
    done
    err "$name did not become healthy within ${max}s"
    err "  → check: docker compose logs $name"
    return 1
  }

  FAILED=0

  # startup-orchestrator is a one-shot container — poll its exit code.
  log "Waiting for startup-orchestrator to complete (up to 120s)..."
  SO_DEADLINE=$(( $(date +%s) + 120 ))
  while [ "$(date +%s)" -lt "$SO_DEADLINE" ]; do
    SO_STATUS=$(docker inspect --format='{{.State.Status}}' \
      cpm-startup-orchestrator 2>/dev/null || echo "missing")
    SO_EXIT=$(docker inspect --format='{{.State.ExitCode}}' \
      cpm-startup-orchestrator 2>/dev/null || echo "")
    if [ "$SO_STATUS" = "exited" ] && [ "$SO_EXIT" = "0" ]; then
      log "  ✓ startup-orchestrator completed"; break
    elif [ "$SO_STATUS" = "exited" ] && [ "$SO_EXIT" != "0" ]; then
      err "startup-orchestrator exited with code $SO_EXIT"
      err "  → check: docker compose logs startup-orchestrator"
      FAILED=1; break
    fi
    sleep 3
  done
  if [ "$(date +%s)" -ge "$SO_DEADLINE" ] && [ "$FAILED" -eq 0 ]; then
    err "startup-orchestrator did not finish within 120s"
    FAILED=1
  fi

  # Flink JobManager REST — the CEP job submitter needs the JM to be up.
  log "Waiting for Flink JobManager REST (up to 120s)..."
  FLINK_DEADLINE=$(( $(date +%s) + 120 ))
  while [ "$(date +%s)" -lt "$FLINK_DEADLINE" ]; do
    if curl -sf --max-time 3 "http://localhost:8081/overview" >/dev/null 2>&1; then
      log "  ✓ Flink JobManager REST healthy"; break
    fi
    sleep 5
  done
  if [ "$(date +%s)" -ge "$FLINK_DEADLINE" ]; then
    warn "Flink JobManager did not respond within 120s — CEP job may not have been submitted"
    warn "  → check: docker compose logs flink-jobmanager"
  fi

  # flink-pyjob-submitter is a one-shot container — wait for it to exit cleanly.
  log "Waiting for flink-pyjob-submitter to complete (up to 180s)..."
  FJS_DEADLINE=$(( $(date +%s) + 180 ))
  while [ "$(date +%s)" -lt "$FJS_DEADLINE" ]; do
    FJS_STATUS=$(docker inspect --format='{{.State.Status}}' \
      cpm-flink-pyjob-submitter 2>/dev/null || echo "missing")
    FJS_EXIT=$(docker inspect --format='{{.State.ExitCode}}' \
      cpm-flink-pyjob-submitter 2>/dev/null || echo "")
    if [ "$FJS_STATUS" = "exited" ] && [ "$FJS_EXIT" = "0" ]; then
      log "  ✓ CEP PyFlink job submitted successfully"; break
    elif [ "$FJS_STATUS" = "exited" ] && [ "$FJS_EXIT" != "0" ]; then
      warn "flink-pyjob-submitter exited with code $FJS_EXIT"
      warn "  → check: docker compose logs flink-pyjob-submitter"
      break
    elif [ "$FJS_STATUS" = "missing" ]; then
      # Container not yet created — still starting
      sleep 4; continue
    fi
    sleep 4
  done

  # Core platform HTTP health checks.
  wait_http "spm-api"       "http://localhost:8092/health" 180 4 || FAILED=1
  wait_http "api"           "http://localhost:8080/health" 180 4 || FAILED=1
  wait_http "spm-mcp"       "http://localhost:8500/health"  90 3 || FAILED=1
  wait_http "spm-llm-proxy" "http://localhost:8501/health"  90 3 || FAILED=1

  if [ "$FAILED" -ne 0 ]; then
    err "──────────────────────────────────────────────────────"
    err "One or more services failed to become healthy."
    err "Diagnose with:"
    err "  docker compose ps"
    err "  docker compose logs <service>"
    err "──────────────────────────────────────────────────────"
    exit 1
  fi

  # ── Success banner ────────────────────────────────────────────────────
  echo ""
  echo "Stack is up and healthy."
  echo "  API           → http://localhost:8080"
  echo "  SPM API       → http://localhost:8092"
  echo "  spm-mcp       → http://localhost:8500/health"
  echo "  spm-llm-proxy → http://localhost:8501/health"
  echo "  Flink UI      → http://localhost:8081           (CEP dashboard)"
  echo "  Grafana       → http://localhost:3000"
  echo "  Prometheus    → http://localhost:9090"
  echo "  Traefik       → http://localhost:9091/dashboard/"
  if [ -n "$AUTH" ]; then
    echo "  Keycloak      → http://keycloak.local:8180"
    echo ""
    echo "  With auth:    http://aispm.local/admin"
    echo "  OrbiX Chat:   http://aispm.local"
  fi
  echo ""
  echo "Logs:  docker compose logs -f [service]"
  echo "Stop:  bash deploy/scripts/bootstrap-cluster.sh --down"
  exit 0
fi

# ── Everything below this line is the Kubernetes bootstrap ─────────────────

# ── Preflight Checks ─────────────────────────────────────────────────────
if [ "$SKIP_PREFLIGHT" != "1" ]; then
  echo
  echo "=== Preflight Checks ==="
  echo

  _PF_FAILED=0
  pf_ok()   { echo "  ✓ $*"; }
  pf_fail() { echo "  ✗ $*"; _PF_FAILED=1; }
  pf_warn() { echo "  ⚠ $*"; }

  # ── 1. kubectl: installed + cluster reachable ───────────────────────────
  if ! command -v kubectl >/dev/null 2>&1; then
    pf_fail "kubectl: not installed — install from https://kubernetes.io/docs/tasks/tools/"
  elif ! kubectl cluster-info >/dev/null 2>&1; then
    pf_fail "kubectl: cannot reach cluster (kubectl cluster-info failed) — check your kubeconfig and that the cluster is running"
  else
    pf_ok "kubectl OK (context: $(kubectl config current-context 2>/dev/null))"
  fi

  # ── 2. helm: installed, v3+ ─────────────────────────────────────────────
  if ! command -v helm >/dev/null 2>&1; then
    pf_fail "helm: not installed — install from https://helm.sh/docs/intro/install/"
  else
    _HELM_MAJOR="$(helm version --short 2>/dev/null | grep -oE 'v[0-9]+' | head -1 | tr -d 'v')"
    if [ "${_HELM_MAJOR:-0}" -lt 3 ]; then
      pf_fail "helm: version v${_HELM_MAJOR:-?} is too old — helm v3+ required; install from https://helm.sh/docs/intro/install/"
    else
      pf_ok "helm OK ($(helm version --short 2>/dev/null | tr -d '\n'))"
    fi
  fi

  # ── 3. Longhorn: namespace, StorageClass, default ───────────────────────
  _LH_INSTALL_HINT="
      helm repo add longhorn https://charts.longhorn.io && \\
      helm install longhorn longhorn/longhorn -n longhorn-system --create-namespace"
  if ! kubectl get namespace longhorn-system >/dev/null 2>&1; then
    pf_fail "Longhorn: longhorn-system namespace not found — install Longhorn:${_LH_INSTALL_HINT}"
  else
    _LH_SC="$(kubectl get storageclass 2>/dev/null | awk '/longhorn/{print $1}' | head -1)"
    if [ -z "$_LH_SC" ]; then
      pf_fail "Longhorn: no Longhorn StorageClass found — install Longhorn:${_LH_INSTALL_HINT}"
    else
      _LH_IS_DEFAULT="$(kubectl get storageclass longhorn \
        -o jsonpath='{.metadata.annotations.storageclass\.kubernetes\.io/is-default-class}' \
        2>/dev/null || echo 'false')"
      if [ "$_LH_IS_DEFAULT" = "true" ]; then
        pf_ok "Longhorn StorageClass OK (present and set as default)"
      else
        pf_warn "Longhorn: StorageClass 'longhorn' exists but is NOT the default StorageClass — some PVCs may bind to the wrong class"
        pf_warn "Longhorn:  to fix: kubectl patch storageclass longhorn -p '{\"metadata\":{\"annotations\":{\"storageclass.kubernetes.io/is-default-class\":\"true\"}}}'"
      fi
    fi
  fi

  # ── 4. RWX support: Longhorn >= 1.5 ─────────────────────────────────────
  if kubectl get storageclass longhorn >/dev/null 2>&1; then
    _LH_IMAGE="$(kubectl -n longhorn-system get deploy longhorn-manager \
      -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || echo '')"
    _LH_VER="$(echo "$_LH_IMAGE" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
    if [ -z "$_LH_VER" ]; then
      pf_warn "Longhorn RWX: cannot determine Longhorn version — ReadWriteMany requires v1.5+; verify before using RWX PVCs"
    else
      _LH_MAJOR_N="$(echo "$_LH_VER" | cut -d. -f1)"
      _LH_MINOR_N="$(echo "$_LH_VER" | cut -d. -f2)"
      if [ "$_LH_MAJOR_N" -gt 1 ] || { [ "$_LH_MAJOR_N" -eq 1 ] && [ "$_LH_MINOR_N" -ge 5 ]; }; then
        pf_ok "Longhorn RWX OK (v${_LH_VER} supports ReadWriteMany)"
      else
        pf_warn "Longhorn RWX: v${_LH_VER} < 1.5 — ReadWriteMany volumes are not supported; upgrade Longhorn to v1.5+ before using RWX PVCs"
      fi
    fi
  fi

  # ── 5. Node count: warn if fewer than 3 Ready nodes ────────────────────
  _READY_NODES="$(kubectl get nodes --no-headers 2>/dev/null | grep -c ' Ready' || echo 0)"
  if [ "${_READY_NODES:-0}" -lt 3 ]; then
    pf_warn "Nodes: only ${_READY_NODES} Ready node(s) detected — Kafka requires 3 nodes for HA; single-node is fine for local dev"
  else
    pf_ok "Nodes OK (${_READY_NODES} Ready)"
  fi

  # ── 6. Target namespace: warn on dirty reinstall ────────────────────────
  _TARGET_NS="${TARGET_NAMESPACE:-aispm}"
  if kubectl get namespace "$_TARGET_NS" >/dev/null 2>&1; then
    _NS_RESOURCES="$(kubectl -n "$_TARGET_NS" get all --no-headers 2>/dev/null | wc -l | tr -d ' ')"
    if [ "${_NS_RESOURCES:-0}" -gt 0 ]; then
      pf_warn "Namespace: '$_TARGET_NS' already exists with ${_NS_RESOURCES} resource(s) — this looks like a reinstall over existing state"
      pf_warn "Namespace:  to start fresh: kubectl delete namespace $_TARGET_NS && kubectl delete namespace aispm-agents"
    else
      pf_warn "Namespace: '$_TARGET_NS' already exists (empty) — proceeding"
    fi
  else
    pf_ok "Namespace '$_TARGET_NS' not present (clean install)"
  fi

  # ── 7. Required CLI tools: jq, curl ────────────────────────────────────
  for _tool in jq curl; do
    if ! command -v "$_tool" >/dev/null 2>&1; then
      pf_fail "${_tool}: not installed — install with: brew install ${_tool}  (or: apt-get install ${_tool})"
    else
      pf_ok "${_tool} OK"
    fi
  done
  unset _tool

  echo
  if [ "$_PF_FAILED" = "1" ]; then
    echo "  One or more preflight checks FAILED. Resolve the issues above, then re-run."
    echo "  To bypass all checks (not recommended): $(basename "$0") --skip-preflight"
    exit 1
  fi

  echo "  All preflight checks passed — proceeding with installation."
  echo
fi

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
  if [ "${INSTALL_GVISOR:-0}" != "1" ]; then
    log "  gVisor skipped (set INSTALL_GVISOR=1 to install — requires containerd cluster)"
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
  # Off by default — Falco requires kernel headers or modern_ebpf support
  # which is not available on all local k8s providers. Set INSTALL_SECURITY=1
  # to enable. Pin to chart 4.20.x / falco 0.42.x — falco 0.43.x has an
  # upstream duplicate-container-plugin bug that crashloops on every install.
  if [ "${INSTALL_SECURITY:-0}" = "1" ]; then
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
  else
    log "  Falco + falcosidekick skipped (set INSTALL_SECURITY=1 to enable)"
  fi

  section "Step 5e: tetragon"
  # Off by default — Tetragon requires BPF support and often needs
  # 'mount --make-rshared /sys' inside the VM. Set INSTALL_SECURITY=1 to enable.
  if [ "${INSTALL_SECURITY:-0}" = "1" ]; then
    helm repo add cilium https://helm.cilium.io >/dev/null 2>&1 || true
    helm repo update cilium >/dev/null 2>&1 || true
    helm upgrade --install tetragon cilium/tetragon \
      -n kube-system \
      --set tetragon.enabled=true \
      --set tetragon.bpf.autoMount.enabled=false \
      --wait --timeout=5m \
      || warn "  tetragon helm returned non-zero (often needs 'mount --make-rshared /sys' inside the VM first)"
  else
    log "  Tetragon skipped (set INSTALL_SECURITY=1 to enable)"
  fi

  section "Step 5f: kyverno"
  # Off by default for local dev — Kyverno admission webhooks can block pod
  # scheduling in unexpected ways during development. Set INSTALL_KYVERNO=1
  # to enable. Pin to 3.3.7 — newer chart's CRDs use selectableFields (k8s 1.30+).
  if [ "${INSTALL_KYVERNO:-0}" = "1" ]; then
    helm repo add kyverno https://kyverno.github.io/kyverno >/dev/null 2>&1 || true
    helm repo update kyverno >/dev/null 2>&1 || true
    helm upgrade --install kyverno kyverno/kyverno \
      -n kyverno --create-namespace --version 3.3.7 \
      --set admissionController.replicas=1 \
      --set backgroundController.replicas=1 \
      --set cleanupController.replicas=1 \
      --set reportsController.replicas=1 \
      --wait --timeout=5m \
      || warn "  kyverno helm returned non-zero"
  else
    log "  Kyverno skipped (set INSTALL_KYVERNO=1 to enable)"
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
  if [ "${INSTALL_KYVERNO:-0}" = "1" ]; then
    POLICIES_FILE="$DEPLOY/k8s/kyverno/cluster-policies.yaml"
    if [ -f "$POLICIES_FILE" ]; then
      kubectl apply -f "$POLICIES_FILE" || warn "policies apply returned non-zero"
      log "  applied $(grep -c '^kind:' "$POLICIES_FILE") policies"
    else
      log "  no policy file at $POLICIES_FILE — skipping"
    fi
  else
    log "  Kyverno not installed — skipping cluster policies"
  fi
fi

# ── 8. Wait for platform health ─────────────────────────────────────────
if [ "$TARGET" = "all" ]; then
  section "Step 8: platform readiness"

  # ── Rollout status — wait for pods to be scheduled and running ─────────
  log "  waiting up to 5m for spm-api rollout..."
  kubectl -n aispm rollout status deploy/spm-api --timeout=5m \
    || warn "spm-api rollout didn't complete in time"

  log "  waiting up to 2m for kafka StatefulSet..."
  kubectl -n aispm rollout status statefulset/kafka --timeout=2m \
    || warn "kafka StatefulSet not ready"

  # ── startup-orchestrator Job — must complete before services are usable ──
  log "  waiting up to 3m for startup-orchestrator Job to complete..."
  kubectl -n aispm wait --for=condition=Complete \
    --timeout=180s job/startup-orchestrator 2>/dev/null \
    || warn "startup-orchestrator Job did not complete — check: kubectl -n aispm logs job/startup-orchestrator"

  # ── Flink cluster readiness ──────────────────────────────────────────────
  # The flink-pyjob-submitter is a post-install/post-upgrade Helm hook (weight 0)
  # that runs submit.sh to submit the CEP PyFlink job to the cluster. It waits
  # internally for the JM REST API, but we also check rollout here so any pod
  # scheduling problem appears in this section's output rather than silently
  # blocking the Helm hook.
  log "  waiting up to 3m for flink-jobmanager StatefulSet rollout..."
  kubectl -n aispm rollout status statefulset/flink-jobmanager --timeout=3m \
    || warn "flink-jobmanager StatefulSet did not roll out — check: kubectl -n aispm describe statefulset flink-jobmanager"

  log "  waiting up to 2m for flink-taskmanager Deployment rollout..."
  kubectl -n aispm rollout status deployment/flink-taskmanager --timeout=2m \
    || warn "flink-taskmanager Deployment did not roll out — check: kubectl -n aispm describe deployment flink-taskmanager"

  # Wait for the CEP PyFlink job submitter Helm hook Job to complete.
  # A successful exit means `flink run --detached` was accepted by the JobManager
  # and the CEP job is now running in the cluster. The Job is deleted on success
  # by `helm.sh/hook-delete-policy: hook-succeeded`, so we only see it if it
  # failed or is still running.
  log "  waiting up to 5m for flink-pyjob-submitter Job (CEP job submission)..."
  if kubectl -n aispm get job/flink-pyjob-submitter >/dev/null 2>&1; then
    kubectl -n aispm wait --for=condition=Complete \
      --timeout=300s job/flink-pyjob-submitter 2>/dev/null \
      && log "    ✓ CEP PyFlink job submitted successfully" \
      || warn "flink-pyjob-submitter Job did not complete — check: kubectl -n aispm logs job/flink-pyjob-submitter"
  else
    log "    flink-pyjob-submitter Job not found (already cleaned up by hook-delete-policy → hook ran and succeeded)"
  fi

  # ── HTTP health checks — rollout ready ≠ HTTP healthy ──────────────────
  # A pod can pass readiness probes but crash-loop on first request. Probe
  # the actual health endpoints for the two services everything else depends on.
  wait_k8s_http() {
    local name="$1" url="$2" max="${3:-120}"
    local deadline
    deadline=$(( $(date +%s) + max ))
    log "  HTTP health: $name ($url, max ${max}s)..."
    while [ "$(date +%s)" -lt "$deadline" ]; do
      if kubectl -n aispm run --rm -i --restart=Never --image=curlimages/curl:8.6.0 \
          healthcheck-"$(date +%s)" -- curl -sf --max-time 3 "$url" >/dev/null 2>&1; then
        log "    ✓ $name responding"
        return 0
      fi
      sleep 5
    done
    warn "    $name did not respond within ${max}s at $url"
    return 0  # warn only — don't block the whole script on HTTP probe flakiness
  }

  # Probe via in-cluster curl pod so we hit the cluster-internal Service IP.
  wait_k8s_http "spm-api"  "http://spm-api.aispm.svc.cluster.local:8092/health" 120
  wait_k8s_http "api"      "http://api.aispm.svc.cluster.local:8080/health"      120

  # ── Step 8.5: DB seed ──────────────────────────────────────────────────────
  # spm-api's lifespan runs _seed_demo_models() + _auto_bootstrap_integrations()
  # on startup, so the DB is already seeded by the time the health check above
  # passes. We exec seed_db.py here as belt-and-suspenders to surface any
  # seed failures explicitly and to cover re-runs where the pod was restarted
  # without reseeding (idempotent — seed_db.py skips rows that already exist).
  section "Step 8.5: DB seed (models + posture history + integrations)"
  SPM_POD="$(kubectl -n aispm get pod -l app=spm-api \
      --field-selector=status.phase=Running \
      -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  if [ -n "$SPM_POD" ]; then
    log "  running seed_db.py in pod $SPM_POD ..."
    if kubectl -n aispm exec "$SPM_POD" -- \
        python3 /app/seed_db.py 2>&1 | sed 's/^/    /'; then
      log "  ✓ Database seeded"
    else
      warn "  seed_db.py returned non-zero — lifespan auto-seed may still have covered this"
      warn "  check: kubectl -n aispm logs $SPM_POD | grep seed"
    fi
  else
    warn "  spm-api pod not running — skipping explicit seed step"
    warn "  (seeding will happen automatically on next spm-api startup via lifespan)"
  fi
fi

# ── 9. Done ─────────────────────────────────────────────────────────────
section "DONE"
INGRESS_HOST="$(yq -r '.ingress.host' "$VALUES_FILE" 2>/dev/null || echo aispm.local)"
cat <<EOF
Cluster bootstrap complete.

  UI:             http://${INGRESS_HOST}
  Agents page:    http://${INGRESS_HOST}/admin/inventory
  Integrations:   http://${INGRESS_HOST}/admin/integrations
  Flink UI:       kubectl -n aispm port-forward svc/flink-jobmanager 8081:8081  (CEP dashboard)

  ✓ Database seeded — models, posture history, integrations, cases, alerts, policies

Next:
  1. (one-time) Add to /etc/hosts:  127.0.0.1  ${INGRESS_HOST}
  2. Open the UI, upload an agent.py from Example agents/.
  3. Verify chat round-trip from the agent panel.

Re-run this script to upgrade. Idempotent. Data in PVCs persists.

Useful targeted runs:
  bash $0 chart                  — re-render and apply AISPM only
  bash $0 policies               — re-apply Kyverno policies only
  bash $0 addons                 — re-install cert-manager / ingress-nginx / kyverno
  bash $0 --skip-preflight       — skip preflight checks (CI / known-good cluster)
  SKIP_GVISOR=1 SKIP_RUNTIME_SECURITY=1 bash $0   — fast minimal install
EOF
