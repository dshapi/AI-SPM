#!/usr/bin/env bash
# start.sh — bring up the full AISPM stack.
#
# Just run:  ./start.sh
#
# Optional env knobs:
#   BUILD=1    force-rebuild every image before starting
#   AUTH=1     include compose.auth.yml (adds Keycloak / auth overlay)
set -euo pipefail

BUILD=${BUILD:-}  # set BUILD=1 to force-rebuild every image before starting
AUTH=${AUTH:-}    # set AUTH=1 to include compose.auth.yml (Keycloak + auth)

# ── Compose file list — auth overlay is opt-in ───────────────────────────────
COMPOSE_FILES="-f compose.yml"
if [ -n "$AUTH" ]; then
  COMPOSE_FILES="$COMPOSE_FILES -f compose.auth.yml"
fi

log() { echo "$(date +%H:%M:%S) [start] $*"; }
err() { echo "$(date +%H:%M:%S) [start] ERROR: $*" >&2; }

# ── Pre-build images that won't be auto-built by `compose up` ────────────────

# The aispm-flink-pyjob image is built once by flink-jobmanager and reused by
# flink-taskmanager and flink-pyjob-submitter. Without this, a fresh checkout
# fails `compose up` with "pull access denied". Cached builds are ~1s.
if ! docker image inspect aispm-flink-pyjob:latest >/dev/null 2>&1; then
  log "Building aispm-flink-pyjob image (one-time)..."
  # shellcheck disable=SC2086
  docker compose $COMPOSE_FILES build flink-jobmanager || {
    err "Failed to build aispm-flink-pyjob — aborting"
    exit 1
  }
fi

# The agent-runtime image lives behind the build-only profile. spm-api spawns
# one container per uploaded agent using this tag, so it must exist up front.
if ! docker image inspect aispm-agent-runtime:latest >/dev/null 2>&1; then
  log "Building aispm-agent-runtime image (one-time)..."
  # shellcheck disable=SC2086
  docker compose $COMPOSE_FILES --profile build-only build agent-runtime-build || {
    err "Failed to build aispm-agent-runtime — aborting"
    exit 1
  }
fi

if [ -n "$BUILD" ]; then
  log "BUILD=1 — rebuilding all images..."
  # shellcheck disable=SC2086
  docker compose $COMPOSE_FILES build || { err "Image build failed — aborting"; exit 1; }
  # shellcheck disable=SC2086
  docker compose $COMPOSE_FILES --profile build-only build agent-runtime-build || {
    err "agent-runtime build failed — aborting"; exit 1
  }
fi

# ── Bring the stack up ───────────────────────────────────────────────────────
log "Starting stack..."
# shellcheck disable=SC2086
docker compose $COMPOSE_FILES up -d --remove-orphans || {
  err "docker compose up failed — check above for errors"
  exit 1
}

# ── Wait for core services to be actually healthy ────────────────────────────
# `compose up -d` returns as soon as containers are *created*, not when they
# are *healthy*. Poll the real health endpoints before printing the success
# banner so callers (CI, scripts, humans) know the stack is actually usable.

wait_http() {
  local name="$1" url="$2" max="${3:-180}" interval="${4:-4}"
  local deadline
  deadline=$(( $(date +%s) + max ))
  log "Waiting for $name ($url)..."
  while [ "$(date +%s)" -lt "$deadline" ]; do
    if curl -sf --max-time 3 "$url" >/dev/null 2>&1; then
      log "  ✓ $name healthy"
      return 0
    fi
    sleep "$interval"
  done
  err "$name did not become healthy within ${max}s"
  err "  → check: docker compose logs $name"
  return 1
}

FAILED=0

# startup-orchestrator exits (it's a one-shot container, not a server).
# Poll its exit code instead of an HTTP endpoint.
log "Waiting for startup-orchestrator to complete (up to 120s)..."
SO_DEADLINE=$(( $(date +%s) + 120 ))
while [ "$(date +%s)" -lt "$SO_DEADLINE" ]; do
  SO_STATUS=$(docker inspect --format='{{.State.Status}}' cpm-startup-orchestrator 2>/dev/null || echo "missing")
  SO_EXIT=$(docker inspect --format='{{.State.ExitCode}}' cpm-startup-orchestrator 2>/dev/null || echo "")
  if [ "$SO_STATUS" = "exited" ] && [ "$SO_EXIT" = "0" ]; then
    log "  ✓ startup-orchestrator completed successfully"
    break
  elif [ "$SO_STATUS" = "exited" ] && [ "$SO_EXIT" != "0" ]; then
    err "startup-orchestrator exited with code $SO_EXIT"
    err "  → check: docker compose logs startup-orchestrator"
    FAILED=1
    break
  fi
  sleep 3
done
if [ "$(date +%s)" -ge "$SO_DEADLINE" ] && [ "$FAILED" -eq 0 ]; then
  err "startup-orchestrator did not finish within 120s"
  err "  → check: docker compose logs startup-orchestrator"
  FAILED=1
fi

# Core platform services — must be healthy before the stack is considered up.
wait_http "spm-api"      "http://localhost:8092/health" 180 4 || FAILED=1
wait_http "api"          "http://localhost:8080/health" 180 4 || FAILED=1
wait_http "spm-mcp"      "http://localhost:8500/health"  90 3 || FAILED=1
wait_http "spm-llm-proxy" "http://localhost:8501/health"  90 3 || FAILED=1

if [ "$FAILED" -ne 0 ]; then
  err "────────────────────────────────────────────────────────"
  err "One or more services failed to become healthy."
  err "Diagnose with:"
  err "  docker compose ps"
  err "  docker compose logs <service>"
  err "────────────────────────────────────────────────────────"
  exit 1
fi

# ── Success banner ───────────────────────────────────────────────────────────
echo ""
echo "Stack is up and healthy."
echo "  API           → http://localhost:8080"
echo "  SPM API       → http://localhost:8092"
echo "  spm-mcp       → http://localhost:8500/health     (agent tools — web_fetch)"
echo "  spm-llm-proxy → http://localhost:8501/health     (OpenAI-compat LLM shim)"
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
echo "Logs: docker compose logs -f [service]"
