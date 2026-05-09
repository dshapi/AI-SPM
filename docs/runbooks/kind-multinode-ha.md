# Multi-node HA Cluster (kind on Docker) — Runbook

This is the operational manual for the 3-node kind cluster that AISPM
runs on locally.  kind on Docker is the only supported local
topology since May 2026 — single-instance fallbacks have been removed
from the chart (see "HA-only contract" under "Recent architectural
changes" below).  Every stateful layer is HA via application-level
replication; storage is local-path because no FUSE/iSCSI/RBD-based CSI
driver works reliably under the Docker engine's Linux kernel, and we
don't need replicated block storage anyway since CNPG, Redis Sentinel,
MinIO, and Kafka all replicate at the application layer.

## Architecture

| Layer    | Implementation                  | Replicas             | What survives a node loss                        |
| -------- | ------------------------------- | -------------------- | ------------------------------------------------ |
| Cluster  | kind v1.31, all control-plane   | 3                    | etcd quorum, kube-apiserver via external LB      |
| Block    | local-path (kind built-in)      | 1 PVC per pod        | N/A — each pod owns its own disk                 |
| Object   | MinIO distributed mode          | 4 pods, EC           | 1 node loss tolerated by erasure coding          |
| Postgres | CloudNativePG `Cluster`         | 3 (1 primary + 2 replicas) | Standby promotes automatically on primary loss   |
| Redis    | Bitnami chart, replication+sentinel | 1m + 3r + 3 sentinels | Sentinels elect a new master                  |
| Kafka    | KRaft, anti-affinity, RF=3, min-isr=2 | 3 brokers      | Topics keep serving from the remaining 2 brokers |
| Flink    | 2 JM + 2 TM, state on MinIO via s3:// | -                | JMs leader-elect via Kubernetes lease            |

There is no replicated block storage and no shared filesystem. State
that must survive a pod loss lives where the application itself
replicates it: Postgres WAL, Kafka log, Redis AOF, MinIO erasure-coded
chunks, or in MinIO via Flink's s3-fs-hadoop plugin.

## Filesystem layout

| Path                                            | Purpose                                       |
| ----------------------------------------------- | --------------------------------------------- |
| `~/.kube/kind-aispm.yaml`                       | kubeconfig for the cluster                    |
| `/tmp/kind-vols/control-plane-{1,2,3}`          | Per-node host extraMounts (PVC backing dir)   |
| `deploy/scripts/kind-cluster.sh`                | Cluster lifecycle (init / up / down / status / destroy) |
| `deploy/scripts/aispm-cluster.sh`               | Day-to-day lifecycle (pause / resume / snapshot / restore) |
| `deploy/scripts/kind-storage.sh`                | MinIO install + flink bucket                  |
| `deploy/scripts/kind-databases-ha.sh`           | CNPG operator + Postgres Cluster + Bitnami Redis |
| `deploy/helm/aispm/values.dev-multinode.yaml`   | Chart overrides for this cluster              |
| `~/.aispm/snapshots/etcd-*.db`                  | etcd snapshots (cron, every 10 min)           |

## Bring-up (clean cluster)

Run from `/Users/danyshapiro/PycharmProjects/AISPM`. Each step is idempotent.

```bash
export KUBECONFIG=$HOME/.kube/kind-aispm.yaml

./deploy/scripts/kind-cluster.sh init           # cluster + registry + metrics-server
./deploy/scripts/kind-storage.sh up             # MinIO + flink bucket
./deploy/scripts/kind-databases-ha.sh up        # CNPG + Bitnami Redis Sentinel

# Push AISPM service images to the local registry the kind nodes pull from:
docker compose build
docker images --format '{{.Repository}}' | grep '^aispm-' | sort -u | while read img; do
  docker tag "${img}:latest" "localhost:5001/${img}:latest"
  docker push "localhost:5001/${img}:latest"
done

# Alias for chart templates that hardcode `local-path`:
cat <<'EOF' | kubectl apply -f -
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: local-path
provisioner: rancher.io/local-path
reclaimPolicy: Delete
volumeBindingMode: WaitForFirstConsumer
EOF

SKIP_FALCO=1 SKIP_KYVERNO=1 \
  VALUES_EXTRA=deploy/helm/aispm/values.dev-multinode.yaml \
  ./deploy/scripts/bootstrap-cluster.sh
```

End-to-end on a fresh machine: about 20 minutes. Subsequent runs that
only re-deploy the AISPM chart take about 5 minutes.

## Tear-down

```bash
./deploy/scripts/kind-cluster.sh destroy
```

Removes the kind containers, the registry container, the kubeconfig,
and `/tmp/kind-vols`. The Docker images you built (`aispm-*`) are kept.

## Day-to-day operations

```bash
# Cluster + node health
kubectl get nodes
kubectl top nodes

# Everything across all namespaces (shows aispm + istio + kube-system together)
kubectl get pods -A
kubectl get pods -A | grep -vE 'Running|Completed'

# AISPM workloads
kubectl -n aispm get pods
kubectl -n aispm get pods | grep -vE 'Running|Completed'

# CNPG Postgres status
kubectl -n aispm get cluster spm-db
kubectl -n aispm get pods -l cnpg.io/cluster=spm-db -o wide

# Redis Sentinel master (which pod is the current master?)
kubectl -n aispm exec redis-node-0 -c sentinel -- \
  redis-cli -p 26379 sentinel get-master-addr-by-name mymaster

# MinIO buckets
kubectl -n minio run mc-ls --rm -i --restart=Never \
  --image=quay.io/minio/mc:RELEASE.2024-11-21T17-21-54Z \
  --env="MC_HOST_local=http://minioadmin:minioadmin@minio.minio.svc.cluster.local:9000" \
  --command -- mc ls local

# Push a fresh image after rebuilding
docker compose build api
docker tag aispm-api:latest localhost:5001/aispm-api:latest
docker push localhost:5001/aispm-api:latest
kubectl -n aispm rollout restart deployment/api
```

## Persistence across Docker restarts

This cluster is durable across normal day-to-day workflow, but Docker
Desktop's full Quit/Restart cycle is hostile to a 3-node etcd because
container IPs reshuffle and peer TLS certs (whose SANs include the
old IPs) stop validating. The lifecycle helper script
`deploy/scripts/aispm-cluster.sh` plus a snapshot cron protects against
this.

### End of day (Docker stays running)

Pause everything and resume next morning. State, leader leases, peer
TLS connections — all preserved verbatim. Survives Mac sleep/wake.

```bash
./deploy/scripts/aispm-cluster.sh pause
# ... walk away ...
./deploy/scripts/aispm-cluster.sh resume
kubectl get nodes      # should respond immediately
```

### Quitting Docker / rebooting Mac

Take a fresh snapshot first so post-reboot recovery uses the most
recent state, then quit Docker normally. On return, restore.

```bash
./deploy/scripts/aispm-cluster.sh snapshot
# ... quit Docker, reboot, whatever ...
./deploy/scripts/aispm-cluster.sh restore $(ls -1t ~/.aispm/snapshots/etcd-*.db | head -1)
```

The restore takes ~2 minutes:

- discovers each control-plane node's current IP
- moves all 3 etcd manifests aside (kubelet stops the pods)
- wipes `/var/lib/etcd` on each node
- restores the snapshot to fresh data dirs with current IPs in
  `--initial-cluster` and `--initial-advertise-peer-urls`
- regenerates etcd peer + server certs against the current node IPs
  via `kubeadm init phase certs etcd-{server,peer}`
- patches each etcd.yaml with the current IPs and puts it back
- waits for kube-apiserver to recover behind the LB

After restore, you almost always need a follow-up:

```bash
# kube-proxy iptables and CNI may have stale routes
kubectl -n kube-system rollout restart daemonset kube-proxy kindnet

# istiod CA service path may need a refresh too
kubectl -n istio-system rollout restart deploy istiod
kubectl -n istio-system rollout status deploy istiod --timeout=2m

# Then bounce app pods so sidecars re-warm certs from refreshed istiod
kubectl -n aispm rollout restart deploy
kubectl -n aispm rollout restart statefulset
```

### Cron snapshot safety net

The cron entry installed in `crontab -e` snapshots etcd every 10 min
to `~/.aispm/snapshots/`. This catches unexpected shutdowns (crash,
power loss, forgotten manual snapshot). The script keeps the most
recent 50 snapshots and rotates older ones.

```bash
*/10 * * * * /Users/danyshapiro/PycharmProjects/AISPM/deploy/scripts/aispm-cluster.sh snapshot >> ~/.aispm/snapshots.log 2>&1
```

macOS requires `cron` (`/usr/sbin/cron`) to be in **System Settings →
Privacy & Security → Full Disk Access** for the schedule to actually
fire. Verify after the next 10-min mark:

```bash
ls -lt ~/.aispm/snapshots/ | head
tail ~/.aispm/snapshots.log
```

**macOS cron PATH gotcha** — cron inherits a minimal PATH
(`/usr/bin:/bin`) that does NOT include `/usr/local/bin` or
`/opt/homebrew/bin` where `docker`/`kubectl` live. The
`aispm-cluster.sh` script now self-sets PATH at the top, so the
recommended crontab entry works as-is. If snapshots.log shows
errors like "Container aispm-control-plane does not exist" despite
the cluster running, that's the symptom — pull the latest version
of `aispm-cluster.sh` (which exports PATH explicitly and gives
clearer "docker not found on PATH" / "docker daemon not responding"
error messages instead of the misleading container-missing one).

### What does NOT survive

- `aispm-cluster.sh pause` does not survive Docker Quit or Mac reboot
  (pause state lives in the running Docker VM). Use snapshot/restore
  for those cases.
- Postgres replicas (`spm-db-1/2/3`) recover via WAL streaming after
  Postgres-0 comes back. Expect ~1–2 min of `1/2 CrashLoopBackOff`
  while replicas wait for the primary's sidecar to be reachable.
- istio sidecars (every `0/2` pod) only recover after istiod's
  ClusterIP path is reachable. The post-restore checklist above takes
  care of this.

## Failover tests

These prove every HA layer actually works. Run them when the cluster
is idle and watch the chosen layer recover.

### Kafka — kill a broker

```bash
kubectl -n aispm get pods -l app=kafka -o wide
kubectl -n aispm delete pod kafka-1                   # any broker

# Watch: producer/consumer traffic continues through kafka-0 and kafka-2.
# kafka-1 reschedules on the same node (its PVC is local-path).
kubectl -n aispm get pods -l app=kafka -w
```

Topics keep serving because replication-factor=3 + min-isr=2 means only
1 of 3 replicas is needed for acked writes. The metric to watch is the
ISR list — temporarily 2 entries during recovery, back to 3 after.

### Postgres — kill the primary

```bash
PRIMARY=$(kubectl -n aispm get pods -l cnpg.io/instanceRole=primary -o name)
echo "current primary: $PRIMARY"
kubectl -n aispm delete "$PRIMARY"

# Watch: CNPG promotes a standby to primary within ~10s.
kubectl -n aispm get cluster spm-db -w
```

The `spm-db-rw` Service follows the new primary automatically so AISPM
clients reconnect without any code change.

### Redis — kill the master

```bash
MASTER_HOST=$(kubectl -n aispm exec redis-node-0 -c sentinel -- \
  redis-cli -p 26379 sentinel get-master-addr-by-name mymaster | head -1)
echo "current master: $MASTER_HOST"
MASTER_POD=${MASTER_HOST%%.*}
kubectl -n aispm delete pod "$MASTER_POD"

# Watch: a sentinel quorum (2/3) elects a new master within ~30s.
sleep 35
kubectl -n aispm exec redis-node-0 -c sentinel -- \
  redis-cli -p 26379 sentinel get-master-addr-by-name mymaster
```

The `redis` Service is sentinel-aware; clients connecting to it land on
the new master automatically.

### MinIO — kill a node

```bash
kubectl -n minio get pods -o wide
kubectl -n minio delete pod minio-0

# Reads / writes for the `flink` bucket continue immediately;
# erasure-coded data is reconstructed from the other 3 pods. minio-0
# rejoins when its pod restarts and resyncs its drive.
```

### Flink — kill the active JobManager

```bash
kubectl -n aispm get pods -l app=flink-jobmanager -o wide
ACTIVE_JM=flink-jobmanager-0
kubectl -n aispm delete pod "$ACTIVE_JM"

# Watch: the standby JM (flink-jobmanager-1) wins the Kubernetes lease
# within ~5s and resumes the running PyFlink CEP job from its last
# checkpoint stored in s3://flink/checkpoints/.
kubectl -n aispm logs flink-jobmanager-1 -c flink-jobmanager --tail=20
```

### Whole-node failure

```bash
docker stop aispm-control-plane2

# All pods that were on that node go NotReady. Each HA layer recovers
# independently:
#   - Kafka: serves from the other 2 brokers.
#   - CNPG: promotes a standby on a healthy node.
#   - Redis: sentinels elect a new master.
#   - MinIO: erasure coding tolerates 1 lost pod.
#   - Flink: JM standby on a healthy node takes the lease.
sleep 60
kubectl get nodes
kubectl -n aispm get pods -o wide

# Bring the node back:
docker start aispm-control-plane2
sleep 60
kubectl -n aispm get pods -o wide
```

Local-path PVCs are bound to specific node disks, so pods that had
been on the killed node remain unscheduable until the node returns.
That is acceptable: every workload above has at least one healthy
replica on a different node.

## Troubleshooting

### kubectl returns `EOF` or `connection refused`

Two distinct failures share this symptom. Diagnose before acting.

**(a) Stale kubeconfig endpoint after Docker restart.** kind picks a
random host port for the API server LB on each cluster create. After
the Docker daemon restarts, the LB container's host port may differ
from what your kubeconfig expects. The `networking.apiServerPort: 6443`
pin in `kind-cluster.sh` prevents this on new clusters; if the cluster
predates that change, refresh the kubeconfig:

```bash
kind export kubeconfig --name aispm
kubectl get nodes
```

**(b) etcd peer-TLS rejecting peers — the real Docker-restart killer.**
Symptom in `docker exec aispm-control-plane crictl logs <etcd>`:

```
"rejected connection on peer endpoint" ... "remote error: tls: bad certificate"
```

Root cause: kind nodes get fresh container IPs from Docker's bridge
network on every cold start. The kubeadm-issued etcd peer certs have
SANs pinned to the original IPs, AND each node's etcd manifest has
`--initial-cluster` / `--initial-advertise-peer-urls` pinned to the
original IPs. When Docker reshuffles, the live IP at every node has
the wrong cert and the wrong peer-URL config.

The recovery procedure that **does not** require destroy+rebootstrap
is `aispm-cluster.sh restore` — see "Persistence across Docker restarts"
above. It rebuilds etcd from the latest snapshot with current IPs and
regenerates the peer certs against those IPs. Total time ~2 min.

The old guidance ("destroy && init") still works as a last resort if
no snapshots exist or the restore script fails for unrelated reasons,
but you'll lose application state in K8s objects (PVs survive — they
are host-mounted).

