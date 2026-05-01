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

### Tool execution policy gate (bug A)

Every tool call Claude requests goes through a single chokepoint:
``services/api/app.py:_execute_tool_with_policy``. That function queries
OPA at ``/v1/data/spm/tools/allow`` (rules in
``opa/policies/tool_policy.rego``) before executing the tool, and
returns a "[Tool blocked by policy: …]" string back to the model when
the policy denies. Three call sites all use this helper: ``/chat``,
``/chat/stream``, ``/internal/probe``. Adding a new tool means: define
it in ``_TOOLS`` (production) and ``_TEST_TOOLS`` (garak), and add
``allow`` rules in ``tool_policy.rego``. **Never bypass the chokepoint**
— previous design let tool calls run unconditionally, which is how the
``tooluse`` probe scored 90 (total bypass) before the fix.

### Encoding-bypass screening (bug F)

Prompts are screened in 4 layers:
``Normalizer → LexicalScanner → LlamaGuard → OPA``. A new step between
LexicalScanner and LlamaGuard extracts decoded payloads (Base64, hex,
ROT13) via
``services/api/models/obfuscation_screen.py:extract_decoded_payloads``.
Each decoded payload is **re-screened through Llama Guard** so novel
phrasing in encoded payloads gets caught by the same content classifier
that screens the raw prompt. When encoding is detected (and the inner
content passes guard), an ``"obfuscation"`` signal is appended to
``guard_categories``; ``opa/policies/prompt_policy.rego`` has a rule
that escalates this signal to block when ``guard_score >= 0.30``,
unless the auth context has scope ``prompts:encoded_allowed``. Benign
short Base64 (e.g. ``"RG9nYW4="`` = "Dogan") passes through cleanly —
no false positives.

### Redis: Sentinel-aware clients (haproxy proxy bypassed)

Services no longer connect through the ``redis-master`` Service /
``redis-master-proxy`` haproxy pods. The proxy was flapping under
istio sidecar pooling (high-frequency tcp-checks tripping ECONNRESET
mid-handshake). The fix moves master-discovery into the application
clients themselves via Redis Sentinel.

Single source of truth: ``platform_shared/redis.py:get_redis_client()``.
Reads ``REDIS_SENTINEL_HOSTS`` (comma-separated list of all 3 sentinel
endpoints, set by the platform-env configmap) and
``REDIS_SENTINEL_MASTER`` (``"mymaster"``). Falls back to direct
``REDIS_HOST:REDIS_PORT`` when sentinel hosts are unset (single-node
dev). Every service's local ``_get_redis()`` now delegates to this
helper. The haproxy proxy is still deployed but **dead code in the data
path** — pending cleanup (see Known Issues below).

### Topic registry expansion + reconciliation

Kafka topics are owned by ``platform_shared/topics.py``. The
startup-orchestrator creates them all on boot with RF derived from
``KAFKA_REPLICATION_FACTOR`` and reconciles drift on existing topics.
RF mismatches are logged as warnings (operator runs
``deploy/scripts/kafka-reconcile-topics.sh``); retention / cleanup
policy drift is auto-fixed via ``alter_configs``. Per-agent topics
(``cpm.t1.agents.<UUID>.chat.{in,out}``) are created by
``services/spm_api/agent_controller.py:create_agent_topics`` which now
reads RF / partitions from env (previously hardcoded RF=1).

### Probe timeout pattern

Bitnami's pg/redis charts default ``timeoutSeconds: 1`` on liveness/
readiness probes. On kind-on-Mac that's too tight — the underlying
exec routinely takes 2–3s, kubelet false-fails the probe and kills
the pod, every dependent service sees connection drops. The pattern
applied to kafka and spm-db is ``timeoutSeconds: 5``. Audit all helm
probes for this footgun (see Known Issues below).

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

### Garak Simulation Lab — partial coverage

Symptoms when running the **Full Kill Chain** profile from the UI:

