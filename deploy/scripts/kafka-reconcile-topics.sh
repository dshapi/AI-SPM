#!/usr/bin/env bash
# deploy/scripts/kafka-reconcile-topics.sh
# ──────────────────────────────────────────────────────────────────────
# One-shot reconciliation of Kafka topics that drifted to the wrong
# replication factor. Specifically targets the failure mode where a
# topic was auto-created with broker default RF=1 while the cluster's
# min.insync.replicas=2 — every write to such a topic fails with
# NotEnoughReplicasException forever.
#
# What this does:
#   1. Lists every non-internal topic in the cluster.
#   2. For each topic with RF < TARGET_RF, generates a partition
#      reassignment plan that distributes replicas across all brokers
#      [0..TARGET_RF-1].
#   3. Applies the plan with `kafka-reassign-partitions --execute`.
#   4. Polls `--verify` until the reassignment completes.
#
# Designed to be safe to re-run:
#   - Topics already at TARGET_RF are skipped.
#   - Reassignment is data-preserving (kafka backfills from leader).
#   - No data is deleted.
#
# When to use:
#   - After ./startup-orchestrator logs "⚠ N topic(s) have wrong
#     replication factor" and points here.
#   - After a fresh deploy where some topics auto-created before broker
#     defaults were set.
#   - Disaster-recovery scenarios that restored from an older snapshot.
#
# Usage (from repo root, with KUBECONFIG pointing at the kind cluster):
#   ./deploy/scripts/kafka-reconcile-topics.sh
#
# Env overrides:
#   NAMESPACE      (default "aispm")
#   POD            (default "kafka-0")
#   TARGET_RF      (default 3)
#   BROKER_LIST    (default "0,1,2")
#   DRY_RUN        (set to "1" to print plans without applying)
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

NAMESPACE="${NAMESPACE:-aispm}"
POD="${POD:-kafka-0}"
TARGET_RF="${TARGET_RF:-3}"
BROKER_LIST="${BROKER_LIST:-0,1,2}"
DRY_RUN="${DRY_RUN:-0}"
KAFKA_BIN="${KAFKA_BIN:-/usr/bin}"
BOOTSTRAP="${BOOTSTRAP:-localhost:9092}"

