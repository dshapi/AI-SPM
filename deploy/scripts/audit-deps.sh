#!/usr/bin/env bash
# deploy/scripts/audit-deps.sh
# ─────────────────────────────────────────────────────────────────────────────
# Pre-SBOM dependency audit. Run this BEFORE generating signed SBOMs so the
# SBOM you sign represents a clean artifact.
#
# Four checks, each writes its raw output as JSON under deploy/audit-reports/
# and contributes to a final summary + exit code.
#
#   1. pip-audit       — Python deps in every services/<svc>/requirements.txt
#   2. npm audit       — UI deps in ui/
#   3. grype           — CVE scan on each image at $REGISTRY (default localhost:5001)
#   4. License scan    — flags GPL/AGPL via syft-generated SBOMs
#
# The license-scan step generates SBOMs as a side effect into
# $REPORT_DIR/sboms/, ready to be picked up by deploy/scripts/sbom-sign.sh
# (next on the list).
#
# Usage:
#   bash deploy/scripts/audit-deps.sh
#   bash deploy/scripts/audit-deps.sh --severity critical
#   bash deploy/scripts/audit-deps.sh --skip-images       # no docker available
#   REGISTRY=registry.example.com/aispm bash deploy/scripts/audit-deps.sh
#
# Flags:
#   --severity {low|medium|high|critical}   Gate level for exit code (default: high)
#   --skip-images                           Skip grype + SBOM steps
#   --skip-licenses                         Skip license scan
#   --registry <host:port>                  Override $REGISTRY
#   -h, --help                              This help text
#
# Exit codes:
#   0 — clean (no findings at or above the severity gate)
#   1 — findings at or above the severity gate
#   2 — script error / required tool missing
# ─────────────────────────────────────────────────────────────────────────────

# NOTE: not `set -e` — we want every check to run even if an earlier one
# returns non-zero. Each section tracks its own findings and we tally at the end.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT_DIR="$REPO_ROOT/deploy/audit-reports/$TIMESTAMP"
LATEST_LINK="$REPO_ROOT/deploy/audit-reports/latest"

# ── CLI parsing ──────────────────────────────────────────────────────────────
SEVERITY="${SEVERITY:-high}"
SKIP_IMAGES=0
SKIP_LICENSES=0
REGISTRY="${REGISTRY:-localhost:5001}"

print_help() { sed -n '2,40p' "$0"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --severity)       SEVERITY="$2"; shift 2 ;;
    --severity=*)     SEVERITY="${1#*=}"; shift ;;
    --skip-images)    SKIP_IMAGES=1; shift ;;
    --skip-licenses)  SKIP_LICENSES=1; shift ;;
    --registry)       REGISTRY="$2"; shift 2 ;;
    --registry=*)     REGISTRY="${1#*=}"; shift ;;
    -h|--help)        print_help; exit 0 ;;
    *)                echo "Unknown arg: $1" >&2; print_help; exit 2 ;;
  esac
done

case "$SEVERITY" in
  low|medium|high|critical) ;;
  *) echo "Invalid --severity: $SEVERITY (use low|medium|high|critical)" >&2; exit 2 ;;
esac

# Numeric rank for gate comparison
sev_rank() {
  case "$1" in
    Critical|critical) echo 4 ;;
    High|high)         echo 3 ;;
    Medium|medium)     echo 2 ;;
    Low|low)           echo 1 ;;
    *)                 echo 0 ;;
  esac
}
GATE=$(sev_rank "$SEVERITY")

# ── Image list (mirrors deploy/helm/aispm/values.yaml `images.*.repository`) ─
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

# ── Logging helpers ──────────────────────────────────────────────────────────
log()  { printf '\033[1;36m▶ %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m! %s\033[0m\n' "$*"; }
err()  { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; }
hr()   { printf '\033[1;34m%s\033[0m\n' "────────────────────────────────────────────────────────────────────"; }

mkdir -p "$REPORT_DIR"

# ── Tool availability (warn, don't fail — let user decide what to skip) ──────
have() { command -v "$1" >/dev/null 2>&1; }

PIP_AUDIT_OK=1
OSV_SCANNER_OK=1
NPM_OK=1
GRYPE_OK=1
SYFT_OK=1
JQ_OK=1
DOCKER_OK=1

have pip-audit    || { warn "pip-audit not found — install: pip install pip-audit"; PIP_AUDIT_OK=0; }
have osv-scanner  || { warn "osv-scanner not found — pip-audit fallback unavailable (brew install osv-scanner)"; OSV_SCANNER_OK=0; }
have npm          || { warn "npm not found — UI audit will be skipped"; NPM_OK=0; }
have grype        || { warn "grype not found — image audit will be skipped (brew install grype)"; GRYPE_OK=0; }
have syft         || { warn "syft not found — license scan will be skipped (brew install syft)"; SYFT_OK=0; }
have jq           || { err  "jq is required for the summary — install: brew install jq"; JQ_OK=0; }
have docker       || { warn "docker not found — image audit will be skipped"; DOCKER_OK=0; }