### Image pull errors after `kind-cluster.sh destroy`

The destroy removes the registry container and containerd's
`/etc/containerd/certs.d/localhost:5001/` config from each node.
`kind-cluster.sh init` re-wires both, but if you destroyed and recreated
manually, run:

```bash
docker network connect kind aispm-registry 2>/dev/null
for n in aispm-control-plane aispm-control-plane2 aispm-control-plane3; do
  docker exec "$n" mkdir -p '/etc/containerd/certs.d/localhost:5001'
  docker exec "$n" sh -c 'echo "[host.\"http://aispm-registry:5000\"]" > /etc/containerd/certs.d/localhost:5001/hosts.toml'
done
```

### MinIO bucket missing

If Flink JM logs show `NoSuchBucket: The specified bucket does not exist`:

```bash
kubectl -n minio run mc-mb --rm -i --restart=Never \
  --image=quay.io/minio/mc:RELEASE.2024-11-21T17-21-54Z \
  --env="MC_HOST_local=http://minioadmin:minioadmin@minio.minio.svc.cluster.local:9000" \
  --command -- mc mb --ignore-existing local/flink
kubectl -n aispm delete pod -l app=flink-jobmanager
```

### Flink JM `Illegal character in scheme name`

Means the s3 endpoint in `flink-conf.yaml` is wrapped in quotes Flink
can't parse. The chart's `flink-conf-configmap.yaml` should not use
`| quote` on the s3.* values. Re-render and apply:

