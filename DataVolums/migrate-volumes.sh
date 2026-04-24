#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# migrate-volumes.sh
#
# One-shot migration from the original named docker volumes into bind-mount
# directories under /Users/danyshapiro/PycharmProjects/AISPM/DataVolums/ so
# the persistent state lives under the repo (visible on the host filesystem
# and survives `docker compose down -v`).
#
# Source volume names follow Compose's auto-prefix convention. The default
# project name on this repo is "aispm" (lowercase of the directory name);
# override with `PROJECT=<name>` if your stack uses something different.
# Volumes that declare their own `name:` (e.g. keycloak-data) are looked up
# by the literal name with NO prefix.
#
# Run from anywhere — the absolute paths are baked in:
#
#   ./DataVolums/migrate-volumes.sh
#
# Then `docker compose up -d` and the services will mount the new bind paths.
#
# Re-running is a no-op for any target dir that's already non-empty (we
# refuse to overwrite). Pass --force to copy anyway.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO="/Users/danyshapiro/PycharmProjects/AISPM"
DST_BASE="${REPO}/DataVolums"

# Compose lowercases the project name. Override with PROJECT=... if needed.
PROJECT="${PROJECT:-aispm}"

# Format: "<source-volume>:<dest-subdir>:<prefix-mode>"
#   prefix-mode = "project"  → look up as "${PROJECT}_<source>"
#   prefix-mode = "literal"  → look up as "<source>" (volume declared with name:)
ENTRIES=(
  "redis-data:redis:project"
  "spm-db-data:spm-db:project"
  "grafana-data:grafana:project"
  "agent-orchestrator-data:agent-orchestrator:project"
  "keycloak-data:keycloak:literal"
)

FORCE=0
if [[ "${1:-}" == "--force" ]]; then FORCE=1; fi

echo "▶ Stopping containers that hold the old volumes (NOT removing volumes)…"
( cd "$REPO" && docker compose stop redis spm-db grafana agent-orchestrator 2>/dev/null ) || true
( cd "$REPO" && docker compose -f docker-compose.auth.yml stop keycloak 2>/dev/null ) || true

for entry in "${ENTRIES[@]}"; do
  IFS=':' read -r src_suffix dst_dir prefix_mode <<<"$entry"

  if [[ "$prefix_mode" == "project" ]]; then
    src_vol="${PROJECT}_${src_suffix}"
  else
    src_vol="${src_suffix}"
  fi
  dst_path="${DST_BASE}/${dst_dir}"

  echo
  echo "── ${src_vol}  →  ${dst_path}"

  mkdir -p "$dst_path"

  if ! docker volume inspect "$src_vol" >/dev/null 2>&1; then
    echo "   (skip — source volume ${src_vol} does not exist)"
    continue
  fi

  # `.gitkeep` is a tracking placeholder and shouldn't count as "data".
  existing="$(ls -A "$dst_path" 2>/dev/null | grep -v '^\.gitkeep$' || true)"
  if [[ -n "$existing" && "$FORCE" -ne 1 ]]; then
    echo "   (skip — destination already contains data; pass --force to overwrite)"
    continue
  fi

  echo "   copying…"
  docker run --rm \
    -v "${src_vol}:/from:ro" \
    -v "${dst_path}:/to" \
    alpine:3.19 \
    sh -c "cp -a /from/. /to/ && echo '   ✓ copied'"
done

echo
echo "▶ Migration complete. Bring services back up:"
echo "    cd ${REPO} && docker compose up -d"
echo
echo "Once the new mounts are confirmed healthy you can reclaim the old volumes:"
for entry in "${ENTRIES[@]}"; do
  IFS=':' read -r src_suffix _dst _mode <<<"$entry"
  if [[ "$_mode" == "project" ]]; then
    echo "    docker volume rm ${PROJECT}_${src_suffix}"
  else
    echo "    docker volume rm ${src_suffix}"
  fi
done