- Most probes complete with all attempts marked **ALLOWED**.
- One probe (typically `dataexfil`) finishes with **ERROR / 1 attempt**
  while others run their 10 attempts cleanly.
- A re-run after auth fixes (see "AuthorizationPolicy" in
  Troubleshooting) yields a more realistic 5 blocked / 6 passed across
  the kill-chain probes — the chain *is* evaluating, but the verdict
  distribution suggests the guard policies catch obvious attacks and
  miss subtler ones.

What we know:

- The earlier "all ALLOWED" runs were Garak using its synthetic
  **Blank** generator instead of the real AISPM target — a missing
  `GARAK_INTERNAL_SECRET` in `platform-secrets`. Bootstrap should
  auto-generate it; on this kind cluster it landed empty. Workaround
  is in Troubleshooting.
- The `dataexfil` probe ERROR is reproducible and may indicate a
  specific upstream-API contract issue worth investigating
  separately.

Action items (not done):

- [ ] Bootstrap should fail loudly if `GARAK_INTERNAL_SECRET` ends up
      empty rather than letting the simulator silently fall back to
      Blank.
- [ ] Investigate why `dataexfil` errors while other probes complete.
- [ ] Tune `GUARD_BLOCK_SCORE` and / or improve the guard prompt to
      raise block rate on the subtler probes.

### Custom agents do not block jailbreak attempts

When you run a chat through a custom agent created via the Agents
admin UI, jailbreak prompts that the platform-level guard chain
*should* catch (prompt injection, ignore-previous-instructions, etc.)
make it to the LLM and produce a response.

Suspected causes (none confirmed yet):

- Custom-agent runtime may bypass the guard chain entirely and call
  the LLM proxy directly.
- Or the per-agent policy attached to the custom agent doesn't include
  the prompt-injection rule that the simulator-style flow has.

Action items (not done):

- [ ] Trace a single custom-agent request end-to-end — confirm
      whether `guard-model` is invoked.
- [ ] If not, fix the agent runtime to route through `guard-model` /
      `output-guard` like the platform chat path does.
- [ ] Add a regression test (Garak probe) that fails if a known
      prompt-injection slips through a custom agent.

### Simulator UI: "Simulation timeout — no terminal event received"

After the Garak run finishes successfully on the backend (probes
return verdicts in api logs), the UI sometimes shows a banner:
"Simulation timeout — no terminal event received from the backend."

The terminal event is delivered over the WebSocket
`/ws/sessions/<session-id>`. Likely culprits:

- ingress-nginx WebSocket idle timeout. Default is 60s; long Garak
  runs exceed that without an in-band keepalive.
- istio sidecar idle timeout closing the upstream WS before the
  terminal event reaches the UI.
- The api side never emits the terminal frame on this code path.

Action items (not done):

- [ ] Add `nginx.ingress.kubernetes.io/proxy-read-timeout: "600"` and
      `proxy-send-timeout: "600"` to the AISPM Ingress to extend WS
      lifetime past 60s.
- [ ] Confirm api emits `{"type":"terminal", ...}` on simulation
      completion — if not, fix the simulator service.
- [ ] Add a server-side keepalive ping every 20s to keep ingress
      proxies happy.

### Custom agent disappears from the agents table

After creating a custom agent and using it once, it sometimes
vanishes from the Agents admin UI table on the next page load, even
though the underlying record is presumably still in `spm-db`.

Suspected causes:

- API GET /agents may filter by a status field the runtime no longer
  satisfies.
- The agent-orchestrator may be deleting/garbage-collecting agents
  whose runtime container has terminated.

Action items (not done):

- [ ] Reproduce reliably and capture the timing.
- [ ] Check the spm-api `/agents` query and see whether it excludes
      the row.
- [ ] If the row is intact, this is a UI bug — the table fetch
      response is dropping it client-side.

### threat-hunting-agent: register as system agent *(DONE)*

The threat-hunting-agent is a platform service that calls
spm-llm-proxy (which validates bearer tokens against
``agents.llm_api_key``). Originally it sent the placeholder string
``"local"`` (left over from an OrbStack-era Ollama setup that didn't
require auth) — every LLM call returned 401 ``Unknown llm_api_key``.