```bash
helm template aispm deploy/helm/aispm \
  -f deploy/helm/aispm/values.yaml \
  -f deploy/helm/aispm/values.dev.yaml \
  -f deploy/helm/aispm/values.dev-multinode.yaml \
  --show-only templates/flink-conf-configmap.yaml \
  | kubectl apply -n aispm -f -
kubectl -n aispm delete pod -l app=flink-jobmanager
```

### Pods Pending with "untolerated taint"

kind HA mode applies `node-role.kubernetes.io/control-plane:NoSchedule`
to all nodes by default. We have no workers, so workloads must run on
control-plane nodes. `kind-cluster.sh init` removes the taint, but if
it's been re-applied:

```bash
kubectl taint nodes --all node-role.kubernetes.io/control-plane:NoSchedule-
```

### Sidecars in CrashLoopBackOff after a restore (every aispm pod is `0/2`)

After an etcd restore, kube-proxy's iptables and the CNI's routes can
hold stale entries that point ClusterIPs at no longer-correct pod IPs.
istio sidecars then can't reach `istiod.istio-system:15012` and fail
to obtain workload certs (logs: `i/o timeout` on the istiod ClusterIP).
Without sidecars, every meshed app pod stays `0/2`.

```bash
kubectl -n kube-system rollout restart daemonset kube-proxy kindnet
kubectl -n kube-system rollout status daemonset kube-proxy --timeout=2m
kubectl -n istio-system get endpoints istiod    # should list istiod pod IP
kubectl -n istio-system rollout restart deploy istiod
kubectl -n istio-system rollout status deploy istiod --timeout=2m
kubectl -n aispm rollout restart deploy
kubectl -n aispm rollout restart statefulset
```

