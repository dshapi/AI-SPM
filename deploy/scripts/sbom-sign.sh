#!/usr/bin/env bash
# deploy/scripts/sbom-sign.sh
# ─────────────────────────────────────────────────────────────────────────────
# Generate + sign SBOMs for every AISPM service image (local-mode).
#
# For each of the 23 images at $REGISTRY/<img>:$TAG:
#   1. Resolve tag → immutable digest (signing by tag is fragile)
#   2. Generate SPDX-JSON SBOM with syft (or reuse one from audit-deps.sh)
#   3. cosign sign image     (key-based, no Rekor, --allow-insecure-registry)
#   4. cosign attest SBOM    (--type spdxjson)
#   5. (optional) grype scan + cosign attest --type vuln
#   6. Self-verify: cosign verify + cosign verify-attestation must succeed
#
# This is the LOCAL flow for localhost:5001 dev iteration. It uses --key,
# --tlog-upload=false, --insecure-ignore-tlog. For public/CI signing of
# images on GHCR, see .github/workflows/sbom.yml (keyless via Sigstore).
#
# Pre-reqs:
#   - cosign key pair at deploy/cosign/cosign.{key,pub}
#       cd deploy/cosign && cosign generate-key-pair
#       echo 'deploy/cosign/cosign.key' >> .gitignore
#   - COSIGN_PASSWORD env var (script prompts once if unset)
#   - All 23 images pushed to $REGISTRY (run build-images.sh first)
#
# Usage:
#   bash deploy/scripts/sbom-sign.sh
#   bash deploy/scripts/sbom-sign.sh --image aispm-api          # one image
#   bash deploy/scripts/sbom-sign.sh --no-vuln                  # skip grype
#   bash deploy/scripts/sbom-sign.sh --verify-only              # don't sign, just verify
#   bash deploy/scripts/sbom-sign.sh --reuse-sboms deploy/audit-reports/latest/sboms
#
# Flags:
#   --registry <host:port>   Default: localhost:5001
#   --tag <tag>              Default: latest
#   --key <path>             Default: deploy/cosign/cosign.key
#   --pub <path>             Default: deploy/cosign/cosign.pub
#   --sbom-dir <path>        Default: deploy/sbom/
#   --reuse-sboms <path>     Reuse SBOMs from this dir (e.g. audit-reports/latest/sboms)
#   --image <name>           Process only this image
#   --no-vuln                Skip grype scan + vuln attestation
#   --verify-only            Don't sign — just verify existing signatures
#
# Exit codes:
#   0 — every processed image signed AND self-verified
#   1 — at least one image failed
#   2 — script error / required tool missing
# ─────────────────────────────────────────────────────────────────────────────

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# ── Defaults ─────────────────────────────────────────────────────────────────
REGISTRY="${REGISTRY:-localhost:5001}"
TAG="${TAG:-latest}"
COSIGN_KEY="${COSIGN_KEY:-$REPO_ROOT/deploy/cosign/cosign.key}"
COSIGN_PUB="${COSIGN_PUB:-$REPO_ROOT/deploy/cosign/cosign.pub}"
SBOM_DIR="${SBOM_DIR:-$REPO_ROOT/deploy/sbom}"
# Newer cosign deprecated --tlog-upload=false. Replacement is a signing config
# file with the rekorTlogUrls field stripped. Generate once with:
#   curl -s https://raw.githubusercontent.com/sigstore/root-signing/refs/heads/main/targets/signing_config.v0.2.json \
#     | jq 'del(.rekorTlogUrls)' > deploy/cosign/signing-config-no-tlog.json
SIGNING_CONFIG="${SIGNING_CONFIG:-$REPO_ROOT/deploy/cosign/signing-config-no-tlog.json}"
REUSE_SBOMS=""
NO_VULN=0
VERIFY_ONLY=0
ONE_IMAGE=""

