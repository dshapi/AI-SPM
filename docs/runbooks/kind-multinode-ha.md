# Multi-node HA Cluster (kind on Docker Desktop) — Runbook

This is the operational manual for the 3-node kind cluster that AISPM
runs on locally. Every stateful layer is HA via application-level
replication; storage is local-path because no FUSE/iSCSI/RBD-based CSI
driver works reliably on Docker Desktop's LinuxKit kernel — and we
don't need replicated block storage anyway, since CNPG, Redis Sentinel,
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
| `deploy/scripts/kind-storage.sh`                | MinIO install + flink bucket                  |
| `deploy/scripts/kind-databases-ha.sh`           | CNPG operator + Postgres Cluster + Bitnami Redis |
| `deploy/helm/aispm/values.dev-multinode.yaml`   | Chart overrides for this cluster              |

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

Docker Desktop restart sometimes stops the kind external load balancer.

```bash
docker ps -a --filter label=io.x-k8s.kind.cluster=aispm
docker start aispm-external-load-balancer
```

If etcd peer certs are out of sync after a long Docker Desktop outage
(symptom: `etcd-aispm-control-plane` CrashLoopBackOff with "bad
certificate" errors), the fastest path is `./deploy/scripts/kind-cluster.sh
destroy && init`. State on application-level replicas is reseeded on
re-bootstrap.

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

### Lens shows no metrics

```bash
kubectl -n kube-system rollout status deploy/metrics-server --timeout=120s
kubectl top nodes   # should return CPU / memory rows
```

If `metrics-server` pod is missing, re-run `kind-cluster.sh init` — the
script reinstalls it.

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