After this, pods first transition `0/2` → `1/2` (sidecar healthy, app
still failing for its own reasons), then `2/2` as Postgres replicas
finish WAL streaming and downstream services can connect.

### CNPG failover storm + WAL timeline divergence

Symptom cluster: `kubectl -n aispm get cluster spm-db` shows
`phase: Failing over` even when `currentPrimary == targetPrimary`
(state machine wedged); one pod in permanent CrashLoopBackOff with
postgres logs containing `requested timeline N does not contain
minimum recovery point ... on timeline M`; events show alternating
`FailingOver` / `FailoverTarget` between two replicas every 15-30 min;
`pg_controldata` on each replica returns wildly different
`Latest checkpoint's TimeLineID` values.

Root cause: chronic intermittent probe failures on the CNPG
instance-manager status port (`:8000`) cause CNPG to ping-pong the
primary. Each failover bumps the WAL timeline, and any replica that
was previously a primary gets stranded on a now-dead timeline.
Once divergence exceeds ~3-5 timelines, `pg_rewind` cannot bridge it
and the stranded replica enters permanent CrashLoopBackOff. See the
"Known issues" entry on `failoverDelay` for the underlying trigger
and prevention.

Recovery procedure (data-preserving, ~10-15 min, validated May 2026
when divergence reached TL21 vs TL42):

1.  Freeze the operator to stop the failover loop:
    ```bash
    kubectl -n cnpg-system scale deploy cnpg-controller-manager --replicas=0
    ```
    Wait 60s, then verify `kubectl -n aispm get events | grep FailingOver`
    timestamps stop advancing.

2.  Identify the live primary. The good replica has highest TimeLineID,
    `cluster state: in production`, and `pg_is_in_recovery()=f`:
    ```bash
    for p in $(kubectl -n aispm get pods -l cnpg.io/cluster=spm-db -o name); do
      pod=${p#pod/}
      echo "--- $pod ---"
      kubectl -n aispm exec "$pod" -c postgres -- bash -c \
        'pg_controldata "$PGDATA"' | grep -E 'TimeLineID|cluster state'
      kubectl -n aispm exec "$pod" -c postgres -- psql -U postgres -tAc \
        "SELECT pg_is_in_recovery();" 2>/dev/null
    done
    ```

3.  Take an insurance dump from the primary:
    ```bash
    PRIMARY=spm-db-N    # identified above
    mkdir -p ~/.aispm/db-dumps
    DUMP=~/.aispm/db-dumps/$PRIMARY-rescue-$(date -u +%Y%m%dT%H%M%SZ).sql
    kubectl -n aispm exec "$PRIMARY" -c postgres -- pg_dumpall -U postgres \
      --clean --if-exists > "$DUMP"
    ls -lh "$DUMP" && tail -3 "$DUMP"   # verify "complete" trailer
    ```