# ── CLI parsing ──────────────────────────────────────────────────────────────
print_help() { sed -n '2,46p' "$0"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --registry)       REGISTRY="$2"; shift 2 ;;
    --registry=*)     REGISTRY="${1#*=}"; shift ;;
    --tag)            TAG="$2"; shift 2 ;;
    --tag=*)          TAG="${1#*=}"; shift ;;
    --key)            COSIGN_KEY="$2"; shift 2 ;;
    --pub)            COSIGN_PUB="$2"; shift 2 ;;
    --sbom-dir)       SBOM_DIR="$2"; shift 2 ;;
    --reuse-sboms)    REUSE_SBOMS="$2"; shift 2 ;;
    --image)          ONE_IMAGE="$2"; shift 2 ;;
    --no-vuln)        NO_VULN=1; shift ;;
    --verify-only)    VERIFY_ONLY=1; shift ;;
    -h|--help)        print_help; exit 0 ;;
    *)                echo "Unknown arg: $1" >&2; print_help; exit 2 ;;
  esac
done

# ── Image list (mirrors deploy/helm/aispm/values.yaml) ───────────────────────
IMAGES=(
  aispm-api               aispm-guard-model       aispm-garak-runner
  aispm-retrieval-gw      aispm-processor         aispm-policy-decider
  aispm-agent             aispm-memory            aispm-executor
  aispm-tool-parser       aispm-output-guard      aispm-freeze-ctrl
  aispm-policy-sim        aispm-spm-api           aispm-spm-mcp
  aispm-spm-llm-proxy     aispm-spm-aggregator    aispm-agent-orchestrator
  aispm-threat-hunter     aispm-ui                aispm-startup-orch
  aispm-flink-pyjob       aispm-agent-runtime
)

# Filter to one image if requested
if [[ -n "$ONE_IMAGE" ]]; then
  found=0
  for img in "${IMAGES[@]}"; do
    [[ "$img" == "$ONE_IMAGE" ]] && found=1
  done
  if [[ $found -eq 0 ]]; then
    echo "Unknown image: $ONE_IMAGE" >&2
    echo "Valid images: ${IMAGES[*]}" >&2
    exit 2
  fi
  IMAGES=("$ONE_IMAGE")
fi

# ── Logging ──────────────────────────────────────────────────────────────────
log()  { printf '\033[1;36m▶ %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m! %s\033[0m\n' "$*"; }
err()  { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; }
hr()   { printf '\033[1;34m%s\033[0m\n' "────────────────────────────────────────────────────────────────────"; }

have() { command -v "$1" >/dev/null 2>&1; }

# ── Tool checks ──────────────────────────────────────────────────────────────
have cosign || { err "cosign not found — brew install cosign"; exit 2; }
have docker || { err "docker not found"; exit 2; }
have jq     || { err "jq not found — brew install jq"; exit 2; }

if [[ $VERIFY_ONLY -eq 0 ]]; then
  if [[ -z "$REUSE_SBOMS" ]]; then
    have syft || { err "syft not found — brew install syft  (or use --reuse-sboms)"; exit 2; }
  fi
  if [[ $NO_VULN -eq 0 ]]; then
    have grype || { warn "grype not found — vuln attestation will be skipped"; NO_VULN=1; }
  fi
fi

# ── Insecure-registry flag (auto-detect for local/HTTP registries) ───────────
INSECURE_FLAG=""
if [[ "$REGISTRY" =~ ^(localhost|127\.0\.0\.1|0\.0\.0\.0|host\.docker\.internal): ]]; then
  INSECURE_FLAG="--allow-insecure-registry"
  log "registry is local/HTTP — using --allow-insecure-registry"
fi

# ── Key handling ─────────────────────────────────────────────────────────────
if [[ ! -f "$COSIGN_PUB" ]]; then
  err "Cosign public key not found: $COSIGN_PUB"
  err ""
  err "Generate a key pair (one time):"
  err "  mkdir -p deploy/cosign && cd deploy/cosign && cosign generate-key-pair"
  err "  echo 'deploy/cosign/cosign.key' >> ../../.gitignore"
  exit 2
