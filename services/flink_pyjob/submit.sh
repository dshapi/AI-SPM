#!/usr/bin/env bash
# Submit the PyFlink CEP job to the JobManager.
#
# Idempotent in the practical sense: re-submitting will be rejected by
# the JobManager if a job with this name is already RUNNING. Use
# `make flink-cancel` first if you want to redeploy with new code.
#
# Required env (defaults shown for local docker-compose):
#   FLINK_JM_URL                - http://flink-jobmanager:8081
#   KAFKA_BOOTSTRAP_SERVERS     - kafka-broker:9092
#   CEP_TENANT_IDS              - t1                 (comma-separated)
#   CEP_AUDIT_TOPIC_SUFFIX      - audit               (shadow runs: audit_shadow)
#   CEP_PARALLELISM             - 2
set -euo pipefail

JM_URL="${FLINK_JM_URL:-http://flink-jobmanager:8081}"
BOOTSTRAP="${KAFKA_BOOTSTRAP_SERVERS:-kafka-broker:9092}"
TENANTS="${CEP_TENANT_IDS:-t1}"
SINK_SUFFIX="${CEP_AUDIT_TOPIC_SUFFIX:-audit}"
PARALLELISM="${CEP_PARALLELISM:-2}"

JOB_FILE="/opt/flink-pyjob/services/flink_pyjob/cep_job.py"

# Build a python files arg covering the whole package — Flink ships
# the user code to TaskManagers via this list.
PY_FILES="/opt/flink-pyjob/services/flink_pyjob,/opt/flink-pyjob/platform_shared"

# ── Wait for the JobManager REST API to be ready ────────────────────────────
# compose.yml depends_on uses `service_started` for flink-jobmanager (not
# `service_healthy` — there's no healthcheck defined on the JM service).
# `service_started` only means the container process was launched, not that
# the REST API is actually serving. Without this wait, `flink run` races the
# JM startup and fails immediately, and because restart="no" the submitter
# never retries.
JM_OVERVIEW_URL="${JM_URL}/overview"
JM_MAX_WAIT=120   # seconds
JM_INTERVAL=3
JM_DEADLINE=$(( $(date +%s) + JM_MAX_WAIT ))

echo ">> waiting for Flink JobManager REST API at ${JM_URL} (max ${JM_MAX_WAIT}s)..."
while [ "$(date +%s)" -lt "${JM_DEADLINE}" ]; do
  HTTP_STATUS=$(curl -sf --max-time 3 -o /dev/null -w "%{http_code}" "${JM_OVERVIEW_URL}" 2>/dev/null || echo "000")
  if [ "${HTTP_STATUS}" = "200" ]; then
    echo "   ✓ JobManager REST API is up (HTTP 200)"
    break
  fi
  REMAINING=$(( JM_DEADLINE - $(date +%s) ))
  echo "   JobManager not ready (HTTP ${HTTP_STATUS}) — retrying in ${JM_INTERVAL}s... (${REMAINING}s remaining)"
  sleep "${JM_INTERVAL}"
done

if [ "$(date +%s)" -ge "${JM_DEADLINE}" ]; then
  echo "ERROR: Flink JobManager REST API did not become ready within ${JM_MAX_WAIT}s at ${JM_URL}"
  exit 1
fi

echo ">> submitting flink-pyjob-cep to ${JM_URL}"
echo "   tenants=${TENANTS}  bootstrap=${BOOTSTRAP}  sink_suffix=${SINK_SUFFIX}  p=${PARALLELISM}"

exec flink run \
    --jobmanager "${JM_URL#http://}" \
    --python "${JOB_FILE}" \
    --pyFiles "${PY_FILES}" \
    --parallelism "${PARALLELISM}" \
    --detached \
    -D "env.java.opts=-DKAFKA_BOOTSTRAP_SERVERS=${BOOTSTRAP} -DCEP_TENANT_IDS=${TENANTS} -DCEP_AUDIT_TOPIC_SUFFIX=${SINK_SUFFIX}"