[[ $SKIP_IMAGES -eq 1 ]] && { GRYPE_OK=0; SYFT_OK=0; }
[[ $SKIP_LICENSES -eq 1 ]] && SYFT_OK=0
[[ $JQ_OK -eq 0 ]] && exit 2

# ── Tally counters ───────────────────────────────────────────────────────────
PY_FINDINGS=0
NPM_FINDINGS=0
IMG_FINDINGS=0
LICENSE_HITS=0
GATE_TRIPPED=0

# Bump tally if a severity meets the gate
bump() {
  local count="$1" sev="$2"
  [[ "$count" =~ ^[0-9]+$ ]] || count=0
  [[ "$count" -eq 0 ]] && return
  if [[ "$(sev_rank "$sev")" -ge "$GATE" ]]; then
    GATE_TRIPPED=$((GATE_TRIPPED + count))
  fi
}

# ─── 1. pip-audit (with osv-scanner fallback) ────────────────────────────────
#
# pip-audit creates a temp venv and dry-run-installs the requirements file to
# resolve the dep tree. That triggers source-distribution build hooks for
# packages like apache-beam, gevent, older tensorflow — which often fail on
# Python 3.12 with `ModuleNotFoundError: No module named 'pkg_resources'`
# because modern setuptools no longer ships pkg_resources by default.
#
# When pip-audit fails for that (or any other internal-pip) reason, we fall
# back to osv-scanner. osv-scanner is read-only — it parses the file
# statically and queries the OSV vuln DB without ever calling pip — so build
# hooks can't crash it. We lose --fix on that file (osv-scanner has no fix
# mode), but we keep CI/audit coverage.
hr
log "1/4  pip-audit  — Python dependencies"
mkdir -p "$REPORT_DIR/pip-audit" "$REPORT_DIR/osv-scanner"

if [[ $PIP_AUDIT_OK -eq 1 ]]; then
  while IFS= read -r req; do
    [[ -z "$req" ]] && continue
    rel="${req#$REPO_ROOT/}"
    safe="$(echo "$rel" | tr '/' '_')"
    out="$REPORT_DIR/pip-audit/${safe}.json"
    osv_out="$REPORT_DIR/osv-scanner/${safe}.json"

    log "  $rel"
    # pip-audit exit codes: 0 clean, 1 vulns found, 2+ internal error
    set +e
    pip-audit -r "$req" --format json --output "$out" >/dev/null 2>&1
    ec=$?
    set -e 2>/dev/null || true

    if [[ $ec -eq 0 ]]; then
      ok "    no findings (pip-audit)"
    elif [[ $ec -eq 1 && -s "$out" ]]; then
      n=$(jq '[.dependencies[]?.vulns[]?] | length' "$out" 2>/dev/null || echo 0)
      warn "    $n vulnerabilities (pip-audit, see $out)"
      PY_FINDINGS=$((PY_FINDINGS + n))
      # pip-audit doesn't expose CVSS; treat all findings as "high" for gating
      bump "$n" high
    else
      # pip-audit blew up (build hook, resolver, network, etc). Fall back.
      if [[ $OSV_SCANNER_OK -eq 1 ]]; then
        warn "    pip-audit failed (ec=$ec) — falling back to osv-scanner"
        set +e
        osv-scanner --lockfile="$req" --format=json --output="$osv_out" >/dev/null 2>&1
        osv_ec=$?
        set -e 2>/dev/null || true

        if [[ $osv_ec -eq 0 ]]; then
          ok "    no findings (osv-scanner)"
        elif [[ -s "$osv_out" ]]; then
          n=$(jq '[.results[]?.packages[]?.vulnerabilities[]?] | length' "$osv_out" 2>/dev/null || echo 0)
          warn "    $n vulnerabilities (osv-scanner, no auto-fix; see $osv_out)"
          PY_FINDINGS=$((PY_FINDINGS + n))
          bump "$n" high
        else
          err "    both pip-audit and osv-scanner failed for $rel"
        fi
      else
        err "    pip-audit failed (ec=$ec) and osv-scanner unavailable — install: brew install osv-scanner"
      fi
    fi
  done < <(find "$REPO_ROOT/services" "$REPO_ROOT/agent_runtime" \
              -type f -name 'requirements.txt' \
              -not -path '*/node_modules/*' \
              -not -path '*/.venv/*' \
              -not -path '*/venv/*' 2>/dev/null)
else
  warn "skipped (pip-audit unavailable)"
fi

# ─── 2. npm audit ─────────────────────────────────────────────────────────────
hr
log "2/4  npm audit — UI dependencies"

if [[ $NPM_OK -eq 1 && -d "$REPO_ROOT/ui" ]]; then
  out="$REPORT_DIR/npm-audit.json"
  ( cd "$REPO_ROOT/ui" && npm audit --json > "$out" 2>/dev/null ) || true

  if [[ -s "$out" ]]; then
    C=$(jq -r '.metadata.vulnerabilities.critical // 0' "$out")
    H=$(jq -r '.metadata.vulnerabilities.high     // 0' "$out")
    M=$(jq -r '.metadata.vulnerabilities.moderate // 0' "$out")
    L=$(jq -r '.metadata.vulnerabilities.low      // 0' "$out")
    echo "    critical=$C  high=$H  moderate=$M  low=$L"
    NPM_FINDINGS=$((C + H + M + L))
    bump "$C" critical
    bump "$H" high
    bump "$M" medium
    bump "$L" low
    [[ $NPM_FINDINGS -eq 0 ]] && ok "    no findings"
  else
    warn "    npm audit produced no output"
  fi