fi

if [[ $VERIFY_ONLY -eq 0 ]]; then
  if [[ ! -f "$COSIGN_KEY" ]]; then
    err "Cosign private key not found: $COSIGN_KEY"
    err "Generate one with: cd deploy/cosign && cosign generate-key-pair"
    exit 2
  fi
  if [[ ! -f "$SIGNING_CONFIG" ]]; then
    err "Signing config (no-tlog) not found: $SIGNING_CONFIG"
    err ""
    err "Generate it once:"
    err "  curl -s https://raw.githubusercontent.com/sigstore/root-signing/refs/heads/main/targets/signing_config.v0.2.json \\"
    err "    | jq 'del(.rekorTlogUrls)' > $SIGNING_CONFIG"
    exit 2
  fi
  # Prompt once if password isn't set in env
  if [[ -z "${COSIGN_PASSWORD:-}" ]]; then
    read -s -r -p "Cosign key password: " COSIGN_PASSWORD
    echo
    export COSIGN_PASSWORD
  fi
fi

mkdir -p "$SBOM_DIR"

# ── Tally ────────────────────────────────────────────────────────────────────
SIGNED=()
FAILED=()
SKIPPED=()

# ── Helper: resolve tag → digest ─────────────────────────────────────────────
resolve_digest() {
  local ref="$1" digest=""
  digest="$(docker buildx imagetools inspect "$ref" \
              --format '{{json .Manifest.Digest}}' 2>/dev/null \
              | tr -d '"')" || true
  if [[ -z "$digest" || "$digest" == "null" ]]; then
    docker pull "$ref" >/dev/null 2>&1 || return 1
    digest="$(docker inspect --format '{{index .RepoDigests 0}}' "$ref" 2>/dev/null \
              | sed 's/.*@//')"
  fi
  [[ -n "$digest" && "$digest" != "null" ]] || return 1
  echo "$digest"
}

