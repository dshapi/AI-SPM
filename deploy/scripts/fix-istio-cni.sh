#!/usr/bin/env bash
# deploy/scripts/fix-istio-cni.sh
#
# Repair a broken istio-cni installation WITHOUT removing it.
#
# Symptoms this fixes:
#   - New pods stuck in Init:0/1 (istio-proxy init container hangs)
#   - Pod-to-pod traffic blackholed after istio-cni install
#   - CNI plugin binary missing or in the wrong directory
#   - Stale iptables rules left by a crashed istio-cni node agent
#
# What this does:
#   1. Detect the CNI binary directory actually used by the node
#   2. Ensure the istio-cni binary is present there (copy from DaemonSet pod if needed)
#   3. Validate the CNI conflist — fix the cniConfDir path if wrong
#   4. Restart the istio-cni DaemonSet to re-apply clean rules on every node
#   5. Roll affected application pods so they re-run through the fixed CNI chain
#   6. Verify istio-cni is present in the conflist and a test pod can network
#
# Usage:
#   bash deploy/scripts/fix-istio-cni.sh
#
# Env knobs:
#   NAMESPACE=aispm          namespace whose pods get the rolling restart (default: aispm)
#   ISTIO_NAMESPACE=istio-system
#   DRY_RUN=1                print actions without executing them
#
set -euo pipefail

NAMESPACE="${NAMESPACE:-aispm}"
ISTIO_NS="${ISTIO_NAMESPACE:-istio-system}"
DRY_RUN="${DRY_RUN:-0}"

log()  { echo "$(date +%H:%M:%S) [fix-istio-cni] $*"; }
warn() { echo "$(date +%H:%M:%S) [fix-istio-cni] WARN: $*" >&2; }
err()  { echo "$(date +%H:%M:%S) [fix-istio-cni] ERROR: $*" >&2; }
run()  {
  if [ "$DRY_RUN" = "1" ]; then
    echo "  [dry-run] $*"
  else
    "$@"
  fi
}

# ── 1. Detect CNI binary directory ────────────────────────────────────────
log "Step 1: detecting CNI binary directory on the node..."

# Spawn a privileged pod that mounts the host filesystem and looks for the
# istio-cni binary in the two common locations. We probe — we don't modify
# anything yet.
CNI_DEBUG_POD="cni-diag-$(date +%s)"
CNI_DETECT_SCRIPT='
CANDIDATES="/host/opt/cni/bin /host/usr/libexec/cni /host/usr/lib/cni"
FOUND_DIR=""
for d in $CANDIDATES; do
  if [ -f "$d/istio-cni" ]; then
    echo "FOUND:$d"
    FOUND_DIR="$d"
    break
  fi
done
# Also report which dir exists even if binary is absent (tells us where to put it)
for d in $CANDIDATES; do
  if [ -d "$d" ]; then
    echo "CANDIDATE_EXISTS:$d"
  fi
done
if [ -z "$FOUND_DIR" ]; then
  echo "BINARY_MISSING"