_log()  { printf '\033[1;36m▶ %s\033[0m\n' "$*"; }
_warn() { printf '\033[1;33m! %s\033[0m\n' "$*"; }
_die()  { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

_kx() { kubectl -n "$NAMESPACE" exec "$POD" -- "$@"; }

# ── 0. Sanity ───────────────────────────────────────────────────────

_log "Verifying connectivity to ${POD} in namespace ${NAMESPACE}"
_kx "${KAFKA_BIN}/kafka-broker-api-versions" --bootstrap-server "$BOOTSTRAP" \
  >/dev/null \
  || _die "Cannot reach kafka via ${POD}; check namespace/pod/network"

# ── 1. Enumerate topics + their current RFs ─────────────────────────

_log "Listing non-internal topics"
TOPICS=$(_kx "${KAFKA_BIN}/kafka-topics" --bootstrap-server "$BOOTSTRAP" \
            --list --exclude-internal | tr -d '\r')
[ -n "$TOPICS" ] || _die "No topics returned"

NEEDS_FIX=()
# Disable pipefail inside the loop: awk's `exit` can SIGPIPE the upstream
# kubectl exec on larger topic descriptions, which under pipefail aborts
# the whole script. We read the describe output into a variable first
# (no pipe in flight when awk exits), then parse.
set +o pipefail
for t in $TOPICS; do
  desc=$(_kx "${KAFKA_BIN}/kafka-topics" --bootstrap-server "$BOOTSTRAP" \
           --describe --topic "$t" 2>/dev/null || true)
  rf=$(printf '%s\n' "$desc" \
       | awk '/ReplicationFactor:/ { for (i=1;i<=NF;i++) if ($i=="ReplicationFactor:") { print $(i+1); exit } }')
  if [ -z "$rf" ]; then
    _warn "  $t — could not parse RF, skipping"
    continue
  fi
  if [ "$rf" -lt "$TARGET_RF" ]; then
    _log "  $t  rf=${rf}  → needs fix"
    NEEDS_FIX+=("$t")
  else
    printf '  %-60s rf=%s ✓\n' "$t" "$rf"
  fi
done
set -o pipefail

if [ "${#NEEDS_FIX[@]}" -eq 0 ]; then
  _log "All topics already at RF≥${TARGET_RF}. Nothing to do."
  exit 0
fi

_log "${#NEEDS_FIX[@]} topic(s) need reassignment to RF=${TARGET_RF}"

# ── 2. Build a reassignment plan ────────────────────────────────────

PLAN_FILE_LOCAL="/tmp/aispm-reassign-$(date +%s).json"
PLAN_FILE_POD="/tmp/aispm-reassign.json"
echo '{ "version": 1, "partitions": [' > "$PLAN_FILE_LOCAL"

# Convert "0,1,2" → "0, 1, 2" for JSON readability
JSON_BROKERS=$(echo "$BROKER_LIST" | sed 's/,/, /g')

FIRST=1
set +o pipefail
for t in "${NEEDS_FIX[@]}"; do
  desc=$(_kx "${KAFKA_BIN}/kafka-topics" --bootstrap-server "$BOOTSTRAP" \
           --describe --topic "$t" 2>/dev/null || true)
  parts=$(printf '%s\n' "$desc" \
          | awk '/PartitionCount:/ { for (i=1;i<=NF;i++) if ($i=="PartitionCount:") { print $(i+1); exit } }')
  [ -n "$parts" ] || { _warn "  $t — no PartitionCount, skipping"; continue; }

  for p in $(seq 0 $((parts - 1))); do
    if [ "$FIRST" -eq 0 ]; then echo "," >> "$PLAN_FILE_LOCAL"; fi
    FIRST=0
    printf '  {"topic": "%s", "partition": %d, "replicas": [%s]}' \
      "$t" "$p" "$JSON_BROKERS" >> "$PLAN_FILE_LOCAL"
  done
done
set -o pipefail

printf '\n] }\n' >> "$PLAN_FILE_LOCAL"

_log "Reassignment plan written to $PLAN_FILE_LOCAL"
echo "─────────────────────────────────────────────────────────────"
cat "$PLAN_FILE_LOCAL"
echo "─────────────────────────────────────────────────────────────"

if [ "$DRY_RUN" = "1" ]; then
  _log "DRY_RUN=1 — not applying. Re-run without DRY_RUN to execute."
  exit 0
fi

_warn "About to APPLY this reassignment in 5s. Ctrl+C to abort."
sleep 5

# ── 3. Copy plan into pod & execute ─────────────────────────────────

kubectl -n "$NAMESPACE" cp "$PLAN_FILE_LOCAL" "${POD}:${PLAN_FILE_POD}"

_log "Executing reassignment"
_kx "${KAFKA_BIN}/kafka-reassign-partitions" \
  --bootstrap-server "$BOOTSTRAP" \
  --reassignment-json-file "$PLAN_FILE_POD" \
  --execute

# ── 4. Poll until complete ──────────────────────────────────────────
#
# Done when no partition is "still in progress" AND we see either
# per-partition "is complete." lines OR the throttle-cleanup messages
# that kafka-reassign-partitions emits on final success. Earlier
# versions only matched "is complete." which missed the case where the
# verify command had already cleaned up — leaving the script polling
# indefinitely until the 10-min timeout.

_log "Polling --verify every 10s (timeout 10 min)"
for i in $(seq 1 60); do
  out=$(_kx "${KAFKA_BIN}/kafka-reassign-partitions" \
          --bootstrap-server "$BOOTSTRAP" \
          --reassignment-json-file "$PLAN_FILE_POD" \
          --verify 2>&1 || true)
  echo "$out" | tail -5
  if ! echo "$out" | grep -q "is still in progress"; then
    if echo "$out" | grep -qE "is complete\.|Clearing (broker|topic)-level throttles"; then
      _log "Reassignment complete."
      break
    fi
  fi
  sleep 10
done

# ── 5. Final verification ───────────────────────────────────────────

_log "Final ISR check for the topics we touched:"
for t in "${NEEDS_FIX[@]}"; do
  _kx "${KAFKA_BIN}/kafka-topics" --bootstrap-server "$BOOTSTRAP" \
    --describe --topic "$t" \
    | grep -E "PartitionCount|Isr:" | head -10
done

_log "Done. Run startup-orchestrator (or its Job) to reconcile retention configs."
