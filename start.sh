#!/bin/bash
set -e

BUILD=${BUILD:-}   # set BUILD=1 to force-rebuild every image before starting

# The aispm-flink-pyjob image is built once by flink-jobmanager and reused by
# flink-taskmanager and flink-pyjob-submitter (they reference the same tag but
# don't have their own build: directive). Without this, a fresh checkout — or
# any host where `docker system prune` has cleared the local cache — fails
# `compose up` with "pull access denied" the first time it tries to start the
# stack. Build the image up-front if it's missing; cached builds are ~1s.
if ! docker image inspect aispm-flink-pyjob:latest >/dev/null 2>&1; then
  echo "Building aispm-flink-pyjob image (one-time)..."
  docker compose -f docker-compose.yml -f docker-compose.auth.yml build flink-jobmanager
fi

if [ -n "$BUILD" ]; then
  docker compose -f docker-compose.yml -f docker-compose.auth.yml build
fi

docker compose -f docker-compose.yml -f docker-compose.auth.yml up -d --remove-orphans

echo ""
echo "Stack is up."
echo "  API         → http://localhost:8080"
echo "  SPM API     → http://localhost:8092"
echo "  Grafana     → http://localhost:3000"
echo "  Prometheus  → http://localhost:9090"
echo "  Traefik     → http://localhost:9091/dashboard/"
echo "  Keycloak    → http://keycloak.local:8180"
echo ""
echo "  With auth:            http://aispm.local/admin"
echo "  OrbiX Chat Bot:       http://aispm.local"

echo "Logs: docker compose logs -f [service]"