4.  Quarantine each divergent replica (NOT the primary). For any replica
    whose `TimeLineID` is below the primary's, delete pod and PVC:
    ```bash
    kubectl -n aispm delete pod spm-db-X --grace-period=0 --force
    kubectl -n aispm delete pvc spm-db-X --wait=false
    # If the PVC hangs in Terminating:
    kubectl -n aispm patch pvc spm-db-X \
      -p '{"metadata":{"finalizers":null}}' --type=merge
    ```
    Replicas that share the primary's TimeLineID and have caught-up
    receive/replay LSNs do NOT need to be deleted.

5.  Wake the operator. It detects missing instances and re-bootstraps
    them via `pg_basebackup` from the primary. CNPG picks the next
    available instance number rather than reusing the deleted one
    (deleted `spm-db-1` returns as `spm-db-4`, etc.):
    ```bash
    kubectl -n cnpg-system scale deploy cnpg-controller-manager --replicas=1
    kubectl -n cnpg-system rollout status deploy cnpg-controller-manager --timeout=120s
    ```

6.  Soak-test 2 min and verify healthy:
    ```bash
    kubectl -n aispm get cluster spm-db
    sleep 120
    kubectl -n aispm get cluster spm-db    # must still say "Cluster in healthy state"
    kubectl -n aispm get pods -l cnpg.io/cluster=spm-db
    kubectl -n aispm get events --sort-by=.lastTimestamp \
      --field-selector involvedObject.kind=Cluster | tail -10
    ```
    Both `get cluster` calls must return `Cluster in healthy state`,
    and no new `FailingOver` events should appear in the 2-min window.

If step 5 immediately re-triggers the failover storm, scale the
operator back to 0 and pivot to nuke-and-rebuild:
`./deploy/scripts/kind-databases-ha.sh down && ./deploy/scripts/kind-databases-ha.sh up`,
then restore the rescue dump.

### Static pod won't restart after manifest edit

Symptom: you moved an `/etc/kubernetes/manifests/*.yaml` aside, then
back, but no new pod container is created. Kubelet's pod cache fell
out of sync with the manifest hash. Restart kubelet inside each kind
node:

```bash
for n in aispm-control-plane aispm-control-plane2 aispm-control-plane3; do
  docker exec "$n" systemctl restart kubelet
done
```

Within ~20 s kubelet re-reads `/etc/kubernetes/manifests/` and creates
fresh static pods.

### Lens shows no metrics

```bash
kubectl -n kube-system rollout status deploy/metrics-server --timeout=120s
kubectl top nodes   # should return CPU / memory rows
```

If `metrics-server` pod is missing, re-run `kind-cluster.sh init` — the
script reinstalls it.

## Recent architectural changes

### HA-only contract: single-instance modes removed (May 2026)

The chart no longer supports any single-instance fallback for stateful
infrastructure or application services.  Specifically:

- `deploy/helm/aispm/templates/spm-db-statefulset.yaml` and
  `redis-statefulset.yaml` were tombstoned (chart-built single-pod
  Postgres / Redis).  CNPG (3-instance Postgres) and the Bitnami HA
  Redis (1 master + 3 replicas + 3 sentinels) installed by
  `kind-databases-ha.sh` are now the only backends.
- `deploy/helm/aispm/templates/spm-db-init-configmap.yaml` was
  tombstoned (raw-SQL bootstrap).  Schema is built exclusively by
  Alembic (`spm/alembic/versions/`) — see the Alembic-canonical
  bootstrap section below.
- `spm/db/migrations/001_initial.sql` was tombstoned for the same
  reason.
- `compose.yml`'s spm-db service block was removed.  Compose is now
  only used for `docker compose build` (image building); `compose up`
  with a full local stack is no longer supported.
- `values.yaml` defaults are HA: `kafka.replicas=3`,
  `kafka.minInsyncReplicas=2`, `flink.jobmanager.replicas=2`,
  `flink.taskmanager.replicas=2`, `redis.replicas=3`.  Never override
  these below their HA-correct values.
- `values.dev.yaml` no longer downgrades these (the old
  single-broker / single-JM workarounds were removed).
- `values.dev-multinode.yaml` no longer needs to re-set HA values
  back up — the defaults already cover it; only environment-specific
  storage class / s3 endpoint overrides remain.
- All 22 application-tier Deployments were bumped from `replicas: 1`
  to `replicas: 2` with topology spread.  Two are intentionally still
  single-replica with explicit SPOF acknowledgment in their template
  comments and tracked follow-ups: `prometheus` (TSDB on RWO PVC,
  needs Thanos sidecar) and `grafana` (SQLite backing store, needs
  CNPG-backed config DB).
- The `api` Service uses `sessionAffinity: ClientIP` to pin
  WebSocket connections to one pod across replicas; tracked
  follow-up to extract WS state to Redis for true HA.
- File deletions are committed as tombstones (file present, content
  is a one-line "removed in May 2026" comment).  Run `git rm` on
  them after the chart change is reviewed:
    - `deploy/helm/aispm/templates/spm-db-statefulset.yaml`
    - `deploy/helm/aispm/templates/spm-db-init-configmap.yaml`
    - `deploy/helm/aispm/templates/redis-statefulset.yaml`
    - `spm/db/migrations/001_initial.sql`

### Alembic-canonical schema bootstrap (May 2026)