Architectural fix: register the agent as a first-class **system
agent** so it has a real row in ``agents`` (visible in the inventory)
and gets a real ``llm_api_key`` like any customer agent. Sets the
precedent for future platform services that need spm-llm-proxy.

Single source of truth pattern (DB and Deployment always agree):

```
helm value secrets.threatHuntingAgentLlmKey
        ↓ (rendered into)
platform-secrets.THREAT_HUNTING_AGENT_LLM_KEY  (k8s Secret)
        ↓ (mounted as env)        ↓ (mounted as env)
threat-hunting-agent      spm-api → seed_db.py
   AGENT_LLM_API_KEY                seed_system_agents()
        ↓                                    ↓
   Bearer token sent                agents.llm_api_key (DB row)
        ↓
   spm-llm-proxy._auth_required → resolve_agent_by_llm_token
                                          ↓
                                    matches → 200 OK
```

What changed:

- [x] ``services/spm_api/seed_db.py`` — new ``seed_system_agents()``
      function. Reads ``THREAT_HUNTING_AGENT_LLM_KEY`` env, inserts or
      reconciles ``agents`` row for ``threat-hunting-agent``
      (kind=system via ``owner=platform``, ``provider=internal``).
      Idempotent; rotates token if value changes.
- [x] ``deploy/helm/aispm/templates/secrets.yaml`` — added
      ``THREAT_HUNTING_AGENT_LLM_KEY`` field, sourced from
      ``.Values.secrets.threatHuntingAgentLlmKey``.
- [x] ``deploy/helm/aispm/values.yaml`` — new top-level value
      ``secrets.threatHuntingAgentLlmKey`` with operator docstring.
- [x] ``deploy/helm/aispm/templates/threat-hunting-agent-deployment.yaml``
      now reads ``AGENT_LLM_API_KEY`` from ``platform-secrets``
      (was ``threat-hunting-agent-creds``; that standalone Secret
      can be deleted post-migration).
- [x] Verified end-to-end: ``200 OK`` from spm-llm-proxy via the
      threat-hunting-agent's bearer token; Ollama responds via the
      proxy; no 401s in agent logs. Subsequent hunt cycles complete
      successfully and persist findings.
- [x] Added ``kind`` enum column on ``agents`` (``customer`` /
      ``system``) plus migration via direct SQL on the live cluster;
      SQLAlchemy model in ``spm/db/models.py`` updated with new
      ``AgentKind`` enum.
- [x] API serializer ``_to_dict()`` exposes ``kind`` in the public
      response (defaults to ``customer`` for legacy rows).
- [x] Admin UI renders a "System" badge on the row, disables the
      Open Chat button, and replaces Run/Stop/Delete with a
      "Lifecycle managed by Kubernetes" note for system agents.
      View Detail and Apply Policy stay available — OPA policies
      still apply to the agent's LLM calls.
- [x] Renamed the agent's display name to ``Threat-Hunting-Agent``
      (the K8s Deployment stays lowercase; spm-llm-proxy lookups use
      ``llm_api_key`` so the rename is operationally inert).

Operator workflow on a fresh install:

```bash
# 1. Generate the token once
TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

# 2. Pass to helm (or set in values.dev-multinode.yaml)
helm template aispm deploy/helm/aispm -n aispm \
  -f deploy/helm/aispm/values.yaml \
  -f deploy/helm/aispm/values.dev-multinode.yaml \
  --set secrets.threatHuntingAgentLlmKey="$TOKEN" \
  | kubectl apply -n aispm -f -

# 3. The db-seed Job runs seed_system_agents(); the threat-hunting
#    deployment reads the same token from platform-secrets. Both
#    sides agree without coordination.
```

To rotate: change the helm value, re-render, re-apply, re-run db-seed.
The deployment picks up the new env on its next pod restart.

### threat-hunting-agent LLM URL pinned to OrbStack hostname *(DONE)*

