# Kafka + Flink High Availability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Configure Kafka to run as a 3-broker KRaft ensemble and Flink with Kubernetes-native HA (2 JobManager replicas), in both the Docker Compose local stack and the Helm/K8s production deployment.

**Architecture:** Kafka moves from a single controller+broker pair to three combined KRaft nodes (each pod is both broker and controller), providing broker fault tolerance, RF=3, and min.insync.replicas=2. Flink JobManager scales from 1 to 2 replicas using k8s-native leader election (ConfigMaps + Leases); a per-pod init container injects the correct `jobmanager.rpc.address` since the ConfigMap-mounted config is shared. Local Docker Compose keeps a single Flink JM (k8s HA is cloud-only) but gains 3 Kafka brokers.

**Tech Stack:** Confluent cp-kafka:7.6.1 (KRaft mode), Apache Flink 1.18.1 (k8s-native HA), Docker Compose v2 YAML anchors, Helm 3 templating

---

## File Map

| File | Change |
|------|--------|
| `compose.yml` | Replace kafka-controller+kafka-broker with kafka-1/2/3; update all bootstrap-server references; update depends_on; add replication/ISR settings |
| `flink/flink-conf.yaml` | Add comment clarifying single-JM compose; checkpointing already configured |
| `deploy/helm/aispm/values.yaml` | kafka.replicas 1→3; add flink.jobmanager.replicas=2; update KAFKA_BOOTSTRAP_SERVERS; add KAFKA_REPLICATION_FACTOR=3, KAFKA_MIN_INSYNC_REPLICAS=2 to platformEnv |
| `deploy/helm/aispm/values.prod.yaml` | kafka.replicas already 3; add flink.jobmanager.replicas=2 |
| `deploy/helm/aispm/templates/kafka-statefulset.yaml` | Dynamic KAFKA_NODE_ID from pod ordinal; 3-node quorum voters; RF=3; min ISR=2 |
| `deploy/helm/aispm/templates/flink-jobmanager-statefulset.yaml` | replicas 1→2; add init container for per-pod jobmanager.rpc.address |
| `deploy/helm/aispm/templates/flink-pvc.yaml` | flink-ha + flink-checkpoints → ReadWriteMany (both JMs share these) |
| `deploy/helm/aispm/templates/flink-conf-configmap.yaml` | Add comment about per-pod RPC address injection |
| `deploy/helm/aispm/templates/flink-rbac.yaml` | No changes needed (configmaps/leases/pods already covered) |

---

## Task 1: Update compose.yml for Kafka HA

**Files:**
- Modify: `compose.yml`

- [ ] **Step 1: Replace kafka services**
  Replace `kafka-controller` (controller-only) + `kafka-broker` (broker-only) with three combined KRaft nodes `kafka-1`, `kafka-2`, `kafka-3`. Each has `KAFKA_PROCESS_ROLES: broker,controller`, unique `KAFKA_NODE_ID` (1/2/3), and lists all three in `KAFKA_CONTROLLER_QUORUM_VOTERS`. Add `KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 3`, `KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR: 3`, `KAFKA_TRANSACTION_STATE_LOG_MIN_ISR: 2`, `KAFKA_MIN_INSYNC_REPLICAS: 2`. Give `kafka-1` the hostname alias `kafka-broker` for backward compat.

- [ ] **Step 2: Update x-common-env anchor**
  Change `KAFKA_BOOTSTRAP_SERVERS: kafka-broker:9092` → `kafka-1:9092,kafka-2:9092,kafka-3:9092`. Add `KAFKA_REPLICATION_FACTOR: "3"` (read by startup_orchestrator).

- [ ] **Step 3: Update hardcoded KAFKA_BOOTSTRAP_SERVERS**
  The following services hardcode `kafka-broker:9092` outside `*common-env` and need updating:
  - `agent-orchestrator`
  - `flink-taskmanager`
  - `flink-pyjob-submitter`

