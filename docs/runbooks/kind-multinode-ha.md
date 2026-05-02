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
Docker Desktop restart, the LB container's host port may differ from
what your kubeconfig expects. The `networking.apiServerPort: 6443` pin
in `kind-cluster.sh` prevents this on new clusters; if the cluster
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

Stays here so the next person reading this runbook understands non-obvious
design decisions made during incident response. Each section names the
chokepoint code so you can grep without digging.



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

### Bootstrap vs Alembic reconciliation

Fresh installs apply ``spm/db/migrations/001_initial.sql`` to
bootstrap the schema, then never run the Alembic migration chain.
Migrations after 001 (e.g. ``002_add_session_id_to_audit_export``)
exist and are correct, but a fresh cluster starts in the post-001
state — missing every column added by 002+. The
threat-hunting-agent's ``session_id`` failure was the visible
symptom; there are likely more silent ones.

Action items:

- [ ] Either backport every Alembic migration into ``001_initial.sql``
      (single source of truth at bootstrap time), or
- [ ] Make the bootstrap path always run ``alembic upgrade head``
      after applying 001 (preserves migration history).
- [ ] Add a CI check that ``alembic upgrade head`` from a freshly
      bootstrapped DB is a no-op — proves 001 + Alembic are aligned.

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
