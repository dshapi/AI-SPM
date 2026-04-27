#!/bin/bash

# Stop and remove containers.
# Pass --volumes (or -v) to also wipe persistent volumes (redis, postgres, grafana, etc.)

# Phase 3 — customer-uploaded agent containers are NOT declared in the
# compose file (spm-api spawns them on demand via the docker SDK with
# names like `agent-<uuid>`), so `compose down` won't reach them. Stop
# any running ones up-front so the network teardown doesn't leave them
# orphaned with broken connectivity.
agent_ctrs=$(docker ps -q --filter "name=^agent-" --filter "ancestor=aispm-agent-runtime:latest" 2>/dev/null || true)
if [ -n "$agent_ctrs" ]; then
  echo "Stopping $(echo "$agent_ctrs" | wc -l | tr -d ' ') agent runtime container(s)…"
  # 10s grace matches spm-api's stop_agent_container() to keep the SDK's
  # graceful-shutdown path working when stop.sh races a deploy.
  docker stop -t 10 $agent_ctrs >/dev/null
  docker rm -f      $agent_ctrs >/dev/null
fi

docker compose -f compose.yml -f compose.auth.yml down "$@"