- [ ] **Step 4: Update depends_on references**
  Services that depend on `kafka-broker: service_healthy` must now depend on `kafka-1: service_healthy`:
  - `startup-orchestrator`
  - `spm-mcp`
  - `threat-hunting-agent`
  - `flink-pyjob-submitter`
  Add `kafka-1` dependency to `kafka-2` and `kafka-3` (so they start after broker 1).

- [ ] **Step 5: Commit**
  ```bash
  git add compose.yml
  git commit -m "feat(compose): replace single kafka broker with 3-node KRaft HA ensemble"
  ```

---

## Task 2: Document compose Flink single-JM mode

**Files:**
- Modify: `flink/flink-conf.yaml`

- [ ] **Step 1: Add HA comment block**
  Add a comment block explaining that compose runs single JM (HA is k8s-only). Checkpointing is already configured (RocksDB, 60s interval, EXACTLY_ONCE). No functional changes needed.

- [ ] **Step 2: Commit**
  ```bash
  git add flink/flink-conf.yaml
  git commit -m "docs(flink): document compose single-JM mode (HA is k8s-only)"
  ```

---

## Task 3: Update Helm kafka-statefulset.yaml

**Files:**
- Modify: `deploy/helm/aispm/templates/kafka-statefulset.yaml`

- [ ] **Step 1: Add command to derive KAFKA_NODE_ID from pod ordinal**
  Override the container command to extract the pod ordinal from `MY_POD_NAME` and export it as `KAFKA_NODE_ID` before launching Kafka:
  ```yaml
  command:
    - sh
    - -c
    - |
      export KAFKA_NODE_ID=${MY_POD_NAME##*-}
      exec /etc/confluent/docker/run
  ```

- [ ] **Step 2: Update KAFKA_CONTROLLER_QUORUM_VOTERS for 3 nodes**
  Replace the single-voter value with all three pod DNS entries:
  ```
  0@kafka-0.kafka.{{ .Values.global.namespace }}.svc.cluster.local:9093,1@kafka-1.kafka.{{ .Values.global.namespace }}.svc.cluster.local:9093,2@kafka-2.kafka.{{ .Values.global.namespace }}.svc.cluster.local:9093
  ```

- [ ] **Step 3: Update replication and ISR values**
  - `KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: "3"`
  - `KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR: "3"`
  - `KAFKA_TRANSACTION_STATE_LOG_MIN_ISR: "2"`
  - Add `KAFKA_MIN_INSYNC_REPLICAS: "2"`

- [ ] **Step 4: Commit**
  ```bash
  git add deploy/helm/aispm/templates/kafka-statefulset.yaml
  git commit -m "feat(helm/kafka): dynamic node ID, 3-node quorum voters, RF=3 min ISR=2"
  ```

---

## Task 4: Update values.yaml

**Files:**
- Modify: `deploy/helm/aispm/values.yaml`
- Modify: `deploy/helm/aispm/values.prod.yaml`

- [ ] **Step 1: Update kafka.replicas and add Flink JM replicas**
  - `kafka.replicas: 1` → `kafka.replicas: 3`
  - Add `flink.jobmanager.replicas: 2` under the flink section

- [ ] **Step 2: Update platformEnv bootstrap servers**
  - `KAFKA_BOOTSTRAP_SERVERS`: change to `kafka-0.kafka.aispm.svc.cluster.local:9092,kafka-1.kafka.aispm.svc.cluster.local:9092,kafka-2.kafka.aispm.svc.cluster.local:9092`
  - Add `KAFKA_REPLICATION_FACTOR: "3"`
  - Add `KAFKA_MIN_INSYNC_REPLICAS: "2"`

- [ ] **Step 3: Update values.prod.yaml**
  Add `flink.jobmanager.replicas: 2` (kafka.replicas: 3 is already there).

- [ ] **Step 4: Commit**
  ```bash
  git add deploy/helm/aispm/values.yaml deploy/helm/aispm/values.prod.yaml
  git commit -m "feat(helm/values): kafka replicas=3, flink JM replicas=2, update bootstrap servers"
  ```