# ─── Per-image loop ──────────────────────────────────────────────────────────
for img in "${IMAGES[@]}"; do
  hr
  log "$img"

  ref_tag="${REGISTRY}/${img}:${TAG}"

  if ! digest="$(resolve_digest "$ref_tag")"; then
    warn "  not in registry — skipped"
    SKIPPED+=("$img")
    continue
  fi
  ref="${REGISTRY}/${img}@${digest}"
  log "  digest: ${digest:0:19}..."

  sbom="$SBOM_DIR/sbom-${img}.spdx.json"
  vuln="$SBOM_DIR/vuln-${img}.json"

  # ── Generate or reuse SBOM ─────────────────────────────────────────────────
  if [[ $VERIFY_ONLY -eq 0 ]]; then
    if [[ -n "$REUSE_SBOMS" && -f "$REUSE_SBOMS/sbom-${img}.spdx.json" ]]; then
      cp "$REUSE_SBOMS/sbom-${img}.spdx.json" "$sbom"
      log "  SBOM reused from $REUSE_SBOMS"
    else
      log "  generating SBOM (syft)..."
      if ! syft "$ref" -o spdx-json="$sbom" 2>/dev/null; then
        err "  syft failed"
        FAILED+=("$img")
        continue
      fi
    fi

    # ── Sign image ───────────────────────────────────────────────────────────
    log "  cosign sign..."
    if ! cosign sign \
            --key "$COSIGN_KEY" \
            $INSECURE_FLAG \
            --signing-config "$SIGNING_CONFIG" \
            --yes \
            "$ref" >/dev/null 2>&1; then
      err "  cosign sign failed"
      FAILED+=("$img")
      continue
    fi

    # ── Attest SBOM ──────────────────────────────────────────────────────────
    log "  cosign attest (sbom)..."
    if ! cosign attest \
            --key "$COSIGN_KEY" \
            --predicate "$sbom" \
            --type spdxjson \
            $INSECURE_FLAG \
            --signing-config "$SIGNING_CONFIG" \
            --yes \
            "$ref" >/dev/null 2>&1; then
      err "  cosign attest (sbom) failed"
      FAILED+=("$img")
      continue
    fi

    # ── Vuln scan + attest ───────────────────────────────────────────────────
    if [[ $NO_VULN -eq 0 ]]; then
      log "  grype scan..."
      if grype "sbom:$sbom" -o json > "$vuln" 2>/dev/null; then
        C=$(jq '[.matches[] | select(.vulnerability.severity == "Critical")] | length' "$vuln")
        H=$(jq '[.matches[] | select(.vulnerability.severity == "High")]     | length' "$vuln")
        log "    critical=$C  high=$H"
        log "  cosign attest (vuln)..."
        cosign attest \
          --key "$COSIGN_KEY" \
          --predicate "$vuln" \
          --type vuln \
          $INSECURE_FLAG \
          --signing-config "$SIGNING_CONFIG" \
          --yes \
          "$ref" >/dev/null 2>&1 \
          || warn "  vuln attest failed (continuing)"
      else
        warn "  grype scan failed — skipping vuln attestation"
      fi
    fi
  fi

  # ── Self-verify ────────────────────────────────────────────────────────────
  log "  self-verify (image signature)..."
  if ! cosign verify \
          --key "$COSIGN_PUB" \
          $INSECURE_FLAG \
          --insecure-ignore-tlog \
          "$ref" >/dev/null 2>&1; then
    err "  cosign verify failed"
    FAILED+=("$img")
    continue
  fi

  log "  self-verify (sbom attestation)..."
  if ! cosign verify-attestation \
          --key "$COSIGN_PUB" \
          --type spdxjson \
          $INSECURE_FLAG \
          --insecure-ignore-tlog \
          "$ref" >/dev/null 2>&1; then
    err "  cosign verify-attestation (sbom) failed"
    FAILED+=("$img")
    continue
  fi

  if [[ $VERIFY_ONLY -eq 1 ]]; then
    ok "  verified"
  else
    ok "  signed + attested + verified"
  fi
  SIGNED+=("$img")
done

# ── Summary ──────────────────────────────────────────────────────────────────
hr
log "Sign summary"
printf "  %s : %d\n" "$([[ $VERIFY_ONLY -eq 1 ]] && echo "verified" || echo "signed  ")" "${#SIGNED[@]}"
printf "  skipped  : %d\n" "${#SKIPPED[@]}"
printf "  failed   : %d\n" "${#FAILED[@]}"
echo

if [[ ${#SKIPPED[@]} -gt 0 ]]; then
  warn "Skipped (not in registry — push first via build-images.sh):"
  for s in "${SKIPPED[@]}"; do printf "    • %s\n" "$s"; done
  echo
fi

if [[ ${#FAILED[@]} -gt 0 ]]; then
  err "Failed images:"
  for f in "${FAILED[@]}"; do printf "    • %s\n" "$f"; done
  echo
  echo "Re-run a single image to debug:"
  echo "  bash deploy/scripts/sbom-sign.sh --image ${FAILED[0]}"
  echo
  exit 1
fi

if [[ ${#SIGNED[@]} -gt 0 ]]; then
  ok "All processed images signed and verified."
  echo
  echo "Verify any image yourself:"
  echo "  cosign verify --key $COSIGN_PUB \\"
  echo "    $INSECURE_FLAG --insecure-ignore-tlog \\"
  echo "    ${REGISTRY}/<image>:${TAG}"
  echo
  echo "Pull the SBOM:"
  echo "  cosign verify-attestation --key $COSIGN_PUB --type spdxjson \\"
  echo "    $INSECURE_FLAG --insecure-ignore-tlog \\"
  echo "    ${REGISTRY}/<image>:${TAG} \\"
  echo "    | jq -r '.payload | @base64d | fromjson | .predicate' > sbom.json"
fi

exit 0