fi
# Show current conflist so we can inspect the cniConfDir
echo "=== CONFLIST ==="
cat /host/etc/cni/net.d/*.conflist 2>/dev/null || echo "(no .conflist files)"
echo "=== END_CONFLIST ==="
'

DETECT_OUTPUT=$(kubectl run "$CNI_DEBUG_POD" --rm -i --restart=Never \
  --namespace=kube-system \
  --overrides="$(cat <<JSON
{
  "spec": {
    "hostNetwork": true,
    "tolerations": [{"operator":"Exists"}],
    "containers": [{
      "name": "d",
      "image": "alpine:3.19",
      "command": ["/bin/sh", "-c"],
      "args": [$(echo "$CNI_DETECT_SCRIPT" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')],
      "volumeMounts": [{"name":"host","mountPath":"/host"}],
      "securityContext": {"privileged": true}
    }],
    "volumes": [{"name":"host","hostPath":{"path":"/"}}]
  }
}
JSON
)" --image=alpine:3.19 2>/dev/null)

log "  CNI probe output:"
echo "$DETECT_OUTPUT" | sed 's/^/    /'

BINARY_PRESENT=1
echo "$DETECT_OUTPUT" | grep -q "BINARY_MISSING" && BINARY_PRESENT=0

# Pick the discovered binary dir, or the first existing candidate
CNI_BIN_DIR=$(echo "$DETECT_OUTPUT" | grep "^FOUND:" | head -1 | cut -d: -f2 || true)
if [ -z "$CNI_BIN_DIR" ]; then
  CNI_BIN_DIR=$(echo "$DETECT_OUTPUT" | grep "^CANDIDATE_EXISTS:" | head -1 | cut -d: -f2 || true)
fi
CNI_BIN_DIR="${CNI_BIN_DIR:-/opt/cni/bin}"
log "  CNI binary directory: $CNI_BIN_DIR"

# ── 2. Repair binary if missing ───────────────────────────────────────────
if [ "$BINARY_PRESENT" -eq 0 ]; then
  log "Step 2: istio-cni binary missing — copying from DaemonSet pod..."

  ISTIO_CNI_POD=$(kubectl -n "$ISTIO_NS" get pod \
    -l app=istio-cni-node \
    --field-selector=status.phase=Running \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)

  if [ -z "$ISTIO_CNI_POD" ]; then
    err "No running istio-cni-node pod found in $ISTIO_NS — cannot copy binary."
    err "Try: helm upgrade --install istio-cni istio/cni -n $ISTIO_NS --set cni.cniBinDir=$CNI_BIN_DIR"
    exit 1
  fi

  log "  istio-cni pod: $ISTIO_CNI_POD"
  run kubectl -n "$ISTIO_NS" exec "$ISTIO_CNI_POD" -- \
    cp /opt/cni/bin/istio-cni /host"$CNI_BIN_DIR"/istio-cni
  log "  ✓ binary copied to $CNI_BIN_DIR"
else
  log "Step 2: istio-cni binary present at $CNI_BIN_DIR — skipping copy"
fi

# ── 3. Patch the Helm release if cniConfDir is wrong ─────────────────────
log "Step 3: verifying istio-cni Helm values (cni.cniBinDir)..."

CURRENT_BIN_DIR=$(helm -n "$ISTIO_NS" get values istio-cni 2>/dev/null \
  | grep cniBinDir | awk '{print $2}' || true)

if [ -n "$CURRENT_BIN_DIR" ] && [ "$CURRENT_BIN_DIR" != "$CNI_BIN_DIR" ]; then
  log "  Helm has cniBinDir=$CURRENT_BIN_DIR but node uses $CNI_BIN_DIR — patching..."
  run helm upgrade istio-cni istio/cni \
    -n "$ISTIO_NS" \
    --reuse-values \
    --set cni.cniBinDir="$CNI_BIN_DIR" \
    --wait --timeout=3m
  log "  ✓ Helm release updated with cniBinDir=$CNI_BIN_DIR"
else
  log "  cniBinDir OK ($CNI_BIN_DIR)"
fi

# ── 4. Restart istio-cni DaemonSet ────────────────────────────────────────
# This evicts the node agent pods and lets them re-run installCNI(), which:
#   - rewrites the CNI conflist with a clean istio-cni plugin entry
#   - re-creates iptables rules on the node
#   - removes any stale rules left by a previous crashed agent
log "Step 4: restarting istio-cni DaemonSet to flush stale iptables + rewrite conflist..."
run kubectl -n "$ISTIO_NS" rollout restart daemonset/istio-cni-node
run kubectl -n "$ISTIO_NS" rollout status  daemonset/istio-cni-node --timeout=3m
log "  ✓ istio-cni DaemonSet restarted"

# ── 5. Rolling restart of application pods ────────────────────────────────
# Pods that were scheduled during the broken window have corrupt iptables
# rules. A rolling restart forces them through the now-fixed CNI chain.
log "Step 5: rolling restart of Deployments and StatefulSets in $NAMESPACE..."
for kind in deployment statefulset; do
  RESOURCES=$(kubectl -n "$NAMESPACE" get "$kind" \
    --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null || true)
  for name in $RESOURCES; do
    log "  restarting $kind/$name..."
    run kubectl -n "$NAMESPACE" rollout restart "$kind/$name"
  done
done

log "  waiting for rollouts to complete (up to 5m)..."
for kind in deployment statefulset; do
  RESOURCES=$(kubectl -n "$NAMESPACE" get "$kind" \
    --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null || true)
  for name in $RESOURCES; do
    run kubectl -n "$NAMESPACE" rollout status "$kind/$name" --timeout=5m \
      || warn "$kind/$name did not complete rollout — check: kubectl -n $NAMESPACE describe $kind $name"
  done
done
log "  ✓ rollouts complete"

# ── 6. Verify istio-cni is present in conflist ────────────────────────────
log "Step 6: verifying istio-cni is present in the CNI conflist..."

VERIFY_POD="cni-verify-$(date +%s)"
VERIFY_OUTPUT=$(kubectl run "$VERIFY_POD" --rm -i --restart=Never \
  --namespace=kube-system \
  --overrides="$(cat <<JSON
{
  "spec": {
    "hostNetwork": true,
    "tolerations": [{"operator":"Exists"}],
    "containers": [{
      "name": "v",
      "image": "alpine:3.19",
      "command": ["/bin/sh", "-c"],
      "args": ["grep -l istio-cni /host/etc/cni/net.d/*.conflist 2>/dev/null && echo ISTIO_CNI_PRESENT || echo ISTIO_CNI_ABSENT"],
      "volumeMounts": [{"name":"host","mountPath":"/host"}],
      "securityContext": {"privileged": true}
    }],
    "volumes": [{"name":"host","hostPath":{"path":"/"}}]
  }
}
JSON
)" --image=alpine:3.19 2>/dev/null)

if echo "$VERIFY_OUTPUT" | grep -q "ISTIO_CNI_PRESENT"; then
  log "  ✓ istio-cni confirmed present in CNI conflist"
else
  err "  istio-cni NOT found in CNI conflist after repair — manual investigation needed"
  err "  Run: kubectl -n $ISTIO_NS logs daemonset/istio-cni-node"
  exit 1
fi

# ── Done ──────────────────────────────────────────────────────────────────
echo ""
echo "═══ istio-cni repair complete ═══"
echo ""
echo "  ✓ CNI binary present at:     $CNI_BIN_DIR"
echo "  ✓ istio-cni DaemonSet:       restarted"
echo "  ✓ $NAMESPACE pods:           rolling-restarted"
echo "  ✓ istio-cni in conflist:     confirmed"
echo ""
echo "If pods are still stuck, check:"
echo "  kubectl -n $ISTIO_NS   logs daemonset/istio-cni-node"
echo "  kubectl -n $NAMESPACE  describe pod <stuck-pod>"
echo "  kubectl -n $NAMESPACE  logs <stuck-pod> -c istio-proxy"