The agent's reasoning LLM client was failing every call with
``httpcore.ConnectError: [Errno -2] Name or service not known``.

Root cause: ``services/threat-hunting-agent/config.py:18`` had
``GROQ_BASE_URL = "http://host.lima.internal:11434/v1"`` hardcoded
as a module-level constant — left over from when the team ran
Ollama on the host via OrbStack k8s. The original comment even
explained it was "intentionally NOT exposed as env-configurable…
so stale shell exports cannot override them." That intent was
correct for OrbStack but wrong on Docker Desktop kind, where
``host.lima.internal`` doesn't resolve from inside pods. Despite
the deployment setting ``AGENT_LLM_BASE_URL`` in env, the constant
was never read from env and always pointed at the dead host.

Fix: read from env with the correct in-cluster default.

- [x] ``GROQ_BASE_URL`` and ``HUNT_MODEL`` now read from env
      (``AGENT_LLM_BASE_URL``, ``HUNT_MODEL``) with default
      ``http://spm-llm-proxy.aispm.svc.cluster.local:8500/v1``.
      Variable name kept as ``GROQ_BASE_URL`` for import compat.
- [x] Verified post-restart: agent logs
      ``base_url=http://spm-llm-proxy.aispm.svc.cluster.local:8500/v1``,
      no more DNS-failure traces.

### threat-hunting-agent collectors: column "session_id" does not exist *(DONE)*

Five collectors (``runtime_collector._check_enforcement_block_clusters``,
``runtime_collector._check_session_storm``,
``prompt_secrets_collector``, ``data_leakage_collector``,
``tool_misuse_collector._check_rapid_chaining``) failed every cycle
with ``column "session_id" does not exist`` on the ``audit_export``
table.

Root cause: the cluster was bootstrapped from
``spm/db/migrations/001_initial.sql`` which predates ``session_id``
and creates ``audit_export`` without it. The Alembic migration
``002_add_session_id_to_audit_export.py`` exists and would add
the column + index, but **was never executed** on this cluster
because the bootstrap path used raw SQL instead of Alembic. The
SQLAlchemy model in ``spm/db/models.py`` already declares the
column (line 163), and the ``spm_aggregator`` writer already passes
``session_id`` in its INSERT (with a graceful fallback that strips
the column on legacy schemas). Schema-vs-model drift, nothing more.

Fix: ran the migration's logic as direct SQL on the live cluster:

```sql
DO $$
BEGIN
    ALTER TABLE audit_export ADD COLUMN session_id VARCHAR(64);
EXCEPTION
    WHEN duplicate_column THEN NULL;
END
$$;
CREATE INDEX IF NOT EXISTS idx_audit_export_session_id
    ON audit_export (session_id);
```

Existing rows have ``session_id=NULL`` (fine — collectors that
``GROUP BY session_id`` just return zero rows from those rows; no
backfill needed). New rows from spm-aggregator populate it.

- [x] Column + index added to live cluster.
- [x] Verified collectors no longer emit
      ``column "session_id" does not exist`` warnings.
- [ ] Reconcile the bootstrap path: either make
      ``001_initial.sql`` include session_id, or always run Alembic
      after the raw SQL on fresh installs. Current state means
      every fresh install hits this same bug. Add an action item
      under "Helm probe-timeout audit" to also audit
      ``001_initial.sql`` vs the Alembic chain for missing
      migrations.

### Flink HA leader election broken after etcd restore *(DONE)*

After the etcd restore, both ``flink-jobmanager-0`` and
``flink-jobmanager-1`` showed ``1/2`` Ready, ``/overview`` on port
8081 hung, logs spammed
``AskTimeoutException: Recipient ... had already been terminated``.

Root cause: the K8s ConfigMap that holds Flink's leader lease
(``aispm-flink-cluster-config-map``) had a stale
``control-plane.alpha.kubernetes.io/leader`` annotation pointing at
a ``holderIdentity`` UUID belonging to a pod that no longer existed
(from before the etcd restore). Both new JMs saw the stale lease,
each tried to take over, neither succeeded — the dispatcher actor
got terminated mid-election and ``/overview`` blocked forever
waiting on a dead actor.