---

## Task 5: Update flink-jobmanager-statefulset.yaml

**Files:**
- Modify: `deploy/helm/aispm/templates/flink-jobmanager-statefulset.yaml`

- [ ] **Step 1: Scale to 2 replicas**
  Change `replicas: 1` to `replicas: {{ .Values.flink.jobmanager.replicas | default 2 }}`.

- [ ] **Step 2: Add init container for per-pod RPC address**
  Add an initContainer that:
  1. Copies the ConfigMap flink-conf.yaml to an emptyDir
  2. Uses `sed` to replace `jobmanager.rpc.address` with the pod's own FQDN (`$(hostname -f)`)
  
  ```yaml
  initContainers:
    - name: prep-flink-conf
      image: busybox:1.36
      command:
        - sh
        - -c
        - |
          sed "s|^jobmanager\.rpc\.address:.*|jobmanager.rpc.address: $(hostname -f)|" \
            /flink-conf-base/flink-conf.yaml > /flink-conf-rw/flink-conf.yaml
      volumeMounts:
        - name: flink-conf
          mountPath: /flink-conf-base
        - name: flink-conf-rw
          mountPath: /flink-conf-rw
  ```

- [ ] **Step 3: Add emptyDir volume and update main container mount**
  Add `flink-conf-rw` emptyDir volume. Change the main container's flink-conf mount to use `flink-conf-rw` (the writable copy) instead of the raw ConfigMap.

- [ ] **Step 4: Commit**
  ```bash
  git add deploy/helm/aispm/templates/flink-jobmanager-statefulset.yaml
  git commit -m "feat(helm/flink): scale JM to 2 replicas with per-pod RPC address injection"
  ```

---

## Task 6: Update flink-pvc.yaml

**Files:**
- Modify: `deploy/helm/aispm/templates/flink-pvc.yaml`

- [ ] **Step 1: Set flink-ha and flink-checkpoints to ReadWriteMany**
  With 2 JM replicas both mounting the same PVCs, those PVCs must support concurrent multi-pod read-write access. Update `flink-ha` and `flink-checkpoints` to `accessModes: [ReadWriteMany]`.
  
  Note: `local-path` (dev default) does NOT support RWX. In dev, both JM pods land on the same node so RWO will work. For production with Longhorn or NFS, RWX is properly supported. Add a comment calling this out.

- [ ] **Step 2: Commit**
  ```bash
  git add deploy/helm/aispm/templates/flink-pvc.yaml
  git commit -m "feat(helm/flink-pvc): ReadWriteMany for flink-ha and flink-checkpoints (multi-JM)"
  ```

---

## Task 7: Update flink-conf-configmap and verify RBAC

**Files:**
- Modify: `deploy/helm/aispm/templates/flink-conf-configmap.yaml`
- Verify: `deploy/helm/aispm/templates/flink-rbac.yaml`

- [ ] **Step 1: Add comment to flink-conf-configmap about per-pod RPC override**
  The `jobmanager.rpc.address: flink-jobmanager` in the configmap is overridden at pod start by the init container. Add a comment documenting this.

- [ ] **Step 2: Verify RBAC covers k8s HA needs**
  The flink-rbac.yaml must grant: configmaps (get/list/watch/create/update/patch/delete), leases (same), pods (get/list/watch). Confirm these are present — no change needed.

- [ ] **Step 3: Commit**
  ```bash
  git add deploy/helm/aispm/templates/flink-conf-configmap.yaml
  git commit -m "docs(helm/flink): note per-pod RPC address override in configmap"
  ```

---

## Task 8: Final commit

- [ ] **Step 1: Squash or create final HA commit**
  ```bash
  git add -A
  git commit -m "feat: configure Kafka and Flink in HA mode (3 Kafka brokers, Flink k8s-native HA with 2 JM replicas)"
  ```

- [ ] **Step 2: Verify no stray changes**
  ```bash
  git diff HEAD~1 --stat
  ```
  Expected: only the 8 files listed in the file map above.
