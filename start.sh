#!/bin/bash
set -e

BUILD=${BUILD:-}   # set BUILD=1 to rebuild images before starting

if [ -n "$BUILD" ]; then
  docker compose -f docker-compose.yml -f docker-compose.auth.yml build
fi

docker compose -f docker-compose.yml -f docker-compose.auth.yml up -d --remove-orphans

echo ""
echo "Stack is up."
echo "  UI          → http://localhost:3001"
echo "  API         → http://localhost:8080"
echo "  SPM API     → http://localhost:8092"
echo "  Grafana     → http://localhost:3000"
echo "  Prometheus  → http://localhost:9090"
echo "  Traefik     → http://localhost:9091/dashboard/"
echo "  Keycloak    → http://keycloak.local:8180"
echo ""
echo "  With auth:    http://aispm.local"
echo ""
echo "Logs: docker compose logs -f [service]"
