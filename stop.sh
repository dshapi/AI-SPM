#!/bin/bash

# Stop and remove containers.
# Pass --volumes (or -v) to also wipe persistent volumes (redis, postgres, grafana, etc.)

docker compose -f docker-compose.yml -f docker-compose.auth.yml down "$@"
