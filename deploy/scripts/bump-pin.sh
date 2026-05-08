#!/usr/bin/env bash
# deploy/scripts/bump-pin.sh
# -----------------------------------------------------------------------------
# Generic pin-bumper for requirements.txt files across the repo.
#
# Use this when pip-audit --fix bumps package A to a version that conflicts
# with package B's existing pin. Bump B with this script, then re-run
# pip-audit and the resolution unblocks.
#
# Examples:
#   # Bump pytest-asyncio (currently 0.24.x) to >=0.26.0
#   bash deploy/scripts/bump-pin.sh pytest-asyncio '0\.(2[0-5])\.[0-9]+' 0.26.0
#
#   # Bump apache-flink from 1.18.x to 1.20.4
#   bash deploy/scripts/bump-pin.sh apache-flink '1\.18\.[0-9]+' 1.20.4
#
#   # Dry-run preview
#   bash deploy/scripts/bump-pin.sh --dry-run pytest-asyncio '0\.24\.[0-9]+' 0.26.0
#
# Args:
#   $1 PACKAGE      Package name as it appears in requirements.txt (extras
#                   like [crypto] are matched automatically)
#   $2 OLD_REGEX    Regex matching the old version (without `==`).
#                   Example: '0\.(2[0-5])\.[0-9]+' matches 0.20.x..0.25.x
#   $3 NEW_VERSION  Target version. Pin becomes >={NEW_VERSION}
#
# After it runs:
#   git diff -- 'services/*/requirements.txt' agent_runtime/requirements.txt
#   bash deploy/scripts/audit-deps.sh --skip-images
# -----------------------------------------------------------------------------

set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

DRY_RUN=0
ARGS=()
for arg in "$@"; do
  case "$arg" in
    --dry-run|-n) DRY_RUN=1 ;;
    --help|-h)    sed -n '2,30p' "$0"; exit 0 ;;
    *)            ARGS+=("$arg") ;;
  esac
done

if [[ ${#ARGS[@]} -lt 3 ]]; then
  echo "Usage: $0 [--dry-run] PACKAGE OLD_REGEX NEW_VERSION" >&2
  echo "       $0 --help" >&2
  exit 2
fi

PACKAGE="${ARGS[0]}"
OLD_REGEX="${ARGS[1]}"
NEW_VERSION="${ARGS[2]}"

log()  { printf '\033[1;36m> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m+ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m! %s\033[0m\n' "$*"; }

# Escape regex metacharacters in the package name so things like
# python-jose[cryptography] match literally.
ESC_PKG="$(printf '%s' "$PACKAGE" | sed 's/[][\\.^$*+?(){}|]/\\&/g')"

# Match the package with optional bracketed extras, e.g. requests, requests[security]
SEARCH_REGEX="^${ESC_PKG}(\[[^]]+\])?==${OLD_REGEX}"

# Portable replacement for `mapfile -t` (bash 4+). macOS ships bash 3.2.
FILES=()
while IFS= read -r line; do
  [[ -n "$line" ]] && FILES+=("$line")
done < <(grep -lE "$SEARCH_REGEX" \
            services/*/requirements.txt \
            agent_runtime/requirements.txt 2>/dev/null || true)

if [[ ${#FILES[@]} -eq 0 ]]; then
  ok "No files match ${SEARCH_REGEX} - nothing to do."
  exit 0
fi

log "Package : ${PACKAGE}"
log "Match   : ${OLD_REGEX}"
log "Target  : >= ${NEW_VERSION}"
log "Files   : ${#FILES[@]}"
[[ $DRY_RUN -eq 1 ]] && warn "DRY RUN - no files will be written"
echo

UPDATED=()
SKIPPED=()

# Replacement: keep any existing extras like [cryptography]
REPLACE_EXPR="s/^${ESC_PKG}(\[[^]]+\])?==${OLD_REGEX}/${PACKAGE}\1>=${NEW_VERSION}/"

for f in "${FILES[@]}"; do
  before="$(grep -E "^${ESC_PKG}(\[[^]]+\])?==" "$f" || true)"

  if [[ $DRY_RUN -eq 1 ]]; then
    after="$(echo "$before" | sed -E "$REPLACE_EXPR")"
    log "$f"
    diff <(echo "$before") <(echo "$after") | sed 's/^/    /'
    UPDATED+=("$f")
    continue
  fi

  if sed -i.bak -E "$REPLACE_EXPR" "$f"; then
    after="$(grep -E "^${ESC_PKG}(\[[^]]+\])?==" "$f" || true)"
    if [[ "$before" != "$after" ]]; then
      ok "$f"
      UPDATED+=("$f")
    else
      warn "$f (no change)"
      SKIPPED+=("$f")
    fi
  else
    warn "$f (sed failed)"
    SKIPPED+=("$f")
  fi
done

echo
log "Summary"
printf "  updated : %d\n" "${#UPDATED[@]}"
printf "  skipped : %d\n" "${#SKIPPED[@]}"
echo

if [[ $DRY_RUN -eq 0 && ${#UPDATED[@]} -gt 0 ]]; then
  cat <<EOF
Next steps:
  1. Review the diff:
       git diff -- 'services/*/requirements.txt' agent_runtime/requirements.txt
  2. Clean up sed backups:
       find services agent_runtime -name 'requirements.txt.bak' -delete
  3. Re-run audit:
       bash deploy/scripts/audit-deps.sh --skip-images
EOF
fi
