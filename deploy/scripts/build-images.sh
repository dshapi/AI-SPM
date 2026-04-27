#!/usr/bin/env bash
# deploy/scripts/build-images.sh
# Build all AISPM service images into k3s containerd via nerdctl.
# Run from ANYWHERE — the script always resolves the repo root itself.
#
# Usage:
#   bash deploy/scripts/build-images.sh          # build all
#   bash deploy/scripts/build-images.sh aispm-api # build one image by name

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NERDCTL="nerdctl --namespace k8s.io"
TARGET="${1:-}"   # optional: only build this image name
FAILED=()
BUILT=()
SIGNED=()
SIGN_FAILED=()

# Optional registry push + Cosign signing.
# Set both to enable the prod path:
#   IMAGE_REGISTRY=registry.example.com/aispm
#   COSIGN_KEY=$REPO_ROOT/deploy/cosign/aispm-images.key
#   COSIGN_PASSWORD=...   (export inline if the key has a password)
#
# Behavior:
#   - if IMAGE_REGISTRY unset → local-only build, no push, no sign (dev)
#   - if IMAGE_REGISTRY set + COSIGN_KEY unset → push, no sign (staging)
#   - if both set → push + sign (prod path required for verifyImages enforce)
IMAGE_REGISTRY="${IMAGE_REGISTRY:-}"
COSIGN_KEY="${COSIGN_KEY:-}"

log()  { echo "$(date +%H:%M:%S) [INFO]  $*"; }
err()  { echo "$(date +%H:%M:%S) [ERROR] $*" >&2; }

# build IMAGE DOCKERFILE_RELATIVE_TO_REPO [CONTEXT_RELATIVE_TO_REPO]
# Default context is the repo root (all Python services need this because
# their Dockerfiles reference paths like `COPY services/api/...`).
build() {
  local IMAGE="$1"
  local DOCKERFILE="$REPO_ROOT/$2"
  local CONTEXT="${3:-$REPO_ROOT}"          # default: repo root
  [[ "$CONTEXT" != /* ]] && CONTEXT="$REPO_ROOT/$CONTEXT"

  if [[ -n "$TARGET" && "$IMAGE" != "$TARGET" ]]; then
    return 0
  fi

  log "Building $IMAGE ..."
  if $NERDCTL build \
      --tag "$IMAGE" \
      --file "$DOCKERFILE" \
      "$CONTEXT" \
      2>&1; then
    BUILT+=("$IMAGE")
    log "  ✓ $IMAGE"
  else
    err "  ✗ $IMAGE FAILED"
    FAILED+=("$IMAGE")
    return 0
  fi

  # ── push + sign (prod path) ─────────────────────────────────────────────
  if [[ -n "$IMAGE_REGISTRY" ]]; then
    local REMOTE="$IMAGE_REGISTRY/$IMAGE"
    log "  pushing $IMAGE → $REMOTE"
    $NERDCTL tag "$IMAGE" "$REMOTE" || { err "tag failed for $REMOTE"; return 0; }
    if ! $NERDCTL push "$REMOTE"; then
      err "push failed for $REMOTE"
      return 0
    fi

    if [[ -n "$COSIGN_KEY" && -f "$COSIGN_KEY" ]]; then
      log "  signing $REMOTE with $COSIGN_KEY"
      if cosign sign --key "$COSIGN_KEY" --yes "$REMOTE"; then
        SIGNED+=("$REMOTE")
        log "  ✓ signed $REMOTE"
      else
        err "  ✗ sign failed for $REMOTE"
        SIGN_FAILED+=("$REMOTE")
      fi
    fi
  fi
}

cd "$REPO_ROOT"
log "=== AISPM image build  (repo: $REPO_ROOT) ==="

# ── Python services — context = repo root (Dockerfiles reference cross-service paths)
build aispm-api:latest                 services/api/Dockerfile
build aispm-retrieval-gw:latest        services/retrieval_gateway/Dockerfile
build aispm-processor:latest           services/processor/Dockerfile
build aispm-policy-decider:latest      services/policy_decider/Dockerfile
build aispm-agent:latest               services/agent/Dockerfile
build aispm-memory:latest              services/memory_service/Dockerfile
build aispm-executor:latest            services/executor/Dockerfile
build aispm-tool-parser:latest         services/tool_parser/Dockerfile
build aispm-output-guard:latest        services/output_guard/Dockerfile
build aispm-freeze-ctrl:latest         services/freeze_controller/Dockerfile
build aispm-policy-sim:latest          services/policy_simulator/Dockerfile
build aispm-guard-model:latest         services/guard_model/Dockerfile
build aispm-garak-runner:latest        services/garak/Dockerfile
build aispm-spm-api:latest             services/spm_api/Dockerfile
build aispm-spm-mcp:latest             services/spm_mcp/Dockerfile
build aispm-spm-llm-proxy:latest       services/spm_llm_proxy/Dockerfile
build aispm-spm-aggregator:latest      services/spm_aggregator/Dockerfile
build aispm-agent-orchestrator:latest  services/agent-orchestrator-service/Dockerfile
build aispm-threat-hunter:latest       services/threat-hunting-agent/Dockerfile
build aispm-startup-orch:latest        services/startup_orchestrator/Dockerfile
build aispm-flink-pyjob:latest         services/flink_pyjob/Dockerfile
build aispm-agent-runtime:latest       agent_runtime/Dockerfile

# ── UI — self-contained; context = ui/ subdirectory
build aispm-ui:latest                  ui/Dockerfile                    ui

# ── Summary
echo ""
log "=== Build summary ==="
log "Built  (${#BUILT[@]}): ${BUILT[*]:-none}"
if [[ -n "$IMAGE_REGISTRY" ]]; then
  log "Registry: $IMAGE_REGISTRY"
  if [[ -n "$COSIGN_KEY" ]]; then
    log "Signed (${#SIGNED[@]}): ${SIGNED[*]:-none}"
    if [[ ${#SIGN_FAILED[@]} -gt 0 ]]; then
      err "Sign failed (${#SIGN_FAILED[@]}):"
      for f in "${SIGN_FAILED[@]}"; do err "  - $f"; done
    fi
  else
    log "Signing: skipped (set COSIGN_KEY to enable)"
  fi
else
  log "Push/sign: skipped (set IMAGE_REGISTRY to enable)"
fi
if [[ ${#FAILED[@]} -gt 0 ]]; then
  err "Failed (${#FAILED[@]}):"
  for f in "${FAILED[@]}"; do err "  - $f"; done
  exit 1
else
  log "All images built successfully."
fi