Schema evolution is now exclusively driven by Alembic migrations under
`spm/alembic/versions/`.  Three previous bootstrap paths (raw SQL via
init configmap, `Base.metadata.create_all` from spm-api lifespan, raw
SQL via Postgres `/docker-entrypoint-initdb.d/`) collapsed into one:

- `services/spm_api/seed_db.py::ensure_schema()` runs
  `alembic upgrade head` via the programmatic API (in an executor so
  the async caller doesn't block).
- `services/spm_api/app.py` lifespan calls `ensure_schema()` instead
  of `Base.metadata.create_all` directly.
- The chart's db-seed Job runs `python3 /app/seed_db.py`, which calls
  `ensure_schema()` first → alembic.
- The spm-api Docker image now ships the `alembic` Python package
  (`services/spm_api/requirements.txt`) and the `spm/` package
  including `alembic.ini` + `alembic/env.py`.

This eliminates the constraint-drift class of bug that motivated the
posture_snapshots `uq_snapshot` fix — schema is defined in one place
(migrations) and applied identically everywhere.  The runbook's old
"Bootstrap vs Alembic reconciliation" issue is closed.



Stays here so the next person reading this runbook understands non-obvious
design decisions made during incident response. Each section names the
chokepoint code so you can grep without digging.



### CNPG `failoverDelay: 60` to prevent failover storms

CNPG defaults `failoverDelay: 0`, meaning *any* probe failure on the
primary instantly triggers a failover. Combined with intermittent
probe failures on the CNPG instance-manager `:8000` status port
(observed under Docker daemon CPU pressure or WAL replay bursts —
EOF, "tls: unrecognized name", context-deadline), this produces a
ping-pong loop. Each failover bumps the WAL timeline; after ~5 forks
`pg_rewind` cannot bridge the divergence and stranded replicas
CrashLoopBackOff permanently.

`deploy/scripts/kind-databases-ha.sh::_create_pg_cluster()` now sets
`spec.failoverDelay: 60` in the Cluster CR. Any probe blip under 60s
is absorbed; only a sustained primary outage promotes a standby. This
single line is what prevents the 9-hour incident in §"CNPG failover
storm" from recurring.

A live cluster can be patched without a restart:
```bash
kubectl -n aispm patch cluster spm-db --type=merge \
  -p '{"spec":{"failoverDelay":60}}'
```

### `posture_snapshots` unique constraint backfill

The bootstrap SQL (`spm/db/migrations/001_initial.sql`), the Alembic
baseline (`001_initial_baseline.py`), and the chart's init ConfigMap
(`deploy/helm/aispm/templates/spm-db-init-configmap.yaml`) all declared
`UNIQUE NULLS DISTINCT (model_id, tenant_id, snapshot_at)` on
`posture_snapshots`. The SQLAlchemy model in `spm/db/models.py` did
not. When any of the several services that call `Base.metadata.create_all`
(spm-api lifespan, db-seed Job, hydrate-on-import paths) won the race
against the raw SQL bootstrap, the table was created without the
constraint. Result: every `INSERT ... ON CONFLICT (model_id, tenant_id,
snapshot_at) DO UPDATE` in `spm_aggregator.upsert_snapshot` errored
`42P10  there is no unique or exclusion constraint matching the
ON CONFLICT specification`, silently failing every metric rollup.

Fix landed in four places to make the repair stick across every
deploy mode (fresh install, in-place upgrade, kind-databases-ha
re-create, single-node chart, multinode chart):

- `spm/db/models.py` — added `UniqueConstraint("model_id", "tenant_id",
  "snapshot_at", name="uq_snapshot")` to `PostureSnapshot.__table_args__`.
  Future fresh installs that hit `Base.metadata.create_all` first now
  get the constraint regardless of which bootstrap path wins the race.
- `services/spm_api/seed_db.py::ensure_schema()` — added a
  pg_constraint-guarded `ALTER TABLE ... ADD CONSTRAINT uq_snapshot ...`
  inside the same transaction as `create_all`. Self-heals on every
  spm-api boot AND every db-seed Job run, so existing clusters that
  were bootstrapped before the model fix get repaired automatically
  on next deploy. Add new self-healing DDL fixes here as the model
  evolves; always pg_constraint-guard them so re-runs are no-ops.
- `services/spm_api/app.py` lifespan — refactored to call
  `ensure_schema()` instead of calling `create_all` directly, so the
  backfill block runs everywhere `create_all` does.
- `spm/alembic/versions/008_backfill_uq_snapshot.py` — source-of-truth
  Alembic migration with the same DDL. Lands when/if `alembic upgrade
  head` is wired into the bootstrap chain (existing follow-up under
  "Bootstrap vs Alembic reconciliation").

Manual one-shot if needed (the runtime backfill above does this
automatically on next spm-api restart):
```bash
kubectl -n aispm exec $(kubectl -n aispm get pod -l cnpg.io/instanceRole=primary -o name | head -1 | sed 's|^pod/||') \
  -c postgres -- psql -U postgres -d spm -c \
  "ALTER TABLE posture_snapshots ADD CONSTRAINT uq_snapshot UNIQUE NULLS DISTINCT (model_id, tenant_id, snapshot_at);"
```

### Image deployment quirk on kind

``docker push localhost:5001/...:latest`` updates the registry, but
kind's containerd holds the previous ``:latest`` digest in its content
store and reports "Image is up to date" when asked to pull. To force a
real image refresh after pushing, evict the local image first:

```bash
for n in aispm-control-plane aispm-control-plane2 aispm-control-plane3; do
  docker exec $n crictl images | awk '/aispm-<service>/{print $3}' \
    | xargs -r -n1 docker exec $n crictl rmi
  docker exec $n crictl pull localhost:5001/aispm-<service>:latest
done
```

We hit this multiple times during the bug A and Sentinel migrations
when restarted pods kept running stale code despite the registry having
a newer image. Always verify after a rollout:

```bash
kubectl -n aispm get pod -l app=<service> -o jsonpath='{.items[0].status.containerStatuses[0].imageID}'
docker inspect localhost:5001/aispm-<service>:latest --format '{{.Id}}'
```

If the running pod's imageID doesn't match the registry's local image
ID, it's running stale code.

## Known issues (open work)

These are real product/configuration issues observed during the kind
multi-node bring-up. They do not block the cluster from running but
need follow-up before this setup is dependable for security testing.


### Helm probe timeout audit (footgun applied broadly)

The ``timeoutSeconds: 1`` default footgun was hit on kafka and
spm-db this session. Other deployments likely have the same issue;
they just haven't manifested because their kubelet probe load is
lower.

Action items:

- [ ] Audit every helm template for exec / httpGet probes without an
      explicit ``timeoutSeconds``. Add ``timeoutSeconds: 5``
      (and ``failureThreshold: 3`` for parity) wherever missing.
- [ ] Consider chart-level lint that blocks PRs introducing
      unspecified probe timeouts.

### `extract_decoded_payloads` is too permissive

`services/api/models/obfuscation_screen.py::extract_decoded_payloads`
runs the base64 / hex regex over the raw prompt and decodes every
match without applying the same alpha-ratio sanity check that
`screen_obfuscation` uses (`_MIN_B64_DECODED_ALPHA_RATIO = 0.8`).
Result: any 4+ letter alphabetic word can match the base64 regex and
get "decoded" into garbage like `'Z\x16'` or `'歅'`. Each garbage
decode is then re-screened through Llama Guard, which costs an HTTP
round-trip per false positive and exposed the
`test_stream_guard_timeout_fails_closed` regression (May 2026 — fixed
by mirroring the `is_unavailable` mapping into the re-screen branch
of `prompt_security/service.py` and `security/service.py`).

Action items:

- [ ] Apply the same `alpha_ratio >= _MIN_B64_DECODED_ALPHA_RATIO`
      guard inside `extract_decoded_payloads` so benign English text
      doesn't produce decoded payloads. Mirrors the logic already in
      `screen_obfuscation`.
- [ ] Add a unit test asserting that prompts like
      `"What is the weather forecast for tomorrow?"` and
      `"Please process this construction order"` produce
      `extract_decoded_payloads(...) == []`.
- [ ] Consider raising `_MIN_B64_BYTES` from 4 to 6 for the extract
      path — anything below 6 chars is effectively never a real
      base64 payload (and is hugely overrepresented by short
      English words).

### `install-gvisor.sh` only patches the host VM, not each kind node

The Job-based installer mounts the **host VM**'s `/etc/containerd` via
`hostPath` and chroots in.  But kind nodes are containers running
*inside* that VM with their own filesystems and their own containerd
instances; the host-VM chroot never reaches them.  Today: only
`aispm-control-plane2` had `runsc` installed (mechanism unknown — likely
a manual run); the other two nodes silently lacked it.  Custom-agent
pods scheduled to the unpatched nodes failed sandbox-create with:

    failed to get sandbox runtime: no runtime for "runsc" is configured

Manual recovery was a `docker cp` loop pushing `runsc`,
`containerd-shim-runsc-v1`, and `runsc.toml` into each missing node,
then appending the `runtimes.runsc` block to the node's
`/etc/containerd/config.toml` and restarting containerd.

Action items:

- [x] Refactor `deploy/scripts/install-gvisor.sh` to enumerate kind
      nodes (`docker ps --filter label=io.x-k8s.kind.role`) and `docker
      exec` the binary install + config patch into each one.
- [ ] Add an idempotency check that re-runs of the script on a fully
      patched cluster are zero-write (verify `runsc` already present,
      `runtimes.runsc` already in config).
- [ ] CI smoke test: `kubectl apply -f` a pod with
      `runtimeClassName: gvisor` + `nodeSelector` for every node, assert
      all reach Running.

### Istio sidecar probe-rewrite race on slow-starting apps

When a sidecar-injected pod has a kubelet probe, Istio rewrites the
probe to go through `pilot-agent`'s status port (`:15020`), which
proxies to the actual app port (e.g. CNPG instance-manager `:8000`,
Flink JM `:8081`, OPA `:8181`).  If the app takes longer than the
probe's `failureThreshold * periodSeconds` window to bind that port,
every probe in the startup window 503s, kubelet kills the pod, the new
pod hits the same window — a crashloop the pod can never out-pace.
Documented victims this session:

- CNPG (spm-db-{1,2,3}): 96, 64, 75 restarts in 43h
- Flink JobManager: 9 restarts in 5h
- Flink TaskManager: silent restarts whenever JMs flapped
- OPA: probe-rewrite errors during the istiod restart cascade

The cluster-wide fix would be `holdApplicationUntilProxyStarts: true` in
the mesh `MeshConfig`, which makes apps wait for the sidecar before
their own probes run.  Until that's enabled cluster-wide, the local
escape hatch is `sidecar.istio.io/inject: "false"` on the affected
pod's annotations — already applied in this chart for kafka, redis,
spm-db (legacy), Flink JM, Flink TM, OPA, and the CNPG Cluster CR
(via `inheritedMetadata` in `kind-databases-ha.sh`).  Apps that talk
TO these services stay in the mesh and reach them via ClusterIP fine —
only the stateful pods themselves are exempt.

Action items:

- [ ] Enable `holdApplicationUntilProxyStarts: true` in the mesh
      `MeshConfig` so future stateful infra doesn't need a per-pod
      exemption.
- [x] Document the exemption pattern in chart templates so a future
      contributor adding (say) Elasticsearch or ClickHouse knows to
      apply the same annotation.
- [ ] Audit policy-simulator, threat-hunting-agent, agent-orchestrator,
      grafana, prometheus — any service the events log shows hitting
      `:15020/app-health/...readyz context deadline exceeded` regularly
      may need the exemption too.

### Headless-service HA bootstrap needs `publishNotReadyAddresses: true`

CoreDNS by default only publishes EndpointSlice members whose pod is
`Ready=true`.  But for any HA cluster that bootstraps via per-pod DNS
(StatefulSet pods discovering peers by name), there's a chicken-and-egg
window: pod-0 needs pod-1's IP to bootstrap → pod-1 isn't Ready yet
because it's also bootstrapping → DNS returns NXDOMAIN for both →
deadlock.  Fixes itself eventually if the bootstrap retry loop
out-paces the readiness probe, but during incident recovery (everyone
bouncing simultaneously) the loop loses and one or both pods sit in
permanent `UnknownHostException`.

Today: Flink JobManager hit this with `java.net.UnknownHostException:
flink-jobmanager-1.flink-jobmanager.aispm.svc.cluster.local`.  Same
fix-pattern as the Kafka KRaft quorum (already in the chart):
`publishNotReadyAddresses: true` on the headless service.  Cost is
purely cosmetic — external clients hitting the ClusterIP may briefly
hit a NotReady pod, but HA-cluster-aware clients (Pekko, KRaft
Raft) handle that fine.

Action items:

- [x] `flink-jobmanager` service — added in this session.
- [ ] Audit every other headless service backing a StatefulSet
      (`kafka` already has it).  Check Redis Sentinel's headless
      service if/when we move to a real StatefulSet.

### Redis Sentinel probe `timeoutSeconds: 1` is too aggressive

`redis-node-{0,1,2}` accumulated 18 / 9 / 13 sentinel-container
restarts (the third container, name `sentinel`) over the cluster's 44h
lifetime.  The probe is a shell exec
(`/bin/bash -ec /health/ping_sentinel.sh 1`) with
`timeoutSeconds: 1` — every probe forks bash + the redis-cli
inside the script, which under any kind of CPU contention exceeds 1s.
Same class of footgun as the Kafka `kafka-broker-api-versions` exec
probe we lengthened earlier this session (5s now, was 1s).

Pods stay Ready because the failureThreshold is high enough to absorb
intermittent timeouts, but the restart counter ticks up every time a
probe loses against contention — masking real degradations and
scaring operators who see double-digit RESTARTS during incident
review.

Action items:

- [x] Bump `timeoutSeconds` to 5 on the Bitnami Redis Sentinel
      readiness/liveness probes.  Knob is at
      `sentinel.livenessProbe.timeoutSeconds` and
      `sentinel.readinessProbe.timeoutSeconds` in the Bitnami chart.
- [x] Apply via `--set` flag in
      `deploy/scripts/kind-databases-ha.sh::_install_redis_ha()` so the
      bump is captured in source, not just one operator's helm
      install command.  (Same `--set` for `master`/`replica` probes.)
- [ ] Existing live cluster: the bump only affects new pods.  After
      this change lands, run `kubectl -n aispm-data delete pod -l app.kubernetes.io/name=redis` to recycle the existing pods so they pick up the new timeout.

### Bootstrap vs Alembic reconciliation — RESOLVED (May 2026)

Closed: see "Alembic-canonical schema bootstrap (May 2026)" under
"Recent architectural changes".  The raw-SQL `001_initial.sql` and
`spm-db-init-configmap.yaml` paths were tombstoned; every code path
now goes through `alembic upgrade head` via
`services/spm_api/seed_db.py::ensure_schema()`.

## What's NOT installed (and why)

- **Longhorn / Rook-Ceph / SeaweedFS-CSI** — kernel modules they need
  (`iscsi_tcp`, `rbd`, `nfsd`) are absent or stripped from Docker
  Desktop's LinuxKit kernel. Application-level replication makes them
  unnecessary anyway.
- **Falco** — chart-pinned 0.42.x has a container-plugin schema bug
  on arm64 / Ubuntu 24.04. Tetragon already enforces the runtime-
  security TracingPolicies AISPM cares about.
- **Kyverno** — admission-webhook lifecycle is brittle on this cluster
  and not load-bearing for dev. `SKIP_KYVERNO=1` in the bootstrap.

Re-enable any of these in `values.dev-multinode.yaml` if/when the
upstream issues are resolved.