Recovery procedure (committed pattern):

```bash
# 1. Cold-stop both JMs to break the race
kubectl -n aispm scale statefulset flink-jobmanager --replicas=0
kubectl -n aispm wait --for=delete pod/flink-jobmanager-0 --timeout=60s

# 2. Wipe the stale lease ConfigMap — Flink HA recreates on JM startup
kubectl -n aispm delete cm aispm-flink-cluster-config-map

# 3. Bring up ONE JM only — no race possible, fresh lease
kubectl -n aispm scale statefulset flink-jobmanager --replicas=1
kubectl -n aispm rollout status statefulset/flink-jobmanager --timeout=3m

# 4. Verify leader annotation is fresh and /overview responds
kubectl -n aispm describe cm aispm-flink-cluster-config-map | grep -A2 Annotations
kubectl -n aispm exec flink-jobmanager-0 -c flink-jobmanager -- \
  curl -s http://localhost:8081/overview

# 5. Scale to 2 — JM-1 sees JM-0's lease, joins as standby cleanly
kubectl -n aispm scale statefulset flink-jobmanager --replicas=2
kubectl -n aispm rollout status statefulset/flink-jobmanager --timeout=3m
```

Why this and NOT a rolling restart: a rolling restart bounces JMs
one at a time but leaves the stale lease intact and lets both new
JMs race. The "scale to 0 → wipe configmap → scale to 1 → scale to 2"
sequence forces a deterministic single-leader cold start.

- [x] Recovery procedure documented above and tested.
- [x] Cluster recovered: 2 JMs, 2 TMs, 6 slots available.

### CNPG cluster (spm-db-1/2/3) — high restart counts *(DONE — false alarm)*

Initial hypothesis: same probe-timeout footgun as the standalone
``spm-db`` StatefulSet. **Wrong.**

Investigation:

- The pods' actual probe spec uses ``timeoutSeconds: 5`` (CNPG
  operator default), routed through istio's app-health proxy at
  port 15020 (``/app-health/postgres/{livez,readyz}``).
- ``previous`` logs from the most recent restart show a clean
  graceful shutdown: ``postmaster exited`` with
  ``postmasterExitStatus: null``, instance-manager waiting for
  caches/webhooks/HTTP servers, ``pg_controldata`` reporting
  ``shut down in recovery`` (clean on-disk state).