else
  warn "skipped (npm or ui/ unavailable)"
fi

# ─── 3. grype on container images ────────────────────────────────────────────
hr
log "3/4  grype     — container image scan ($REGISTRY)"
mkdir -p "$REPORT_DIR/grype"

if [[ $GRYPE_OK -eq 1 && $DOCKER_OK -eq 1 ]]; then
  for img in "${IMAGES[@]}"; do
    ref="${REGISTRY}/${img}:latest"
    out="$REPORT_DIR/grype/${img}.json"

    # Skip if image isn't actually in the registry yet (dev iteration)
    if ! docker manifest inspect "$ref" >/dev/null 2>&1 \
       && ! docker pull "$ref" >/dev/null 2>&1; then
      warn "  $img — not in registry, skipped"
      continue
    fi

    log "  $img"
    grype "$ref" -o json > "$out" 2>/dev/null || {
      warn "    grype scan failed"
      continue
    }

    C=$(jq '[.matches[] | select(.vulnerability.severity == "Critical")] | length' "$out")
    H=$(jq '[.matches[] | select(.vulnerability.severity == "High")]     | length' "$out")
    M=$(jq '[.matches[] | select(.vulnerability.severity == "Medium")]   | length' "$out")
    L=$(jq '[.matches[] | select(.vulnerability.severity == "Low")]      | length' "$out")
    printf "    critical=%-3s high=%-3s medium=%-3s low=%-3s\n" "$C" "$H" "$M" "$L"

    IMG_FINDINGS=$((IMG_FINDINGS + C + H + M + L))
    bump "$C" critical
    bump "$H" high
    bump "$M" medium
    bump "$L" low
  done
else
  warn "skipped (grype or docker unavailable, or --skip-images)"
fi

# ─── 4. License scan (via syft-generated SBOMs) ──────────────────────────────
hr
log "4/4  licenses  — GPL/AGPL flag check"
mkdir -p "$REPORT_DIR/sboms" "$REPORT_DIR/licenses"

if [[ $SYFT_OK -eq 1 && $DOCKER_OK -eq 1 ]]; then
  for img in "${IMAGES[@]}"; do
    ref="${REGISTRY}/${img}:latest"
    sbom="$REPORT_DIR/sboms/sbom-${img}.spdx.json"
    out="$REPORT_DIR/licenses/${img}.txt"

    # Skip if image not in registry
    if ! docker manifest inspect "$ref" >/dev/null 2>&1 \
       && ! docker pull "$ref" >/dev/null 2>&1; then
      continue
    fi

    log "  $img — generating SBOM"
    if ! syft "$ref" -o spdx-json="$sbom" 2>/dev/null; then
      warn "    syft failed"
      continue
    fi

    # Filter packages with GPL or AGPL anywhere in the license string
    jq -r '.packages[]?
           | select(.licenseConcluded // "" | test("GPL|AGPL"; "i"))
           | "\(.name)@\(.versionInfo // "?") — \(.licenseConcluded)"' \
      "$sbom" > "$out"

    n=$(wc -l < "$out" | tr -d ' ')
    if [[ "$n" -gt 0 ]]; then
      warn "    $n GPL/AGPL package(s) — see $out"
      LICENSE_HITS=$((LICENSE_HITS + n))
    fi
  done
else
  warn "skipped (syft, docker unavailable, or --skip-licenses)"
fi

# ─── Summary ─────────────────────────────────────────────────────────────────
hr
ln -sfn "$TIMESTAMP" "$LATEST_LINK"

echo
log "Audit summary"
printf "  python deps   : %d finding(s)\n" "$PY_FINDINGS"
printf "  npm deps      : %d finding(s)\n" "$NPM_FINDINGS"
printf "  image CVEs    : %d finding(s)\n" "$IMG_FINDINGS"
printf "  GPL/AGPL pkgs : %d match(es)\n"  "$LICENSE_HITS"
echo
log "Reports: $REPORT_DIR"
log "Symlink: $LATEST_LINK  →  $TIMESTAMP"
echo

if [[ $GATE_TRIPPED -gt 0 ]]; then
  err "$GATE_TRIPPED finding(s) at or above '$SEVERITY' severity — gate FAILED"
  echo
  echo "Next steps:"
  echo "  • Fix Python:  pip-audit -r <file> --fix"
  echo "  • Fix npm:     ( cd ui && npm audit fix )"
  echo "  • Fix images:  upgrade base image / re-pin Dockerfile FROM"
  echo "  • Re-run:      bash deploy/scripts/audit-deps.sh"
  exit 1
fi

ok "Clean — no findings at or above '$SEVERITY' severity"
echo "  Ready to sign SBOMs (deploy/scripts/sbom-sign.sh — coming next)"
exit 0
