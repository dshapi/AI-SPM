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

echo ">> submitting flink-pyjob-cep to ${JM_URL}"
echo "   tenants=${TENANTS}  bootstrap=${BOOTSTRAP}  sink_suffix=${SINK_SUFFIX}  p=${PARALLELISM}"

exec flink run \
    --jobmanager "${JM_URL#http://}" \
    --python "${JOB_FILE}" \
    --pyFiles "${PY_FILES}" \
    --parallelism "${PARALLELISM}" \
    --detached \
    -D "env.java.opts=-DKAFKA_BOOTSTRAP_SERVERS=${BOOTSTRAP} -DCEP_TENANT_IDS=${TENANTS} -DCEP_AUDIT_TOPIC_SUFFIX=${SINK_SUFFIX}"