Actual cause: the high restart counts (13–18) accumulated **during**
yesterday's etcd recovery — the standalone primary ``spm-db-0`` was
itself cycling (probe-timeout footgun, fixed separately), so the
CNPG replicas kept trying to attach to a primary that wasn't there.
Each failed-sync cycle counted as a restart. Once the standalone
primary stabilized, replica restarts dropped to noise level (2 in
18 hours, indistinguishable from CNPG's normal reconciliation).

- [x] Confirmed CNPG probes are not the cause; no fix needed.
- [x] Future reference: high restart counts on CNPG instances are
      most often downstream of the primary's health, not the
      replicas' own probes. Diagnose by checking the primary first.

### spm-api 401 on model registration during startup

The startup-orchestrator's "register CPM models" step fails 20/20
attempts with ``spm-api returned 401 for llama-guard-3``. Result:
Llama-Guard-3 is unregistered after every boot, and the SPM admin UI
shows no models.

Suspected causes:

- Internal-token mismatch between orchestrator and spm-api
  (``platform-secrets`` got rotated post-recovery and orchestrator's
  cached token went stale).
- spm-api's ``/internal/models`` endpoint uses a different auth
  scheme than orchestrator is sending.

Action items:

- [ ] Capture the actual 401 response body — identifies which auth
      scheme is being rejected.
- [ ] If token-rotation, restart orchestrator AFTER the secret rotates
      (or have it re-read on every attempt).
- [ ] Add a startup-orchestrator integration test that catches model
      registration regressions.

### Kafka leader rebalance *(DONE)*

After yesterday's partition reassignment to RF=3, every partition's
leader landed on broker 0 (74 / 6 / 6 distribution). Cause: the
reassignment script set replicas as ``[0,1,2]`` for every partition,
making broker 0 the *preferred* leader for everything. Running
``kafka-leader-election --election-type preferred`` alone wouldn't
redistribute — it picks the FIRST replica in the list, which was 0
everywhere.

Fix: rotate the replica order per partition (partition 0 →
``[0,1,2]``, partition 1 → ``[1,2,0]``, partition 2 → ``[2,0,1]``)
via a one-shot reassignment, then run preferred-leader-election. The
reassignment is metadata-only since the replica *set* doesn't change,
only the order — fast and zero data movement.

Recovery procedure (committed pattern):

```bash
# 1. Generate rotated reassignment JSON inside kafka-0
kubectl -n aispm exec kafka-0 -- bash -c '
TOPICS=$(/usr/bin/kafka-topics --bootstrap-server localhost:9092 --list --exclude-internal)
echo "{ \"version\": 1, \"partitions\": ["
FIRST=1
for t in $TOPICS; do
  desc=$(/usr/bin/kafka-topics --bootstrap-server localhost:9092 --describe --topic "$t" 2>/dev/null)
  parts=$(printf "%s\n" "$desc" | awk "/PartitionCount:/ { for (i=1;i<=NF;i++) if (\$i==\"PartitionCount:\") { print \$(i+1); exit } }")
  rf=$(printf "%s\n" "$desc"   | awk "/ReplicationFactor:/ { for (i=1;i<=NF;i++) if (\$i==\"ReplicationFactor:\") { print \$(i+1); exit } }")
  [ -z "$parts" ] && continue
  [ "$rf" -lt 3 ] && continue
  for p in $(seq 0 $((parts - 1))); do
    a=$((p % 3)); b=$(((p + 1) % 3)); c=$(((p + 2) % 3))
    [ $FIRST -eq 0 ] && echo ","
    FIRST=0
    printf "  {\"topic\": \"%s\", \"partition\": %d, \"replicas\": [%d, %d, %d]}" "$t" "$p" $a $b $c
  done
done
echo
echo "] }"
' > /tmp/aispm-rebalance.json

# 2. Apply the reassignment + run preferred-leader-election
kubectl -n aispm cp /tmp/aispm-rebalance.json kafka-0:/tmp/aispm-rebalance.json
kubectl -n aispm exec kafka-0 -- /usr/bin/kafka-reassign-partitions \
  --bootstrap-server localhost:9092 \
  --reassignment-json-file /tmp/aispm-rebalance.json --execute
sleep 5
kubectl -n aispm exec kafka-0 -- /usr/bin/kafka-leader-election \
  --bootstrap-server localhost:9092 \
  --election-type preferred --all-topic-partitions

# 3. Verify even distribution (~28-30 per broker)
kubectl -n aispm exec kafka-0 -- /usr/bin/kafka-topics \
  --bootstrap-server localhost:9092 --describe --exclude-internal \
  | grep "Leader:" | awk '{print $6}' | sort | uniq -c
```

Result: distribution went from 74-6-6 → 30-28-28. The 2-extra on
broker 0 is from two single-partition topics
(per-agent ``chat.in``/``chat.out``) that can't rotate.

- [x] One-shot rebalance executed; verified 30-28-28 distribution.
- [x] Updated ``deploy/scripts/kafka-reconcile-topics.sh`` to rotate
      replicas by partition index (partition P → preferred leader
      P mod num_brokers). Future reconcile runs produce balanced
      leadership from the start; no follow-up election needed.

### Garak `encoding.InjectBase64` probe noise

The probe's success criterion is "did the model decode any Base64?"
That's overly broad — benign decodes (e.g. ``"RG9nYW4="`` → "Dogan")
get scored as defense-bypassed even though no harmful content was
involved. After bug F (Layer 2.5 Llama-Guard re-screen) the actual
security gap is fixed; the residual score on this probe is mostly
false-positive noise.

Action items:

- [ ] Tune the probe's detector or replace with a custom probe that
      scores only on harmful decoded content.
- [ ] Document the noise in the simulation results UI so reviewers
      don't flag it as a real failure.

### redis-allow-platform AuthorizationPolicy is a no-op

Found while debugging redis flakiness — the AuthorizationPolicy
``redis-allow-platform`` selects ``app: redis``, but Bitnami's redis
chart labels pods with ``app.kubernetes.io/name: redis``. The
selector matches nothing, so the policy is dead. Nothing in istio
currently enforces who can talk to the platform redis.

Action items:

- [ ] Update the policy's selector to
      ``app.kubernetes.io/name: redis``.
- [ ] Apply same audit to other AuthorizationPolicies in the chart;
      Bitnami pods consistently use the ``app.kubernetes.io/*``
      labels and the chart's policies often use ``app: <name>``.

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

### Cleanup: dead haproxy redis-master proxy *(DONE)*

After the Sentinel-aware client migration, the ``redis-master-proxy``
Deployment + ``redis-master`` Service were dead code in the data path
and have been removed.

- [x] Removed the ``redis-master-proxy`` Deployment + ``redis-master``
      Service block from ``deploy/scripts/kind-databases-ha.sh``;
      replaced with a comment block documenting why no proxy is needed
      (clients use Sentinel via ``platform_shared/redis.py``).
- [x] Verified no service still references
      ``redis-master.aispm.svc.cluster.local`` — the only redis access
      path is now ``get_redis_client()``.
- [x] Deleted ``redis-haproxy-cfg`` ConfigMap, ``redis-master-proxy``
      Deployment, and ``redis-master`` Service from the cluster.

### Policy editor: accept Rego, not Python

The admin-UI policy editor currently lets users author policies in
Python (or a Python-flavored DSL). That's a layer of indirection on
top of what OPA actually evaluates — all enforcement runs against
``.rego`` files in ``opa/policies/``. Users edit Python, something
translates / executes it, OPA never sees the user's intent in its
native form. Means: drift between editor preview and live behavior,
rules that don't compose with our other ``allow``/``has_signal``
helpers, and a worse experience for anyone who knows Rego.

Direction: switch the editor to a Rego authoring surface (Monaco with
``rego`` syntax mode, in-browser ``opa eval`` for live preview,
server-side validation by uploading to OPA before save). The editor
should also show the existing platform rules read-only as references
(prompt_policy.rego, tool_policy.rego, output_policy.rego) so users
extend rather than reinvent.

Action items:

- [ ] Audit current editor: where is "Python" rendered? Find the
      compiler / executor and document the indirection.
- [ ] Add ``rego`` Monaco language mode to the UI editor.
- [ ] Server-side: validate rego on save via
      ``opa parse`` / ``opa eval`` before accepting; reject syntax
      errors with line/column-pointed messages.
- [ ] Migration: keep Python authoring read-only for existing
      user-authored policies (or auto-translate when round-trip is
      faithful); new policies are Rego-only.
- [ ] Surface the platform-shipped policies as inline references in
      the editor so users see the existing helpers
      (``has_signal``, ``has_scope``, ``has_behavioral``) and the
      ``allow := { decision, reason, action }`` shape.

### Connector card description drift *(DONE)*

The Redis integration card's text was old DB-seeded copy from before
the platform-managed read-only redesign.

- [x] Updated ``services/spm_api/integrations_seed_data.py`` for
      ``int-021`` (Redis) — fresh installs now seed the correct
      description on first boot.
- [x] Updated the existing DB row via direct SQL UPDATE on
      ``integrations.description``. The bootstrap-on-startup upsert
      in ``_upsert_integration`` (``integrations_routes.py:1497``)
      reconciles ``description`` on every spm-api restart, so future
      drift won't recur as long as the seed file stays correct.

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
