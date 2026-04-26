# Kubernetes / Rancher Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the AI-SPM platform from docker-compose to Kubernetes (RKE2) with Rancher as the management plane, replacing all Docker SDK container operations with the Kubernetes Python client, and enforcing per-agent microVM isolation via Kata Containers.

**Architecture:** One umbrella Helm chart (`deploy/helm/aispm/`) with service templates grouped by concern. Stateful services (Postgres, Kafka, Redis, Flink) use StatefulSets + Longhorn PVCs. Stateless services use Deployments. The `startup-orchestrator` and Flink job submitter become Kubernetes Jobs. Customer agent containers become on-demand Pods in the `aispm-agents` namespace, created by the `kubernetes` Python client (replacing the Docker SDK), each carrying `runtimeClassName: kata` for microVM isolation. All env vars move to a platform-wide ConfigMap; secrets move to Kubernetes Secrets. Istio runs in sidecar mode with STRICT mTLS across the `aispm` namespace (full L7 AuthorizationPolicy + Kiali observability); the `aispm-agents` namespace uses Istio Ambient mode (ztunnel DaemonSet, no sidecar injected) to avoid conflicts between Envoy and Kata's VM network boundary. NetworkPolicy + AuthorizationPolicy both enforce agent egress to only spm-mcp, spm-llm-proxy, Kafka, and a narrow set of spm-api paths.

**Tech Stack:** Kubernetes 1.29+, RKE2, Rancher 2.8+, Helm 3, Longhorn (storage), ingress-nginx, cert-manager, Istio 1.22+ (sidecar/Ambient), Tetragon (eBPF inline enforcement), Falco + Falcosidekick (behavioral alerting → Kafka), `kubernetes==29.*` Python client, Python 3.12, pytest.

---

## File Structure

### New files

```
deploy/
  helm/
    aispm/
      Chart.yaml
      values.yaml                          # platform-wide defaults
      values.prod.yaml                     # production overrides
      templates/
        _helpers.tpl
        namespace.yaml
        # Infrastructure
        kafka-statefulset.yaml
        kafka-service.yaml
        redis-statefulset.yaml
        redis-service.yaml
        opa-deployment.yaml
        opa-service.yaml
        # One-shot jobs
        startup-orchestrator-job.yaml
        flink-pyjob-submitter-job.yaml
        # Platform services (one file each)
        guard-model-deployment.yaml
        garak-runner-deployment.yaml
        api-deployment.yaml
        retrieval-gateway-deployment.yaml
        processor-deployment.yaml
        policy-decider-deployment.yaml
        agent-deployment.yaml
        memory-service-deployment.yaml
        executor-deployment.yaml
        tool-parser-deployment.yaml
        output-guard-deployment.yaml
        freeze-controller-deployment.yaml
        policy-simulator-deployment.yaml
        # Flink
        flink-jobmanager-statefulset.yaml
        flink-taskmanager-deployment.yaml
        flink-pvc.yaml
        # SPM platform
        spm-db-statefulset.yaml
        spm-db-pvc.yaml
        spm-db-service.yaml
        spm-api-deployment.yaml
        spm-mcp-deployment.yaml
        spm-llm-proxy-deployment.yaml
        spm-aggregator-deployment.yaml
        agent-orchestrator-deployment.yaml
        threat-hunting-agent-deployment.yaml
        # Observability
        prometheus-deployment.yaml
        grafana-deployment.yaml
        # UI
        ui-deployment.yaml
        ui-ingress.yaml
        # Istio
        istio-peerauthentication.yaml
        istio-authorizationpolicies.yaml
        istio-gateway.yaml
        istio-virtualservices.yaml
        # Runtime security
        falco-rules-configmap.yaml
        tetragon-tracingpolicies.yaml
        # Shared
        configmap-platform-env.yaml
        secrets.yaml                       # template only — values injected via Rancher
        services.yaml                      # ClusterIP Services for every Deployment
  istio/
    istio-values.yaml                    # reference values for istioctl / helm install
  falco/
    falco-values.yaml                    # Falco Helm values — scoped to aispm-agents
  tetragon/
    tetragon-values.yaml                 # Tetragon Helm values

  k8s/
    namespaces/
      aispm.yaml                         # MODIFIED: +istio-injection label
      aispm-agents.yaml                  # MODIFIED: +ambient dataplane-mode label
    rbac/
      spm-api-sa.yaml                      # SA + ClusterRole + Binding for pod creation
      agent-runtime-sa.yaml                # SA for agent pods (no cluster perms)
    network-policies/
      agent-default-deny.yaml
      agent-allow-egress.yaml
    storage/
      longhorn-storageclass.yaml
      spm-db-pvc.yaml
      redis-pvc.yaml
      flink-checkpoints-pvc.yaml
      flink-savepoints-pvc.yaml
      spm-api-models-pvc.yaml
    runtime/
      kata-runtimeclass.yaml
    ingress/
      aispm-ingress.yaml
      cert-manager-clusterissuer.yaml

services/spm_api/agent_controller.py      # MODIFIED — Docker SDK → k8s Python client
services/spm_api/requirements.txt         # MODIFIED — add kubernetes==29.*
tests/spm_api/test_agent_controller_k8s.py  # NEW — tests for k8s backend
```

### Modified files

```
services/spm_api/agent_controller.py      # core rewrite
services/spm_api/requirements.txt         # +kubernetes==29.*
docker-compose.yml                        # kept for local dev; no changes required
```

---

## Task 1: RKE2 Cluster Prerequisites
**Effort:** M (2 h, ops work — no automated tests; verified by `kubectl` checks)

**Files:**
- Create: `deploy/k8s/namespaces/aispm.yaml`
- Create: `deploy/k8s/namespaces/aispm-agents.yaml`
- Create: `deploy/k8s/runtime/kata-runtimeclass.yaml`

- [ ] **Step 1: Verify RKE2 + Rancher are reachable**

```bash
kubectl cluster-info
kubectl get nodes -o wide        # should show Ready nodes with RKE2 version
```

Expected: nodes in `Ready` state, server version ≥ 1.29.

- [ ] **Step 2: Install Kata Containers on every worker node**

On each worker node (Ubuntu 22.04):

```bash
KATA_VERSION=3.2.0
curl -fsSL https://github.com/kata-containers/kata-containers/releases/download/${KATA_VERSION}/kata-static-${KATA_VERSION}-amd64.tar.xz \
  | sudo tar -xJp -C /

# Configure containerd to use the kata shim
sudo tee /etc/containerd/config.toml.d/kata.toml <<'EOF'
[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.kata]
  runtime_type = "io.containerd.kata.v2"
EOF
sudo systemctl restart containerd
```

Verify: `sudo kata-runtime check` should print "System is capable of running Kata Containers".

- [ ] **Step 3: Create the kata RuntimeClass manifest**

```yaml
# deploy/k8s/runtime/kata-runtimeclass.yaml
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: kata
handler: kata
overhead:
  podFixed:
    memory: "64Mi"
    cpu: "250m"
scheduling:
  nodeClassification:
    tolerations:
      - key: kata
        operator: Exists
        effect: NoSchedule
```

```bash
kubectl apply -f deploy/k8s/runtime/kata-runtimeclass.yaml
kubectl get runtimeclass kata
```

- [ ] **Step 4: Create the namespaces**

```yaml
# deploy/k8s/namespaces/aispm.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: aispm
  labels:
    app.kubernetes.io/managed-by: helm
```

```yaml
# deploy/k8s/namespaces/aispm-agents.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: aispm-agents
  labels:
    purpose: agent-runtime
    pod-security.kubernetes.io/enforce: restricted
```

```bash
kubectl apply -f deploy/k8s/namespaces/
kubectl get ns aispm aispm-agents
```

- [ ] **Step 5: Install Longhorn via Rancher UI or Helm**

```bash
helm repo add longhorn https://charts.longhorn.io
helm repo update
helm install longhorn longhorn/longhorn \
  --namespace longhorn-system \
  --create-namespace \
  --set defaultSettings.defaultReplicaCount=2
kubectl -n longhorn-system rollout status deploy/longhorn-manager
```

- [ ] **Step 6: Create Longhorn StorageClass manifest**

```yaml
# deploy/k8s/storage/longhorn-storageclass.yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: longhorn
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: driver.longhorn.io
reclaimPolicy: Retain
volumeBindingMode: Immediate
parameters:
  numberOfReplicas: "2"
  staleReplicaTimeout: "2880"
```

```bash
kubectl apply -f deploy/k8s/storage/longhorn-storageclass.yaml
kubectl get sc longhorn
```

- [ ] **Step 7: Install cert-manager**

```bash
helm repo add jetstack https://charts.jetstack.io
helm repo update
helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --set installCRDs=true
kubectl -n cert-manager rollout status deploy/cert-manager
```

- [ ] **Step 8: Install ingress-nginx**

```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update
helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace \
  --set controller.service.type=LoadBalancer
kubectl -n ingress-nginx rollout status deploy/ingress-nginx-controller
```

- [ ] **Step 9: Commit**

```bash
git add deploy/k8s/
git commit -m "chore(k8s): cluster prerequisites — namespaces, kata RuntimeClass, storage, ingress"
```

---

## Task 2: Helm Chart Skeleton
**Effort:** M (1.5 h)

**Files:**
- Create: `deploy/helm/aispm/Chart.yaml`
- Create: `deploy/helm/aispm/values.yaml`
- Create: `deploy/helm/aispm/templates/_helpers.tpl`

- [ ] **Step 1: Create Chart.yaml**

```yaml
# deploy/helm/aispm/Chart.yaml
apiVersion: v2
name: aispm
description: AI Security Posture Management platform
type: application
version: 1.0.0
appVersion: "3.0.0"
keywords:
  - ai-security
  - llm
  - agent-runtime
```

- [ ] **Step 2: Create values.yaml with all service images and env defaults**

```yaml
# deploy/helm/aispm/values.yaml
global:
  imageRegistry: ""          # e.g. registry.example.com/aispm
  imagePullPolicy: IfNotPresent
  namespace: aispm

# ── Per-service image tags ───────────────────────────────────────────────────
images:
  api:           { repository: aispm-api,           tag: latest }
  guardModel:    { repository: aispm-guard-model,   tag: latest }
  garakRunner:   { repository: aispm-garak-runner,  tag: latest }
  retrievalGw:   { repository: aispm-retrieval-gw,  tag: latest }
  processor:     { repository: aispm-processor,     tag: latest }
  policyDecider: { repository: aispm-policy-decider, tag: latest }
  agent:         { repository: aispm-agent,         tag: latest }
  memoryService: { repository: aispm-memory,        tag: latest }
  executor:      { repository: aispm-executor,      tag: latest }
  toolParser:    { repository: aispm-tool-parser,   tag: latest }
  outputGuard:   { repository: aispm-output-guard,  tag: latest }
  freezeCtrl:    { repository: aispm-freeze-ctrl,   tag: latest }
  policySimulator: { repository: aispm-policy-sim,  tag: latest }
  spmApi:        { repository: aispm-spm-api,       tag: latest }
  spmMcp:        { repository: aispm-spm-mcp,       tag: latest }
  spmLlmProxy:   { repository: aispm-spm-llm-proxy, tag: latest }
  spmAggregator: { repository: aispm-spm-aggregator, tag: latest }
  agentOrchestrator: { repository: aispm-agent-orchestrator, tag: latest }
  threatHunter:  { repository: aispm-threat-hunter, tag: latest }
  ui:            { repository: aispm-ui,            tag: latest }
  startupOrch:   { repository: aispm-startup-orch,  tag: latest }
  flinkJob:      { repository: aispm-flink-pyjob,   tag: latest }
  agentRuntime:  { repository: aispm-agent-runtime, tag: latest }

# ── Infrastructure images (upstream) ────────────────────────────────────────
kafka:
  image: confluentinc/cp-kafka
  tag: "7.6.1"
  replicas: 1
  clusterId: q1Enf0NkTvaBgXGsKZoeRA
  storage: 10Gi
  storageClass: longhorn

redis:
  image: redis
  tag: "7-alpine"
  storage: 1Gi
  storageClass: longhorn
  maxmemory: 512mb

opa:
  image: openpolicyagent/opa
  tag: "0.70.0"

spmDb:
  image: postgres
  tag: "16-alpine"
  storage: 20Gi
  storageClass: longhorn
  database: spm
  user: spm_rw

# ── Platform env (non-secret) ────────────────────────────────────────────────
platformEnv:
  KAFKA_BOOTSTRAP_SERVERS: kafka-broker.aispm.svc.cluster.local:9092
  OPA_URL: http://opa.aispm.svc.cluster.local:8181
  JWT_ALGORITHM: RS256
  JWT_ISSUER: cpm-platform
  GUARD_MODEL_URL: http://guard-model.aispm.svc.cluster.local:8200
  GUARD_MODEL_ENABLED: "true"
  GUARD_MODEL_TIMEOUT: "60.0"
  WS_WAIT_TIMEOUT_S: "10.0"
  RATE_LIMIT_RPM: "60"
  SERVICE_VERSION: "3.0.0"
  ENVIRONMENT: production
  REDIS_HOST: redis.aispm.svc.cluster.local
  REDIS_PORT: "6379"
  AGENT_MCP_URL: http://spm-mcp.aispm.svc.cluster.local:8500/mcp
  AGENT_LLM_BASE_URL: http://spm-llm-proxy.aispm.svc.cluster.local:8500/v1
  AGENT_CONTROLLER_URL: http://spm-api.aispm.svc.cluster.local:8092
  AGENT_POD_NAMESPACE: aispm-agents
  AGENT_RUNTIME_IMAGE: aispm-agent-runtime:latest

# ── Agent runtime ────────────────────────────────────────────────────────────
agentRuntime:
  namespace: aispm-agents
  runtimeClassName: kata
  defaultMemMi: 512
  defaultCpuMillicores: 500

# ── Ingress ──────────────────────────────────────────────────────────────────
ingress:
  enabled: true
  className: nginx
  host: aispm.example.com
  tlsSecretName: aispm-tls
  letsencryptEmail: ops@example.com

# ── Observability ────────────────────────────────────────────────────────────
prometheus:
  storage: 10Gi
  storageClass: longhorn

grafana:
  adminPasswordSecret: grafana-secret
  storage: 2Gi
  storageClass: longhorn
```

- [ ] **Step 3: Create `_helpers.tpl`**

```
{{/* deploy/helm/aispm/templates/_helpers.tpl */}}
{{- define "aispm.image" -}}
{{- $svc := . -}}
{{- if $.Values.global.imageRegistry -}}
{{ $.Values.global.imageRegistry }}/{{ $svc.repository }}:{{ $svc.tag }}
{{- else -}}
{{ $svc.repository }}:{{ $svc.tag }}
{{- end -}}
{{- end -}}

{{- define "aispm.labels" -}}
app.kubernetes.io/managed-by: Helm
app.kubernetes.io/part-of: aispm
{{- end -}}
```

- [ ] **Step 4: Lint the skeleton**

```bash
helm lint deploy/helm/aispm/
```

Expected: "1 chart(s) linted, 0 chart(s) failed"

- [ ] **Step 5: Commit**

```bash
git add deploy/helm/aispm/
git commit -m "chore(helm): scaffold aispm chart skeleton with values.yaml and helpers"
```

---

## Task 3: Secrets & ConfigMaps Migration
**Effort:** M (1.5 h)

All docker-compose `*common-env*` env vars and the JWT key pair become k8s Secrets and a platform-wide ConfigMap.

**Files:**
- Create: `deploy/helm/aispm/templates/configmap-platform-env.yaml`
- Create: `deploy/helm/aispm/templates/secrets.yaml`
- Create: `deploy/k8s/rbac/spm-api-sa.yaml`
- Create: `deploy/k8s/rbac/agent-runtime-sa.yaml`

- [ ] **Step 1: Create platform ConfigMap template**

```yaml
# deploy/helm/aispm/templates/configmap-platform-env.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: platform-env
  namespace: {{ .Values.global.namespace }}
data:
  {{- range $k, $v := .Values.platformEnv }}
  {{ $k }}: {{ $v | quote }}
  {{- end }}
  JWT_PRIVATE_KEY_PATH: /keys/private.pem
  JWT_PUBLIC_KEY_PATH: /keys/public.pem
  KEYS_DIR: /keys
```

- [ ] **Step 2: Create secrets template (values injected at deploy time via Rancher)**

```yaml
# deploy/helm/aispm/templates/secrets.yaml
# Values are base64-encoded and injected via Rancher Secrets UI or
# `--set` flags at deploy time. Never commit real values.
apiVersion: v1
kind: Secret
metadata:
  name: platform-secrets
  namespace: {{ .Values.global.namespace }}
type: Opaque
stringData:
  SPM_DB_PASSWORD: {{ .Values.secrets.spmDbPassword | default "CHANGEME" | quote }}
  GROQ_API_KEY: {{ .Values.secrets.groqApiKey | default "" | quote }}
  ANTHROPIC_API_KEY: {{ .Values.secrets.anthropicApiKey | default "" | quote }}
  TAVILY_API_KEY: {{ .Values.secrets.tavilyApiKey | default "" | quote }}
  GARAK_INTERNAL_SECRET: {{ .Values.secrets.garakInternalSecret | default "" | quote }}
  SPM_INTERNAL_BOOTSTRAP_SECRET: {{ .Values.secrets.spmInternalBootstrapSecret | default "" | quote }}
  GRAFANA_ADMIN_PASSWORD: {{ .Values.secrets.grafanaAdminPassword | default "admin" | quote }}
---
apiVersion: v1
kind: Secret
metadata:
  name: jwt-keys
  namespace: {{ .Values.global.namespace }}
type: Opaque
data:
  # Populate with: kubectl create secret generic jwt-keys \
  #   --from-file=private.pem=keys/private.pem \
  #   --from-file=public.pem=keys/public.pem \
  #   -n aispm --dry-run=client -o yaml | kubectl apply -f -
  private.pem: ""
  public.pem: ""
```

- [ ] **Step 3: Create spm-api ServiceAccount + RBAC (for creating/deleting agent Pods)**

```yaml
# deploy/k8s/rbac/spm-api-sa.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: spm-api
  namespace: aispm
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: agent-pod-controller
  namespace: aispm-agents
rules:
  - apiGroups: [""]
    resources: ["pods", "configmaps"]
    verbs: ["get", "list", "watch", "create", "delete", "patch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: spm-api-agent-pod-controller
  namespace: aispm-agents
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: agent-pod-controller
subjects:
  - kind: ServiceAccount
    name: spm-api
    namespace: aispm
```

- [ ] **Step 4: Create agent-runtime ServiceAccount (minimal — no cluster perms)**

```yaml
# deploy/k8s/rbac/agent-runtime-sa.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: agent-runtime
  namespace: aispm-agents
automountServiceAccountToken: false
```

- [ ] **Step 5: Apply and verify**

```bash
kubectl apply -f deploy/k8s/rbac/
kubectl get sa spm-api -n aispm
kubectl get role agent-pod-controller -n aispm-agents
```

- [ ] **Step 6: Create the jwt-keys Secret from local keys/**

```bash
kubectl create secret generic jwt-keys \
  --from-file=private.pem=keys/private.pem \
  --from-file=public.pem=keys/public.pem \
  -n aispm --dry-run=client -o yaml > /tmp/jwt-keys.yaml
# Review /tmp/jwt-keys.yaml, then apply:
kubectl apply -f /tmp/jwt-keys.yaml
```

- [ ] **Step 7: Commit**

```bash
git add deploy/helm/aispm/templates/configmap-platform-env.yaml \
        deploy/helm/aispm/templates/secrets.yaml \
        deploy/k8s/rbac/
git commit -m "chore(k8s): platform ConfigMap, secrets template, spm-api RBAC"
```

---

## Task 4: spm-db StatefulSet (Postgres + Longhorn)
**Effort:** M (1.5 h)

**Files:**
- Create: `deploy/helm/aispm/templates/spm-db-statefulset.yaml`
- Create: `deploy/helm/aispm/templates/spm-db-service.yaml`
- Create: `deploy/k8s/storage/spm-db-pvc.yaml`

- [ ] **Step 1: Write the StatefulSet template**

```yaml
# deploy/helm/aispm/templates/spm-db-statefulset.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: spm-db
  namespace: {{ .Values.global.namespace }}
spec:
  serviceName: spm-db
  replicas: 1
  selector:
    matchLabels:
      app: spm-db
  template:
    metadata:
      labels:
        app: spm-db
    spec:
      containers:
        - name: postgres
          image: {{ .Values.spmDb.image }}:{{ .Values.spmDb.tag }}
          ports:
            - containerPort: 5432
          env:
            - name: POSTGRES_DB
              value: {{ .Values.spmDb.database }}
            - name: POSTGRES_USER
              value: {{ .Values.spmDb.user }}
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: platform-secrets
                  key: SPM_DB_PASSWORD
          volumeMounts:
            - name: data
              mountPath: /var/lib/postgresql/data
            - name: init-sql
              mountPath: /docker-entrypoint-initdb.d/001_initial.sql
              subPath: 001_initial.sql
          livenessProbe:
            exec:
              command: ["pg_isready", "-U", "{{ .Values.spmDb.user }}", "-d", "{{ .Values.spmDb.database }}"]
            initialDelaySeconds: 15
            periodSeconds: 10
          readinessProbe:
            exec:
              command: ["pg_isready", "-U", "{{ .Values.spmDb.user }}", "-d", "{{ .Values.spmDb.database }}"]
            initialDelaySeconds: 5
            periodSeconds: 5
      volumes:
        - name: init-sql
          configMap:
            name: spm-db-init-sql
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: [ReadWriteOnce]
        storageClassName: {{ .Values.spmDb.storageClass }}
        resources:
          requests:
            storage: {{ .Values.spmDb.storage }}
```

- [ ] **Step 2: Write the headless Service (required for StatefulSet DNS)**

```yaml
# deploy/helm/aispm/templates/spm-db-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: spm-db
  namespace: {{ .Values.global.namespace }}
spec:
  clusterIP: None   # headless — each pod gets a stable DNS entry
  selector:
    app: spm-db
  ports:
    - port: 5432
      targetPort: 5432
```

- [ ] **Step 3: Create ConfigMap with the init SQL (embed the file content)**

```bash
kubectl create configmap spm-db-init-sql \
  --from-file=001_initial.sql=spm/db/migrations/001_initial.sql \
  -n aispm --dry-run=client -o yaml \
  > deploy/helm/aispm/templates/spm-db-init-configmap.yaml
```

Edit the output to add `namespace: {{ .Values.global.namespace }}` under `metadata`.

- [ ] **Step 4: Dry-run the full template**

```bash
helm template aispm deploy/helm/aispm/ \
  --set secrets.spmDbPassword=testpass \
  | grep -A 60 "kind: StatefulSet"
```

- [ ] **Step 5: Install and verify**

```bash
helm upgrade --install aispm deploy/helm/aispm/ \
  -n aispm \
  --set secrets.spmDbPassword=testpass \
  --set secrets.grafanaAdminPassword=admin
kubectl -n aispm rollout status statefulset/spm-db
kubectl -n aispm exec spm-db-0 -- pg_isready -U spm_rw -d spm
```

- [ ] **Step 6: Commit**

```bash
git add deploy/helm/aispm/templates/spm-db-*.yaml
git commit -m "feat(helm): spm-db StatefulSet + Longhorn PVC + headless Service"
```

---

## Task 5: Kafka KRaft StatefulSet
**Effort:** L (2.5 h — KRaft combined-mode requires careful env wiring)

**Files:**
- Create: `deploy/helm/aispm/templates/kafka-statefulset.yaml`
- Create: `deploy/helm/aispm/templates/kafka-service.yaml`

KRaft combined mode: a single StatefulSet where each pod runs both `controller` and `broker` roles. This replaces the docker-compose split of `kafka-controller` + `kafka-broker` while keeping the same Cluster ID.

- [ ] **Step 1: Write the combined StatefulSet**

```yaml
# deploy/helm/aispm/templates/kafka-statefulset.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: kafka
  namespace: {{ .Values.global.namespace }}
spec:
  serviceName: kafka
  replicas: {{ .Values.kafka.replicas }}
  selector:
    matchLabels:
      app: kafka
  template:
    metadata:
      labels:
        app: kafka
    spec:
      containers:
        - name: kafka
          image: {{ .Values.kafka.image }}:{{ .Values.kafka.tag }}
          ports:
            - containerPort: 9092   # PLAINTEXT (internal)
            - containerPort: 9093   # CONTROLLER
          env:
            - name: KAFKA_NODE_ID
              valueFrom:
                fieldRef:
                  fieldPath: metadata.annotations['kafka.node-id']
            - name: MY_POD_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
            - name: KAFKA_PROCESS_ROLES
              value: "broker,controller"
            - name: KAFKA_LISTENERS
              value: "PLAINTEXT://:9092,CONTROLLER://:9093"
            - name: KAFKA_LISTENER_SECURITY_PROTOCOL_MAP
              value: "PLAINTEXT:PLAINTEXT,CONTROLLER:PLAINTEXT"
            - name: KAFKA_INTER_BROKER_LISTENER_NAME
              value: PLAINTEXT
            - name: KAFKA_CONTROLLER_LISTENER_NAMES
              value: CONTROLLER
            - name: KAFKA_CONTROLLER_QUORUM_VOTERS
              value: "0@kafka-0.kafka.{{ .Values.global.namespace }}.svc.cluster.local:9093"
            - name: KAFKA_ADVERTISED_LISTENERS
              value: "PLAINTEXT://$(MY_POD_NAME).kafka.{{ .Values.global.namespace }}.svc.cluster.local:9092"
            - name: KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR
              value: "1"
            - name: KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR
              value: "1"
            - name: KAFKA_TRANSACTION_STATE_LOG_MIN_ISR
              value: "1"
            - name: KAFKA_NUM_PARTITIONS
              value: "3"
            - name: CLUSTER_ID
              value: {{ .Values.kafka.clusterId | quote }}
          readinessProbe:
            exec:
              command:
                - sh
                - -c
                - "kafka-broker-api-versions --bootstrap-server localhost:9092"
            initialDelaySeconds: 30
            periodSeconds: 10
            failureThreshold: 10
          volumeMounts:
            - name: data
              mountPath: /var/lib/kafka/data
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: [ReadWriteOnce]
        storageClassName: {{ .Values.kafka.storageClass }}
        resources:
          requests:
            storage: {{ .Values.kafka.storage }}
```

- [ ] **Step 2: Write Kafka Services (headless + ClusterIP)**

```yaml
# deploy/helm/aispm/templates/kafka-service.yaml
# Headless service for stable per-pod DNS (kafka-0.kafka.aispm...)
apiVersion: v1
kind: Service
metadata:
  name: kafka
  namespace: {{ .Values.global.namespace }}
spec:
  clusterIP: None
  selector:
    app: kafka
  ports:
    - name: broker
      port: 9092
    - name: controller
      port: 9093
---
# Named ClusterIP service matching the compose hostname "kafka-broker"
apiVersion: v1
kind: Service
metadata:
  name: kafka-broker
  namespace: {{ .Values.global.namespace }}
spec:
  selector:
    app: kafka
  ports:
    - port: 9092
      targetPort: 9092
```

- [ ] **Step 3: Format and verify template renders**

```bash
helm template aispm deploy/helm/aispm/ | grep -A 80 "name: kafka" | head -90
```

- [ ] **Step 4: Deploy and verify broker readiness**

```bash
helm upgrade --install aispm deploy/helm/aispm/ -n aispm \
  --set secrets.spmDbPassword=testpass
kubectl -n aispm rollout status statefulset/kafka
kubectl -n aispm exec kafka-0 -- kafka-broker-api-versions \
  --bootstrap-server localhost:9092
```

Expected: prints broker API versions table.

- [ ] **Step 5: Commit**

```bash
git add deploy/helm/aispm/templates/kafka-*.yaml
git commit -m "feat(helm): Kafka KRaft combined-mode StatefulSet"
```

---

## Task 6: Redis StatefulSet + OPA Deployment
**Effort:** S (45 min)

**Files:**
- Create: `deploy/helm/aispm/templates/redis-statefulset.yaml`
- Create: `deploy/helm/aispm/templates/opa-deployment.yaml`
- Create: `deploy/helm/aispm/templates/services.yaml` (aggregates all ClusterIP services)

- [ ] **Step 1: Redis StatefulSet**

```yaml
# deploy/helm/aispm/templates/redis-statefulset.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: redis
  namespace: {{ .Values.global.namespace }}
spec:
  serviceName: redis
  replicas: 1
  selector:
    matchLabels: { app: redis }
  template:
    metadata:
      labels: { app: redis }
    spec:
      containers:
        - name: redis
          image: {{ .Values.redis.image }}:{{ .Values.redis.tag }}
          command:
            - redis-server
            - --save
            - ""
            - --appendonly
            - "yes"
            - --stop-writes-on-bgsave-error
            - "no"
            - --maxmemory
            - {{ .Values.redis.maxmemory }}
            - --maxmemory-policy
            - allkeys-lru
          ports:
            - containerPort: 6379
          readinessProbe:
            exec:
              command: ["redis-cli", "ping"]
            initialDelaySeconds: 5
            periodSeconds: 5
          volumeMounts:
            - name: data
              mountPath: /data
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: [ReadWriteOnce]
        storageClassName: {{ .Values.redis.storageClass }}
        resources:
          requests:
            storage: {{ .Values.redis.storage }}
```

- [ ] **Step 2: OPA Deployment — mount policies from a ConfigMap**

```bash
# First, build a ConfigMap with all OPA policies:
kubectl create configmap opa-policies \
  --from-file=opa/policies/ \
  -n aispm --dry-run=client -o yaml \
  > deploy/helm/aispm/templates/opa-policies-configmap.yaml
# Add namespace: {{ .Values.global.namespace }} to metadata manually
```

```yaml
# deploy/helm/aispm/templates/opa-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: opa
  namespace: {{ .Values.global.namespace }}
spec:
  replicas: 1
  selector:
    matchLabels: { app: opa }
  template:
    metadata:
      labels: { app: opa }
    spec:
      containers:
        - name: opa
          image: {{ .Values.opa.image }}:{{ .Values.opa.tag }}
          args: ["run", "--server", "--addr=0.0.0.0:8181", "--log-level=info", "/policies"]
          ports:
            - containerPort: 8181
          volumeMounts:
            - name: policies
              mountPath: /policies
              readOnly: true
          readinessProbe:
            httpGet:
              path: /health
              port: 8181
            initialDelaySeconds: 5
            periodSeconds: 5
      volumes:
        - name: policies
          configMap:
            name: opa-policies
```

- [ ] **Step 3: Add ClusterIP Services for Redis + OPA to services.yaml**

```yaml
# deploy/helm/aispm/templates/services.yaml
# Aggregated ClusterIP services for all stateless services.
# StatefulSets have their own headless service files.
---
apiVersion: v1
kind: Service
metadata:
  name: redis
  namespace: {{ .Values.global.namespace }}
spec:
  selector: { app: redis }
  ports:
    - port: 6379
---
apiVersion: v1
kind: Service
metadata:
  name: opa
  namespace: {{ .Values.global.namespace }}
spec:
  selector: { app: opa }
  ports:
    - port: 8181
```

- [ ] **Step 4: Verify Redis and OPA reach Ready state**

```bash
helm upgrade --install aispm deploy/helm/aispm/ -n aispm \
  --set secrets.spmDbPassword=testpass
kubectl -n aispm rollout status statefulset/redis
kubectl -n aispm rollout status deploy/opa
kubectl -n aispm exec deploy/opa -- wget -qO- http://localhost:8181/health
```

- [ ] **Step 5: Commit**

```bash
git add deploy/helm/aispm/templates/redis-*.yaml \
        deploy/helm/aispm/templates/opa-*.yaml \
        deploy/helm/aispm/templates/services.yaml
git commit -m "feat(helm): Redis StatefulSet and OPA Deployment"
```

---

## Task 7: startup-orchestrator as a Kubernetes Job
**Effort:** S (1 h)

The startup-orchestrator runs once to provision Kafka topics and generate JWT keys. In k8s this is a Job with `restartPolicy: OnFailure`. JWT keys are already in the `jwt-keys` Secret (created in Task 3); the Job only needs to provision Kafka topics.

**Files:**
- Create: `deploy/helm/aispm/templates/startup-orchestrator-job.yaml`

- [ ] **Step 1: Write the Job template**

```yaml
# deploy/helm/aispm/templates/startup-orchestrator-job.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: startup-orchestrator
  namespace: {{ .Values.global.namespace }}
  annotations:
    "helm.sh/hook": post-install,post-upgrade
    "helm.sh/hook-weight": "-5"
    "helm.sh/hook-delete-policy": hook-succeeded
spec:
  backoffLimit: 3
  template:
    spec:
      restartPolicy: OnFailure
      # Wait for Kafka broker and Redis to be ready before running the orchestrator.
      # Without this, the hook may fire while Kafka is still in leader-election.
      initContainers:
        - name: wait-for-kafka
          image: busybox:1.36
          command:
            - sh
            - -c
            - |
              echo "Waiting for Kafka...";
              until nc -z kafka-broker.{{ .Values.global.namespace }}.svc.cluster.local 9092; do
                sleep 2;
              done;
              echo "Kafka ready."
        - name: wait-for-redis
          image: busybox:1.36
          command:
            - sh
            - -c
            - |
              echo "Waiting for Redis...";
              until nc -z redis.{{ .Values.global.namespace }}.svc.cluster.local 6379; do
                sleep 2;
              done;
              echo "Redis ready."
      containers:
        - name: startup-orchestrator
          image: {{ include "aispm.image" .Values.images.startupOrch }}
          envFrom:
            - configMapRef:
                name: platform-env
            - secretRef:
                name: platform-secrets
          env:
            - name: KEYS_DIR
              value: /keys-rw
            - name: JWT_PRIVATE_KEY_PATH
              value: /keys-rw/private.pem
            - name: JWT_PUBLIC_KEY_PATH
              value: /keys-rw/public.pem
          volumeMounts:
            - name: jwt-keys
              mountPath: /keys-rw
      volumes:
        - name: jwt-keys
          secret:
            secretName: jwt-keys
            defaultMode: 0600
```

- [ ] **Step 2: Verify Job renders correctly**

```bash
helm template aispm deploy/helm/aispm/ | grep -A 40 "kind: Job"
```

- [ ] **Step 3: Commit**

```bash
git add deploy/helm/aispm/templates/startup-orchestrator-job.yaml
git commit -m "feat(helm): startup-orchestrator as a post-install Helm Job"
```

---

## Task 8: Platform Service Deployments (Batch)
**Effort:** L (3 h — boilerplate-heavy; use a loop pattern)

Covers: `guard-model`, `garak-runner`, `api`, `retrieval-gateway`, `processor`, `policy-decider`, `agent`, `memory-service`, `executor`, `tool-parser`, `output-guard`, `freeze-controller`, `policy-simulator`.

All follow the same Deployment pattern: pull image from `values.yaml`, inject `platform-env` ConfigMap + `platform-secrets` Secret + `jwt-keys` volume, expose a ClusterIP Service.

**Files:** One template file per service (listed in File Structure above).

- [ ] **Step 1: Create the reusable pattern — use guard-model as the reference**

```yaml
# deploy/helm/aispm/templates/guard-model-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: guard-model
  namespace: {{ .Values.global.namespace }}
spec:
  replicas: 1
  selector:
    matchLabels: { app: guard-model }
  template:
    metadata:
      labels: { app: guard-model }
    spec:
      containers:
        - name: guard-model
          image: {{ include "aispm.image" .Values.images.guardModel }}
          imagePullPolicy: {{ .Values.global.imagePullPolicy }}
          ports:
            - containerPort: 8200
          envFrom:
            - configMapRef:
                name: platform-env
            - secretRef:
                name: platform-secrets
          env:
            - name: SPM_DB_URL
              value: "postgresql://{{ .Values.spmDb.user }}:$(SPM_DB_PASSWORD)@spm-db.{{ .Values.global.namespace }}.svc.cluster.local:5432/{{ .Values.spmDb.database }}"
          volumeMounts:
            - name: jwt-keys
              mountPath: /keys
              readOnly: true
          readinessProbe:
            httpGet: { path: /health, port: 8200 }
            initialDelaySeconds: 15
            periodSeconds: 10
          livenessProbe:
            httpGet: { path: /health, port: 8200 }
            initialDelaySeconds: 30
            periodSeconds: 15
      volumes:
        - name: jwt-keys
          secret:
            secretName: jwt-keys
            defaultMode: 0444
```

- [ ] **Step 2: Add guard-model to services.yaml**

```yaml
# Append to deploy/helm/aispm/templates/services.yaml:
---
apiVersion: v1
kind: Service
metadata:
  name: guard-model
  namespace: {{ .Values.global.namespace }}
spec:
  selector: { app: guard-model }
  ports:
    - port: 8200
```

- [ ] **Step 3: Replicate the pattern for all remaining services**

Copy `guard-model-deployment.yaml` and substitute for each service. Key differences:

| Service | Port | Extra env |
|---------|------|-----------|
| garak-runner | 8099 | `CPM_API_URL: http://api.aispm.svc.cluster.local:8080` |
| api | 8080 | `GARAK_RUNNER_URL: http://garak-runner.aispm.svc.cluster.local:8099`, `SPM_DB_URL` |
| retrieval-gateway | (internal) | none |
| processor | (internal) | none |
| policy-decider | (internal) | none |
| agent | (internal) | none |
| memory-service | (internal) | none |
| executor | (internal) | none |
| tool-parser | (internal) | none |
| output-guard | (internal) | none |
| freeze-controller | 8090 | none |
| policy-simulator | 8091 | none |

Services with no external port use `port: 80` on the ClusterIP Service pointing to the uvicorn port (8080 default).

Add corresponding entries to `services.yaml` for each.

- [ ] **Step 4: Lint and dry-run all new templates**

```bash
helm lint deploy/helm/aispm/
helm template aispm deploy/helm/aispm/ --set secrets.spmDbPassword=x \
  | kubectl apply --dry-run=client -f -
```

Expected: no errors. Warnings about missing CRDs (cert-manager) are acceptable.

- [ ] **Step 5: Deploy and verify a representative service**

```bash
helm upgrade --install aispm deploy/helm/aispm/ -n aispm \
  --set secrets.spmDbPassword=testpass
kubectl -n aispm rollout status deploy/api
kubectl -n aispm exec deploy/api -- \
  python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health', timeout=4)"
```

- [ ] **Step 6: Commit**

```bash
git add deploy/helm/aispm/templates/
git commit -m "feat(helm): Deployments for all CPM platform services"
```

---

## Task 9: Flink Cluster (StatefulSet + Job)
**Effort:** L (2.5 h)

**Files:**
- Create: `deploy/helm/aispm/templates/flink-jobmanager-statefulset.yaml`
- Create: `deploy/helm/aispm/templates/flink-taskmanager-deployment.yaml`
- Create: `deploy/helm/aispm/templates/flink-pyjob-submitter-job.yaml`
- Create: `deploy/helm/aispm/templates/flink-pvc.yaml`

- [ ] **Step 1: Create shared Flink PVCs for checkpoints + savepoints**

```yaml
# deploy/helm/aispm/templates/flink-pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: flink-checkpoints
  namespace: {{ .Values.global.namespace }}
spec:
  accessModes: [ReadWriteMany]
  storageClassName: longhorn
  resources:
    requests:
      storage: 5Gi
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: flink-savepoints
  namespace: {{ .Values.global.namespace }}
spec:
  accessModes: [ReadWriteMany]
  storageClassName: longhorn
  resources:
    requests:
      storage: 5Gi
```

Note: Longhorn supports ReadWriteMany only with the NFS provisioner or via a shared filesystem. If RWX is unavailable, use a single replica with RWO and co-locate jobmanager + taskmanager on the same node, or use an NFS PVC.

- [ ] **Step 2: JobManager StatefulSet**

```yaml
# deploy/helm/aispm/templates/flink-jobmanager-statefulset.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: flink-jobmanager
  namespace: {{ .Values.global.namespace }}
spec:
  serviceName: flink-jobmanager
  replicas: 1
  selector:
    matchLabels: { app: flink-jobmanager }
  template:
    metadata:
      labels: { app: flink-jobmanager }
    spec:
      containers:
        - name: flink-jobmanager
          image: {{ include "aispm.image" .Values.images.flinkJob }}
          command: ["jobmanager"]
          ports:
            - containerPort: 8081  # Flink REST UI
            - containerPort: 6123  # RPC
          env:
            - name: KAFKA_BOOTSTRAP_SERVERS
              valueFrom:
                configMapKeyRef:
                  name: platform-env
                  key: KAFKA_BOOTSTRAP_SERVERS
          volumeMounts:
            - name: flink-conf
              mountPath: /opt/flink/conf/flink-conf.yaml
              subPath: flink-conf.yaml
            - name: checkpoints
              mountPath: /flink/checkpoints
            - name: savepoints
              mountPath: /flink/savepoints
      volumes:
        - name: flink-conf
          configMap:
            name: flink-conf
        - name: checkpoints
          persistentVolumeClaim:
            claimName: flink-checkpoints
        - name: savepoints
          persistentVolumeClaim:
            claimName: flink-savepoints
```

- [ ] **Step 3: Build flink-conf ConfigMap from existing file**

```bash
kubectl create configmap flink-conf \
  --from-file=flink-conf.yaml=flink/flink-conf.yaml \
  -n aispm --dry-run=client -o yaml \
  > deploy/helm/aispm/templates/flink-conf-configmap.yaml
# Add namespace: {{ .Values.global.namespace }} to metadata
```

- [ ] **Step 4: TaskManager Deployment + submitter Job (same volumes)**

```yaml
# deploy/helm/aispm/templates/flink-taskmanager-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: flink-taskmanager
  namespace: {{ .Values.global.namespace }}
spec:
  replicas: 1
  selector:
    matchLabels: { app: flink-taskmanager }
  template:
    metadata:
      labels: { app: flink-taskmanager }
    spec:
      containers:
        - name: flink-taskmanager
          image: {{ include "aispm.image" .Values.images.flinkJob }}
          command: ["taskmanager"]
          volumeMounts:
            - name: flink-conf
              mountPath: /opt/flink/conf/flink-conf.yaml
              subPath: flink-conf.yaml
            - name: checkpoints
              mountPath: /flink/checkpoints
            - name: savepoints
              mountPath: /flink/savepoints
      volumes:
        - name: flink-conf
          configMap:
            name: flink-conf
        - name: checkpoints
          persistentVolumeClaim:
            claimName: flink-checkpoints
        - name: savepoints
          persistentVolumeClaim:
            claimName: flink-savepoints
```

```yaml
# deploy/helm/aispm/templates/flink-pyjob-submitter-job.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: flink-pyjob-submitter
  namespace: {{ .Values.global.namespace }}
  annotations:
    "helm.sh/hook": post-install,post-upgrade
    "helm.sh/hook-weight": "0"
    "helm.sh/hook-delete-policy": hook-succeeded
spec:
  backoffLimit: 3
  template:
    spec:
      restartPolicy: OnFailure
      containers:
        - name: submitter
          image: {{ include "aispm.image" .Values.images.flinkJob }}
          entrypoint: ["/opt/flink-pyjob/submit.sh"]
          env:
            - name: FLINK_JM_URL
              value: "http://flink-jobmanager.{{ .Values.global.namespace }}.svc.cluster.local:8081"
            - name: KAFKA_BOOTSTRAP_SERVERS
              valueFrom:
                configMapKeyRef:
                  name: platform-env
                  key: KAFKA_BOOTSTRAP_SERVERS
            - name: CEP_TENANT_IDS
              value: "t1"
```

- [ ] **Step 5: Add Flink services to services.yaml**

```yaml
# Append:
---
apiVersion: v1
kind: Service
metadata:
  name: flink-jobmanager
  namespace: {{ .Values.global.namespace }}
spec:
  selector: { app: flink-jobmanager }
  ports:
    - name: rest
      port: 8081
    - name: rpc
      port: 6123
```

- [ ] **Step 6: Verify Flink reaches Ready state**

```bash
helm upgrade --install aispm deploy/helm/aispm/ -n aispm \
  --set secrets.spmDbPassword=testpass
kubectl -n aispm rollout status statefulset/flink-jobmanager
kubectl -n aispm rollout status deploy/flink-taskmanager
kubectl -n aispm get jobs flink-pyjob-submitter
```

- [ ] **Step 7: Commit**

```bash
git add deploy/helm/aispm/templates/flink-*.yaml
git commit -m "feat(helm): Flink JobManager StatefulSet + TaskManager Deployment + submitter Job"
```

---

## Task 10: SPM API, spm-mcp, spm-llm-proxy, spm-aggregator Deployments
**Effort:** M (1.5 h)

**Files:**
- Create: `deploy/helm/aispm/templates/spm-api-deployment.yaml`
- Create: `deploy/helm/aispm/templates/spm-mcp-deployment.yaml`
- Create: `deploy/helm/aispm/templates/spm-llm-proxy-deployment.yaml`
- Create: `deploy/helm/aispm/templates/spm-aggregator-deployment.yaml`
- Create: `deploy/k8s/storage/spm-api-models-pvc.yaml`

The spm-api Deployment gets the `spm-api` ServiceAccount (from Task 3) so its pod carries the token needed to create Pods in `aispm-agents`.

- [ ] **Step 1: spm-api PVC for uploaded models**

```yaml
# deploy/k8s/storage/spm-api-models-pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: spm-api-models
  namespace: aispm
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: longhorn
  resources:
    requests:
      storage: 5Gi
```

- [ ] **Step 2: spm-api Deployment**

```yaml
# deploy/helm/aispm/templates/spm-api-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: spm-api
  namespace: {{ .Values.global.namespace }}
spec:
  replicas: 1
  selector:
    matchLabels: { app: spm-api }
  template:
    metadata:
      labels: { app: spm-api }
    spec:
      serviceAccountName: spm-api   # grants Pod RBAC in aispm-agents
      containers:
        - name: spm-api
          image: {{ include "aispm.image" .Values.images.spmApi }}
          imagePullPolicy: {{ .Values.global.imagePullPolicy }}
          ports:
            - containerPort: 8092
          envFrom:
            - configMapRef:
                name: platform-env
            - secretRef:
                name: platform-secrets
          env:
            - name: SPM_DB_URL
              value: "postgresql+asyncpg://{{ .Values.spmDb.user }}:$(SPM_DB_PASSWORD)@spm-db.{{ .Values.global.namespace }}.svc.cluster.local:5432/{{ .Values.spmDb.database }}"
            - name: FREEZE_CONTROLLER_URL
              value: "http://freeze-controller.{{ .Values.global.namespace }}.svc.cluster.local:8090"
            - name: CPM_API_URL
              value: "http://api.{{ .Values.global.namespace }}.svc.cluster.local:8080"
            - name: POLICY_SIMULATOR_URL
              value: "http://policy-simulator.{{ .Values.global.namespace }}.svc.cluster.local:8091"
            - name: MODEL_UPLOAD_DIR
              value: /app/models
            # Agent runtime — k8s backend
            - name: AGENT_POD_NAMESPACE
              value: {{ .Values.agentRuntime.namespace }}
            - name: AGENT_RUNTIME_IMAGE
              value: {{ include "aispm.image" .Values.images.agentRuntime }}
            - name: AGENT_RUNTIME_CLASS
              value: {{ .Values.agentRuntime.runtimeClassName }}
          volumeMounts:
            - name: jwt-keys
              mountPath: /keys
              readOnly: true
            - name: models
              mountPath: /app/models
          readinessProbe:
            httpGet: { path: /health, port: 8092 }
            initialDelaySeconds: 20
            periodSeconds: 10
          livenessProbe:
            httpGet: { path: /health, port: 8092 }
            initialDelaySeconds: 40
            periodSeconds: 15
      volumes:
        - name: jwt-keys
          secret:
            secretName: jwt-keys
            defaultMode: 0444
        - name: models
          persistentVolumeClaim:
            claimName: spm-api-models
```

Note: `AGENT_CODE_HOST_DIR` is no longer used. The k8s backend (Task 11) stores code in ConfigMaps, not bind-mounts.

- [ ] **Step 3: spm-mcp Deployment**

```yaml
# deploy/helm/aispm/templates/spm-mcp-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: spm-mcp
  namespace: {{ .Values.global.namespace }}
spec:
  replicas: 1
  selector:
    matchLabels: { app: spm-mcp }
  template:
    metadata:
      labels: { app: spm-mcp }
    spec:
      containers:
        - name: spm-mcp
          image: {{ include "aispm.image" .Values.images.spmMcp }}
          ports:
            - containerPort: 8500
          envFrom:
            - configMapRef:
                name: platform-env
            - secretRef:
                name: platform-secrets
          env:
            - name: SPM_DB_URL
              value: "postgresql+asyncpg://{{ .Values.spmDb.user }}:$(SPM_DB_PASSWORD)@spm-db.{{ .Values.global.namespace }}.svc.cluster.local:5432/{{ .Values.spmDb.database }}"
          readinessProbe:
            httpGet: { path: /health, port: 8500 }
            initialDelaySeconds: 10
            periodSeconds: 10
```

- [ ] **Step 4: spm-llm-proxy Deployment (same pattern as spm-mcp, port 8500)**

Copy spm-mcp template, substitute `spm-llm-proxy` everywhere, keep port 8500.

- [ ] **Step 5: spm-aggregator Deployment**

Same pattern; add `SPM_API_URL: http://spm-api.aispm.svc.cluster.local:8092`.

- [ ] **Step 6: Add services for all four to services.yaml**

```yaml
# Append to services.yaml:
---
apiVersion: v1
kind: Service
metadata:
  name: spm-api
  namespace: {{ .Values.global.namespace }}
spec:
  selector: { app: spm-api }
  ports:
    - port: 8092
---
apiVersion: v1
kind: Service
metadata:
  name: spm-mcp
  namespace: {{ .Values.global.namespace }}
spec:
  selector: { app: spm-mcp }
  ports:
    - port: 8500
---
apiVersion: v1
kind: Service
metadata:
  name: spm-llm-proxy
  namespace: {{ .Values.global.namespace }}
spec:
  selector: { app: spm-llm-proxy }
  ports:
    - port: 8500
---
apiVersion: v1
kind: Service
metadata:
  name: spm-aggregator
  namespace: {{ .Values.global.namespace }}
spec:
  selector: { app: spm-aggregator }
  ports:
    - port: 80
```

- [ ] **Step 7: Apply PVC + deploy**

```bash
kubectl apply -f deploy/k8s/storage/spm-api-models-pvc.yaml
helm upgrade --install aispm deploy/helm/aispm/ -n aispm \
  --set secrets.spmDbPassword=testpass
kubectl -n aispm rollout status deploy/spm-api
kubectl -n aispm rollout status deploy/spm-mcp
kubectl -n aispm rollout status deploy/spm-llm-proxy
```

- [ ] **Step 8: Commit**

```bash
git add deploy/helm/aispm/templates/spm-*.yaml \
        deploy/k8s/storage/spm-api-models-pvc.yaml
git commit -m "feat(helm): spm-api (with SA), spm-mcp, spm-llm-proxy, spm-aggregator Deployments"
```

---

## Task 11: agent-orchestrator, threat-hunting-agent, UI + Ingress
**Effort:** M (1.5 h)

**Files:**
- Create: `deploy/helm/aispm/templates/agent-orchestrator-deployment.yaml`
- Create: `deploy/helm/aispm/templates/threat-hunting-agent-deployment.yaml`
- Create: `deploy/helm/aispm/templates/ui-deployment.yaml`
- Create: `deploy/helm/aispm/templates/ui-ingress.yaml`
- Create: `deploy/k8s/ingress/cert-manager-clusterissuer.yaml`

- [ ] **Step 0: Check whether agent-orchestrator still uses SQLite**

```bash
grep -r "sqlite\|DB_PATH\|agent_orchestrator.db" \
  services/agent-orchestrator-service/ --include="*.py" -l
```

If any files reference SQLite/DB_PATH, add a 1Gi Longhorn PVC:

```yaml
# deploy/helm/aispm/templates/agent-orchestrator-pvc.yaml  (create if needed)
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: agent-orchestrator-data
  namespace: {{ .Values.global.namespace }}
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: longhorn
  resources:
    requests:
      storage: 1Gi
```

And mount it at `/data` in the Deployment below, with `DB_PATH: /data/agent_orchestrator.db`.
If the grep shows no SQLite usage (it uses `POLICY_DB_URL` only), skip the PVC.

- [ ] **Step 1: agent-orchestrator Deployment**

```yaml
# deploy/helm/aispm/templates/agent-orchestrator-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: agent-orchestrator
  namespace: {{ .Values.global.namespace }}
spec:
  replicas: 1
  selector:
    matchLabels: { app: agent-orchestrator }
  template:
    metadata:
      labels: { app: agent-orchestrator }
    spec:
      containers:
        - name: agent-orchestrator
          image: {{ include "aispm.image" .Values.images.agentOrchestrator }}
          ports:
            - containerPort: 8094
          env:
            - name: LOG_LEVEL
              value: INFO
            - name: KAFKA_BOOTSTRAP_SERVERS
              valueFrom:
                configMapKeyRef:
                  name: platform-env
                  key: KAFKA_BOOTSTRAP_SERVERS
            - name: POLICY_DB_URL
              value: "postgresql+psycopg2://{{ .Values.spmDb.user }}:$(SPM_DB_PASSWORD)@spm-db.{{ .Values.global.namespace }}.svc.cluster.local:5432/{{ .Values.spmDb.database }}"
          envFrom:
            - secretRef:
                name: platform-secrets
          readinessProbe:
            httpGet: { path: /health, port: 8094 }
            initialDelaySeconds: 15
            periodSeconds: 10
```

Note: the compose version used a SQLite file at `DB_PATH: /data/agent_orchestrator.db`. In k8s this is replaced by the Postgres URL. Verify the agent-orchestrator service uses the `POLICY_DB_URL` for all state; if it still uses SQLite for local state add a Longhorn PVC (`agent-orchestrator-pvc.yaml`) and mount it at `/data`.

- [ ] **Step 2: threat-hunting-agent Deployment**

```yaml
# deploy/helm/aispm/templates/threat-hunting-agent-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: threat-hunting-agent
  namespace: {{ .Values.global.namespace }}
spec:
  replicas: 1
  selector:
    matchLabels: { app: threat-hunting-agent }
  template:
    metadata:
      labels: { app: threat-hunting-agent }
    spec:
      containers:
        - name: threat-hunting-agent
          image: {{ include "aispm.image" .Values.images.threatHunter }}
          ports:
            - containerPort: 8095
          envFrom:
            - configMapRef:
                name: platform-env
            - secretRef:
                name: platform-secrets
          env:
            - name: ORCHESTRATOR_URL
              value: "http://agent-orchestrator.{{ .Values.global.namespace }}.svc.cluster.local:8094"
            - name: PLATFORM_API_URL
              value: "http://api.{{ .Values.global.namespace }}.svc.cluster.local:8080"
            - name: SPM_DB_URL
              value: "postgresql://{{ .Values.spmDb.user }}:$(SPM_DB_PASSWORD)@spm-db.{{ .Values.global.namespace }}.svc.cluster.local:5432/{{ .Values.spmDb.database }}"
          readinessProbe:
            httpGet: { path: /health, port: 8095 }
            initialDelaySeconds: 20
            periodSeconds: 15
```

- [ ] **Step 3: UI Deployment**

```yaml
# deploy/helm/aispm/templates/ui-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ui
  namespace: {{ .Values.global.namespace }}
spec:
  replicas: 1
  selector:
    matchLabels: { app: ui }
  template:
    metadata:
      labels: { app: ui }
    spec:
      containers:
        - name: ui
          image: {{ include "aispm.image" .Values.images.ui }}
          ports:
            - containerPort: 3001
```

- [ ] **Step 4: cert-manager ClusterIssuer (Let's Encrypt)**

```yaml
# deploy/k8s/ingress/cert-manager-clusterissuer.yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: {{ .Values.ingress.letsencryptEmail }}
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
      - http01:
          ingress:
            class: nginx
```

```bash
kubectl apply -f deploy/k8s/ingress/cert-manager-clusterissuer.yaml
```

- [ ] **Step 5: Ingress template**

```yaml
# deploy/helm/aispm/templates/ui-ingress.yaml
{{- if .Values.ingress.enabled }}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: aispm
  namespace: {{ .Values.global.namespace }}
  annotations:
    kubernetes.io/ingress.class: {{ .Values.ingress.className }}
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/proxy-read-timeout: "300"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "300"
spec:
  tls:
    - hosts:
        - {{ .Values.ingress.host }}
      secretName: {{ .Values.ingress.tlsSecretName }}
  rules:
    - host: {{ .Values.ingress.host }}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: ui
                port:
                  number: 3001
          - path: /api
            pathType: Prefix
            backend:
              service:
                name: api
                port:
                  number: 8080
          - path: /api/spm
            pathType: Prefix
            backend:
              service:
                name: spm-api
                port:
                  number: 8092
{{- end }}
```

- [ ] **Step 6: Deploy and verify**

```bash
helm upgrade --install aispm deploy/helm/aispm/ -n aispm \
  --set secrets.spmDbPassword=testpass \
  --set ingress.host=aispm.yourdomain.com
kubectl -n aispm rollout status deploy/agent-orchestrator
kubectl -n aispm rollout status deploy/threat-hunting-agent
kubectl -n aispm rollout status deploy/ui
kubectl -n aispm get ingress aispm
```

- [ ] **Step 7: Commit**

```bash
git add deploy/helm/aispm/templates/agent-orchestrator*.yaml \
        deploy/helm/aispm/templates/threat-hunting-agent*.yaml \
        deploy/helm/aispm/templates/ui-*.yaml \
        deploy/k8s/ingress/
git commit -m "feat(helm): agent-orchestrator, threat-hunting-agent, UI Deployment + Ingress + TLS"
```

---

## Task 12: Prometheus + Grafana Deployments
**Effort:** S (1 h)

**Files:**
- Create: `deploy/helm/aispm/templates/prometheus-deployment.yaml`
- Create: `deploy/helm/aispm/templates/grafana-deployment.yaml`
- Create: `deploy/helm/aispm/templates/prometheus-configmap.yaml`

- [ ] **Step 1: Prometheus ConfigMap from existing prometheus.yml**

```bash
kubectl create configmap prometheus-config \
  --from-file=prometheus.yml=prometheus/prometheus.yml \
  -n aispm --dry-run=client -o yaml \
  > deploy/helm/aispm/templates/prometheus-configmap.yaml
# Add namespace: {{ .Values.global.namespace }}
```

- [ ] **Step 2: Prometheus Deployment + PVC**

```yaml
# deploy/helm/aispm/templates/prometheus-deployment.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: prometheus-data
  namespace: {{ .Values.global.namespace }}
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: longhorn
  resources:
    requests:
      storage: {{ .Values.prometheus.storage }}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: prometheus
  namespace: {{ .Values.global.namespace }}
spec:
  replicas: 1
  selector:
    matchLabels: { app: prometheus }
  template:
    metadata:
      labels: { app: prometheus }
    spec:
      containers:
        - name: prometheus
          image: prom/prometheus:v2.55.1
          args:
            - --config.file=/etc/prometheus/prometheus.yml
            - --storage.tsdb.path=/prometheus
          ports:
            - containerPort: 9090
          volumeMounts:
            - name: config
              mountPath: /etc/prometheus/prometheus.yml
              subPath: prometheus.yml
            - name: data
              mountPath: /prometheus
          readinessProbe:
            httpGet: { path: /-/healthy, port: 9090 }
            initialDelaySeconds: 10
            periodSeconds: 10
      volumes:
        - name: config
          configMap:
            name: prometheus-config
        - name: data
          persistentVolumeClaim:
            claimName: prometheus-data
```

- [ ] **Step 3: Grafana Deployment**

```yaml
# deploy/helm/aispm/templates/grafana-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: grafana
  namespace: {{ .Values.global.namespace }}
spec:
  replicas: 1
  selector:
    matchLabels: { app: grafana }
  template:
    metadata:
      labels: { app: grafana }
    spec:
      containers:
        - name: grafana
          image: grafana/grafana:11.4.0
          ports:
            - containerPort: 3000
          env:
            - name: GF_SECURITY_ADMIN_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: platform-secrets
                  key: GRAFANA_ADMIN_PASSWORD
            - name: GF_AUTH_ANONYMOUS_ENABLED
              value: "false"
          volumeMounts:
            - name: provisioning
              mountPath: /etc/grafana/provisioning
            - name: dashboards
              mountPath: /var/lib/grafana/dashboards
            - name: data
              mountPath: /var/lib/grafana
      volumes:
        - name: provisioning
          configMap:
            name: grafana-provisioning
        - name: dashboards
          configMap:
            name: grafana-dashboards
        - name: data
          persistentVolumeClaim:
            claimName: grafana-data
```

Create `grafana-provisioning` and `grafana-dashboards` ConfigMaps from the `grafana/` directory the same way as the prometheus config above.

- [ ] **Step 4: Add Prometheus + Grafana to services.yaml**

```yaml
---
apiVersion: v1
kind: Service
metadata:
  name: prometheus
  namespace: {{ .Values.global.namespace }}
spec:
  selector: { app: prometheus }
  ports:
    - port: 9090
---
apiVersion: v1
kind: Service
metadata:
  name: grafana
  namespace: {{ .Values.global.namespace }}
spec:
  selector: { app: grafana }
  ports:
    - port: 3000
```

- [ ] **Step 5: Commit**

```bash
git add deploy/helm/aispm/templates/prometheus-*.yaml \
        deploy/helm/aispm/templates/grafana-*.yaml
git commit -m "feat(helm): Prometheus and Grafana Deployments with Longhorn PVCs"
```

---

## Task 13: agent_controller.py Rewrite — Docker SDK → Kubernetes Python Client
**Effort:** XL (4 h — highest-risk task; includes TDD)

This is the core of the migration. Replace all `docker.from_env()` calls with the `kubernetes` Python client. The agent code is stored in a per-agent ConfigMap instead of a host bind-mount.

**Files:**
- Modify: `services/spm_api/agent_controller.py`
- Modify: `services/spm_api/requirements.txt`
- Create: `tests/spm_api/test_agent_controller_k8s.py`

- [ ] **Step 1: Add kubernetes to requirements**

```
# services/spm_api/requirements.txt — append:
kubernetes==29.*
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/spm_api/test_agent_controller_k8s.py
"""Unit tests for the Kubernetes backend of agent_controller.

Uses unittest.mock to patch kubernetes.client so no cluster is needed.
"""
from __future__ import annotations
import os
import pytest
from unittest.mock import MagicMock, patch, call


@pytest.fixture(autouse=True)
def k8s_env(monkeypatch):
    monkeypatch.setenv("AGENT_POD_NAMESPACE", "aispm-agents")
    monkeypatch.setenv("AGENT_RUNTIME_IMAGE", "aispm-agent-runtime:latest")
    monkeypatch.setenv("AGENT_RUNTIME_CLASS", "kata")
    monkeypatch.setenv("AGENT_CONTROLLER_URL", "http://spm-api.aispm.svc.cluster.local:8092")


def _make_k8s_mocks():
    core = MagicMock()
    # create_namespaced_config_map and create_namespaced_pod return mock objects
    core.create_namespaced_config_map.return_value = MagicMock()
    core.create_namespaced_pod.return_value = MagicMock(metadata=MagicMock(name="agent-test-id"))
    core.delete_namespaced_pod.return_value = MagicMock()
    core.delete_namespaced_config_map.return_value = MagicMock()
    return core


@pytest.mark.asyncio
async def test_spawn_agent_pod_creates_configmap_and_pod():
    """spawn_agent_pod should create a ConfigMap for agent code and a Pod."""
    core = _make_k8s_mocks()
    with patch("agent_controller._k8s_core_client", return_value=core):
        from agent_controller import spawn_agent_pod
        pod_name = await spawn_agent_pod(
            agent_id="test-id",
            tenant_id="t1",
            mcp_token="tok123",
            code_blob="print('hello')",
        )

    assert pod_name == "agent-test-id"
    # ConfigMap created with agent code
    core.create_namespaced_config_map.assert_called_once()
    cm_call = core.create_namespaced_config_map.call_args
    assert cm_call.kwargs["namespace"] == "aispm-agents"
    body = cm_call.kwargs["body"]
    assert body.data["agent.py"] == "print('hello')"
    assert body.metadata.name == "agent-code-test-id"
    # Pod created
    core.create_namespaced_pod.assert_called_once()
    pod_call = core.create_namespaced_pod.call_args
    assert pod_call.kwargs["namespace"] == "aispm-agents"
    pod_spec = pod_call.kwargs["body"].spec
    assert pod_spec.runtime_class_name == "kata"
    assert pod_spec.service_account_name == "agent-runtime"
    container = pod_spec.containers[0]
    env_names = {e.name: e.value for e in container.env}
    assert env_names["AGENT_ID"] == "test-id"
    assert env_names["MCP_TOKEN"] == "tok123"
    # Volume mount for agent code
    assert any(vm.mount_path == "/agent/agent.py" for vm in container.volume_mounts)


@pytest.mark.asyncio
async def test_spawn_agent_pod_removes_stale_pod():
    """spawn_agent_pod should delete any existing pod with the same name first."""
    import kubernetes.client.exceptions as k8s_exc

    core = _make_k8s_mocks()
    # Simulate stale pod existing
    existing = MagicMock()
    existing.status.phase = "Running"
    core.read_namespaced_pod.return_value = existing

    with patch("agent_controller._k8s_core_client", return_value=core):
        from agent_controller import spawn_agent_pod
        await spawn_agent_pod(
            agent_id="test-id", tenant_id="t1",
            mcp_token="tok",
            code_blob="pass",
        )

    core.delete_namespaced_pod.assert_called()


@pytest.mark.asyncio
async def test_stop_agent_pod_deletes_pod_and_configmap():
    core = _make_k8s_mocks()
    with patch("agent_controller._k8s_core_client", return_value=core):
        from agent_controller import stop_agent_pod
        await stop_agent_pod("test-id")

    core.delete_namespaced_pod.assert_called_once_with(
        name="agent-test-id",
        namespace="aispm-agents",
        grace_period_seconds=10,
    )
    core.delete_namespaced_config_map.assert_called_once()


@pytest.mark.asyncio
async def test_stop_agent_pod_is_noop_when_not_found():
    """stop_agent_pod should not raise if the pod doesn't exist."""
    import kubernetes.client.exceptions as k8s_exc

    core = _make_k8s_mocks()
    core.delete_namespaced_pod.side_effect = k8s_exc.ApiException(status=404)

    with patch("agent_controller._k8s_core_client", return_value=core):
        from agent_controller import stop_agent_pod
        await stop_agent_pod("missing-id")   # should not raise


@pytest.mark.asyncio
async def test_resource_limits_applied():
    """Pod containers must have cpu + memory resource limits."""
    core = _make_k8s_mocks()
    with patch("agent_controller._k8s_core_client", return_value=core):
        from agent_controller import spawn_agent_pod
        await spawn_agent_pod(
            agent_id="res-id", tenant_id="t1",
            mcp_token="t",
            code_blob="pass",
            mem_mb=256, cpu_millicores=250,
        )

    pod_call = core.create_namespaced_pod.call_args
    container = pod_call.kwargs["body"].spec.containers[0]
    assert container.resources.limits["memory"] == "256Mi"
    assert container.resources.limits["cpu"] == "250m"
```

- [ ] **Step 3: Run tests to confirm they fail**

```bash
cd /Users/danyshapiro/PycharmProjects/AISPM
pip install kubernetes==29.* --break-system-packages
pytest tests/spm_api/test_agent_controller_k8s.py -v
```

Expected: `ImportError: cannot import name 'spawn_agent_pod' from 'agent_controller'`

- [ ] **Step 4: Implement the Kubernetes backend in agent_controller.py**

Replace the Docker sections (sections 3 and part of 4) with the following, keeping all other functions (`mint_agent_tokens`, `create_agent_topics`, `delete_agent_topics`, `deploy_agent`, `start_agent`, `stop_agent`, `retire_agent`) intact but updating their calls from `spawn_agent_container` / `stop_agent_container` to `spawn_agent_pod` / `stop_agent_pod`.

```python
# ─── 3. Kubernetes Pod spawn / stop ────────────────────────────────────────
# Replaces the Docker SDK backend. The agent_controller no longer needs the
# Docker socket. It talks to the Kubernetes API via the in-cluster service
# account token (or KUBECONFIG when running outside the cluster for tests).

import os
from typing import Optional, Tuple

_AGENT_POD_NAMESPACE  = os.environ.get("AGENT_POD_NAMESPACE",  "aispm-agents")
_AGENT_IMAGE          = os.environ.get("AGENT_RUNTIME_IMAGE",  "aispm-agent-runtime:latest")
_AGENT_RUNTIME_CLASS  = os.environ.get("AGENT_RUNTIME_CLASS",  "kata")
_AGENT_CONTROLLER_URL = os.environ.get(
    "AGENT_CONTROLLER_URL", "http://spm-api.aispm.svc.cluster.local:8092"
)


def _k8s_core_client():
    """Return a configured kubernetes CoreV1Api.

    Tries in-cluster config first (running inside a Pod); falls back to
    KUBECONFIG for local development and testing.
    """
    from kubernetes import client, config  # type: ignore
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.CoreV1Api()


async def spawn_agent_pod(
    *,
    agent_id: str,
    tenant_id: str,
    mcp_token: str,
    code_blob: Optional[str] = None,
    mem_mb: int = 512,
    cpu_millicores: int = 500,
) -> str:
    """Create a ConfigMap for agent.py source, then spawn a Pod.

    Returns the pod name ("agent-{agent_id}").

    Note: llm_api_key is intentionally absent — the agent SDK fetches it
    from the controller's GET /agents/{id}/bootstrap endpoint at startup,
    same as in the Docker backend. Not passing it here avoids leaking it
    into the Pod env.

    ConfigMap size: agent.py is stored as a k8s ConfigMap data entry.
    Kubernetes ConfigMaps have a 1 MiB data limit. Agent scripts that
    embed large inline data (base64 assets, training data, etc.) will
    fail silently at create_namespaced_config_map with a 422 error —
    check logs if deploy hangs at "starting" state.

    Kata isolation: each Pod gets runtimeClassName=kata so containerd
    launches it in a Firecracker/QEMU microVM. The agent has no direct
    internet egress — NetworkPolicy (Task 14) restricts it to spm-mcp,
    spm-llm-proxy, Kafka, and spm-api only.

    Idempotent: any existing pod/configmap with the same names is deleted
    before creating fresh ones.
    """
    from kubernetes import client  # type: ignore

    k8s  = _k8s_core_client()
    ns   = _AGENT_POD_NAMESPACE
    pod_name = f"agent-{agent_id}"
    cm_name  = f"agent-code-{agent_id}"

    # 1. Delete stale pod (idempotency) — 10s grace to match Docker backend behavior
    try:
        k8s.delete_namespaced_pod(
            name=pod_name, namespace=ns, grace_period_seconds=10
        )
        log.info("spawn_agent_pod: removed stale pod %s", pod_name)
    except client.exceptions.ApiException as e:
        if e.status != 404:
            log.warning("spawn_agent_pod: error deleting stale pod %s: %s", pod_name, e)

    # 2. Delete stale ConfigMap (idempotency)
    try:
        k8s.delete_namespaced_config_map(name=cm_name, namespace=ns)
    except client.exceptions.ApiException as e:
        if e.status != 404:
            log.warning("spawn_agent_pod: error deleting stale CM %s: %s", cm_name, e)

    # 3. Create ConfigMap with agent source code
    cm = client.V1ConfigMap(
        metadata=client.V1ObjectMeta(
            name=cm_name,
            namespace=ns,
            labels={"app": "agent-runtime", "agent-id": agent_id,
                    "tenant-id": tenant_id},
        ),
        data={"agent.py": code_blob or "# empty agent"},
    )
    k8s.create_namespaced_config_map(namespace=ns, body=cm)

    # 4. Create Pod
    pod = client.V1Pod(
        metadata=client.V1ObjectMeta(
            name=pod_name,
            namespace=ns,
            labels={
                "app":       "agent-runtime",
                "agent-id":  agent_id,
                "tenant-id": tenant_id,
                "role":      "agent-runtime",  # targeted by NetworkPolicy
            },
        ),
        spec=client.V1PodSpec(
            runtime_class_name=_AGENT_RUNTIME_CLASS,
            restart_policy="OnFailure",
            service_account_name="agent-runtime",  # no cluster permissions
            automount_service_account_token=False,
            containers=[
                client.V1Container(
                    name="agent",
                    image=_AGENT_IMAGE,
                    image_pull_policy="IfNotPresent",
                    env=[
                        client.V1EnvVar(name="AGENT_ID",       value=agent_id),
                        client.V1EnvVar(name="MCP_TOKEN",      value=mcp_token),
                        client.V1EnvVar(name="CONTROLLER_URL", value=_AGENT_CONTROLLER_URL),
                    ],
                    resources=client.V1ResourceRequirements(
                        requests={"memory": f"{mem_mb}Mi", "cpu": f"{cpu_millicores}m"},
                        limits={  "memory": f"{mem_mb}Mi", "cpu": f"{cpu_millicores}m"},
                    ),
                    volume_mounts=[
                        client.V1VolumeMount(
                            name="agent-code",
                            mount_path="/agent/agent.py",
                            sub_path="agent.py",
                            read_only=True,
                        )
                    ],
                    security_context=client.V1SecurityContext(
                        run_as_non_root=True,
                        run_as_user=1000,
                        allow_privilege_escalation=False,
                        read_only_root_filesystem=True,
                    ),
                )
            ],
            volumes=[
                client.V1Volume(
                    name="agent-code",
                    config_map=client.V1ConfigMapVolumeSource(name=cm_name),
                )
            ],
        ),
    )
    result = k8s.create_namespaced_pod(namespace=ns, body=pod)
    log.info("spawn_agent_pod: created pod %s in %s", pod_name, ns)
    return result.metadata.name


async def stop_agent_pod(agent_id: str) -> None:
    """Stop (delete) the agent's Pod and its code ConfigMap.

    No-op if either resource is already gone.
    """
    from kubernetes import client  # type: ignore

    k8s      = _k8s_core_client()
    ns       = _AGENT_POD_NAMESPACE
    pod_name = f"agent-{agent_id}"
    cm_name  = f"agent-code-{agent_id}"

    try:
        k8s.delete_namespaced_pod(
            name=pod_name, namespace=ns, grace_period_seconds=10
        )
    except client.exceptions.ApiException as e:
        if e.status == 404:
            log.info("stop_agent_pod: pod %s not found (no-op)", pod_name)
        else:
            raise

    try:
        k8s.delete_namespaced_config_map(name=cm_name, namespace=ns)
    except client.exceptions.ApiException as e:
        if e.status != 404:
            log.warning("stop_agent_pod: CM delete failed for %s: %s", cm_name, e)
```

Update the high-level orchestration functions (`deploy_agent`, `start_agent`, `stop_agent`, `retire_agent`) to call `spawn_agent_pod` / `stop_agent_pod` instead of the old Docker functions:

```python
# In deploy_agent — replace spawn_agent_container(...) with:
await spawn_agent_pod(
    agent_id=str(a.id), tenant_id=a.tenant_id,
    mcp_token=a.mcp_token,
    # llm_api_key intentionally omitted — agent SDK fetches it via bootstrap endpoint
    code_blob=getattr(a, "code_blob", None),
    mem_mb=512, cpu_millicores=500,
)

# In start_agent — same substitution.
# In stop_agent  — replace stop_agent_container(str(a.id)) with:
await stop_agent_pod(str(a.id))

# In retire_agent — same substitution for stop call.
```

Also remove `_resolve_host_code_path`, `_ensure_code_on_disk`, `_docker_client`, `spawn_agent_container`, `stop_agent_container`, and the `_AGENT_NETWORK` / `_AGENT_CODE_HOST_DIR` constants — they're Docker-specific and no longer needed.

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/spm_api/test_agent_controller_k8s.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Run existing agent_controller tests to ensure nothing regressed**

```bash
pytest services/spm_api/tests/test_agent_controller.py -v
```

If the existing tests mock `docker.from_env`, update them to mock `agent_controller._k8s_core_client` instead, or mark them as docker-backend-only and skip.

- [ ] **Step 7: Commit**

```bash
git add services/spm_api/agent_controller.py \
        services/spm_api/requirements.txt \
        tests/spm_api/test_agent_controller_k8s.py
git commit -m "feat(agent-ctrl): rewrite Docker SDK → Kubernetes client; Kata Pod + ConfigMap backend"
```

---

## Task 14: NetworkPolicy — Agent Pod Isolation
**Effort:** M (1.5 h)

Every agent Pod runs in `aispm-agents` and must only be able to reach spm-mcp (port 8500), spm-llm-proxy (port 8500), Kafka (port 9092), and spm-api (port 8092).

**Files:**
- Create: `deploy/k8s/network-policies/agent-default-deny.yaml`
- Create: `deploy/k8s/network-policies/agent-allow-egress.yaml`
- Create: `deploy/helm/aispm/templates/agent-networkpolicy.yaml`

- [ ] **Step 1: Default-deny all ingress and egress in aispm-agents**

```yaml
# deploy/k8s/network-policies/agent-default-deny.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: aispm-agents
spec:
  podSelector: {}   # all pods in namespace
  policyTypes:
    - Ingress
    - Egress
```

- [ ] **Step 2: Allow egress from agent Pods to the four permitted services**

```yaml
# deploy/k8s/network-policies/agent-allow-egress.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: agent-allow-egress
  namespace: aispm-agents
spec:
  podSelector:
    matchLabels:
      role: agent-runtime
  policyTypes:
    - Egress
  egress:
    # spm-mcp (port 8500)
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: aispm
          podSelector:
            matchLabels:
              app: spm-mcp
      ports:
        - protocol: TCP
          port: 8500
    # spm-llm-proxy (port 8500)
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: aispm
          podSelector:
            matchLabels:
              app: spm-llm-proxy
      ports:
        - protocol: TCP
          port: 8500
    # Kafka broker (port 9092)
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: aispm
          podSelector:
            matchLabels:
              app: kafka
      ports:
        - protocol: TCP
          port: 9092
    # spm-api — ready() handshake + secrets endpoint (port 8092)
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: aispm
          podSelector:
            matchLabels:
              app: spm-api
      ports:
        - protocol: TCP
          port: 8092
    # DNS (required for all DNS resolution inside the cluster)
    - ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
```

- [ ] **Step 3: Apply policies**

```bash
kubectl apply -f deploy/k8s/network-policies/
kubectl get networkpolicies -n aispm-agents
```

- [ ] **Step 4: Verify isolation with a test pod**

```bash
# Launch a test pod with role=agent-runtime and try to reach google.com — should fail
kubectl run test-isolation --image=curlimages/curl:8.6.0 \
  -n aispm-agents \
  --labels="role=agent-runtime" \
  --restart=Never \
  --command -- curl -m 5 https://google.com

kubectl logs test-isolation -n aispm-agents
# Expected: "curl: (28) Operation timed out" or connection refused

# Now reach spm-mcp — should succeed (if spm-mcp is running)
kubectl run test-mcp --image=curlimages/curl:8.6.0 \
  -n aispm-agents \
  --labels="role=agent-runtime" \
  --restart=Never \
  --command -- curl -m 5 http://spm-mcp.aispm.svc.cluster.local:8500/health

kubectl logs test-mcp -n aispm-agents
# Expected: {"status":"ok"}

kubectl delete pod test-isolation test-mcp -n aispm-agents
```

- [ ] **Step 5: Add network policies as a Helm template too**

Copy both YAML files into `deploy/helm/aispm/templates/agent-networkpolicy.yaml` (combine into one file with `---` separator) and add `namespace: {{ .Values.agentRuntime.namespace }}` to each metadata block.

- [ ] **Step 6: Commit**

```bash
git add deploy/k8s/network-policies/ \
        deploy/helm/aispm/templates/agent-networkpolicy.yaml
git commit -m "feat(k8s): NetworkPolicy default-deny + agent-runtime egress allowlist"
```

---

## Task 15: Istio Service Mesh

**Effort:** L (3 h)

Two modes are used deliberately:
- **`aispm` namespace → sidecar mode**: Envoy proxy injected into every platform Pod. Gives full L7 visibility, mTLS, and AuthorizationPolicy enforcement between platform services.
- **`aispm-agents` namespace → Ambient mode**: No sidecar injected. Instead, a per-node `ztunnel` DaemonSet handles mTLS at L4 transparently. This avoids the complexity of injecting Envoy into a Kata microVM (the sidecar would need to run inside the microVM's own network namespace, which complicates Kata's VM boundary).

**Files:**
- Create: `deploy/istio/istio-values.yaml`
- Create: `deploy/helm/aispm/templates/istio-peerauthentication.yaml`
- Create: `deploy/helm/aispm/templates/istio-authorizationpolicies.yaml`
- Create: `deploy/helm/aispm/templates/istio-gateway.yaml`
- Create: `deploy/helm/aispm/templates/istio-virtualservices.yaml`
- Modify: `deploy/k8s/namespaces/aispm.yaml` — add `istio-injection: enabled` label
- Modify: `deploy/k8s/namespaces/aispm-agents.yaml` — add `istio.io/dataplane-mode: ambient` label

- [ ] **Step 1: Install Istio with Ambient mode support**

```bash
# Download istioctl (1.22+)
curl -L https://istio.io/downloadIstio | ISTIO_VERSION=1.22.0 sh -
export PATH=$PWD/istio-1.22.0/bin:$PATH

# Install with ambient profile (includes ztunnel DaemonSet + sidecar support)
istioctl install --set profile=ambient --set meshConfig.accessLogFile=/dev/stdout -y

# Verify control plane
kubectl -n istio-system get pods
# Expected: istiod, istio-ingressgateway, ztunnel (DaemonSet) all Running
```

Alternatively via Helm:
```bash
helm repo add istio https://istio-release.storage.googleapis.com/charts
helm repo update
helm install istio-base istio/base -n istio-system --create-namespace
helm install istiod istio/istiod -n istio-system \
  --set pilot.env.PILOT_ENABLE_AMBIENT=true \
  --wait
helm install ztunnel istio/ztunnel -n istio-system --wait
helm install istio-cni istio/cni -n istio-system --wait
```

- [ ] **Step 2: Label namespaces for the correct mode**

```yaml
# deploy/k8s/namespaces/aispm.yaml  (updated)
apiVersion: v1
kind: Namespace
metadata:
  name: aispm
  labels:
    app.kubernetes.io/managed-by: helm
    istio-injection: enabled          # sidecar mode — full L7 for platform services
```

```yaml
# deploy/k8s/namespaces/aispm-agents.yaml  (updated)
apiVersion: v1
kind: Namespace
metadata:
  name: aispm-agents
  labels:
    purpose: agent-runtime
    pod-security.kubernetes.io/enforce: restricted
    istio.io/dataplane-mode: ambient  # ztunnel handles mTLS; no sidecar in Kata VMs
```

```bash
kubectl apply -f deploy/k8s/namespaces/
kubectl get ns aispm -o jsonpath='{.metadata.labels}' | jq .
# Should show: "istio-injection": "enabled"
kubectl get ns aispm-agents -o jsonpath='{.metadata.labels}' | jq .
# Should show: "istio.io/dataplane-mode": "ambient"
```

- [ ] **Step 3: Enable STRICT mTLS for the aispm namespace**

```yaml
# deploy/helm/aispm/templates/istio-peerauthentication.yaml
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: {{ .Values.global.namespace }}
spec:
  mtls:
    mode: STRICT   # all service-to-service traffic must be mTLS; plaintext rejected
```

```bash
helm upgrade --install aispm deploy/helm/aispm/ -n aispm \
  --set secrets.spmDbPassword=testpass

# Verify mTLS is active — check sidecar injection on a running pod:
kubectl -n aispm get pod -l app=api -o jsonpath='{.items[0].spec.containers[*].name}'
# Should show: api istio-proxy
```

- [ ] **Step 4: AuthorizationPolicy — default deny + agent egress allowlist**

This works alongside (not instead of) the NetworkPolicy from Task 14. NetworkPolicy enforces at the kernel/CNI layer; AuthorizationPolicy enforces at the Istio L7 layer. Both must pass.

```yaml
# deploy/helm/aispm/templates/istio-authorizationpolicies.yaml
# Default deny all traffic within aispm-agents namespace
apiVersion: security.istio.io/v1beta1
kind: AuthorizationPolicy
metadata:
  name: deny-all-agents
  namespace: {{ .Values.agentRuntime.namespace }}
spec:
  {}   # empty spec = deny all
---
# Allow agent Pods to reach spm-mcp
apiVersion: security.istio.io/v1beta1
kind: AuthorizationPolicy
metadata:
  name: agent-allow-spm-mcp
  namespace: {{ .Values.global.namespace }}
spec:
  selector:
    matchLabels:
      app: spm-mcp
  action: ALLOW
  rules:
    - from:
        - source:
            namespaces: ["{{ .Values.agentRuntime.namespace }}"]
            principals: ["cluster.local/ns/{{ .Values.agentRuntime.namespace }}/sa/agent-runtime"]
      to:
        - operation:
            ports: ["8500"]
---
# Allow agent Pods to reach spm-llm-proxy
apiVersion: security.istio.io/v1beta1
kind: AuthorizationPolicy
metadata:
  name: agent-allow-spm-llm-proxy
  namespace: {{ .Values.global.namespace }}
spec:
  selector:
    matchLabels:
      app: spm-llm-proxy
  action: ALLOW
  rules:
    - from:
        - source:
            namespaces: ["{{ .Values.agentRuntime.namespace }}"]
            principals: ["cluster.local/ns/{{ .Values.agentRuntime.namespace }}/sa/agent-runtime"]
      to:
        - operation:
            ports: ["8500"]
---
# Allow agent Pods to call back to spm-api (ready handshake + secrets)
apiVersion: security.istio.io/v1beta1
kind: AuthorizationPolicy
metadata:
  name: agent-allow-spm-api
  namespace: {{ .Values.global.namespace }}
spec:
  selector:
    matchLabels:
      app: spm-api
  action: ALLOW
  rules:
    - from:
        - source:
            namespaces: ["{{ .Values.agentRuntime.namespace }}"]
            principals: ["cluster.local/ns/{{ .Values.agentRuntime.namespace }}/sa/agent-runtime"]
      to:
        - operation:
            paths: ["/agents/*/ready", "/agents/*/bootstrap", "/secrets/*"]
            methods: ["GET", "POST"]
---
# Allow all traffic within aispm namespace (between platform services)
apiVersion: security.istio.io/v1beta1
kind: AuthorizationPolicy
metadata:
  name: allow-intra-platform
  namespace: {{ .Values.global.namespace }}
spec:
  action: ALLOW
  rules:
    - from:
        - source:
            namespaces: ["{{ .Values.global.namespace }}"]
```

- [ ] **Step 5: Istio Gateway + VirtualServices for external traffic**

The Istio Gateway replaces the bare ingress-nginx Ingress for routing. The ingress-nginx controller remains as the external load balancer entry point but forwards to the Istio IngressGateway.

```yaml
# deploy/helm/aispm/templates/istio-gateway.yaml
{{- if .Values.ingress.enabled }}
apiVersion: networking.istio.io/v1beta1
kind: Gateway
metadata:
  name: aispm-gateway
  namespace: {{ .Values.global.namespace }}
spec:
  selector:
    istio: ingressgateway
  servers:
    - port:
        number: 443
        name: https
        protocol: HTTPS
      tls:
        mode: SIMPLE
        credentialName: {{ .Values.ingress.tlsSecretName }}   # same cert-manager secret as Task 11
      hosts:
        - {{ .Values.ingress.host }}
    - port:
        number: 80
        name: http
        protocol: HTTP
      hosts:
        - {{ .Values.ingress.host }}
      tls:
        httpsRedirect: true
{{- end }}
```

```yaml
# deploy/helm/aispm/templates/istio-virtualservices.yaml
{{- if .Values.ingress.enabled }}
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: aispm-ui
  namespace: {{ .Values.global.namespace }}
spec:
  hosts:
    - {{ .Values.ingress.host }}
  gateways:
    - aispm-gateway
  http:
    # /api/spm/* → spm-api
    - match:
        - uri:
            prefix: /api/spm
      route:
        - destination:
            host: spm-api
            port:
              number: 8092
    # /api/* → CPM api
    - match:
        - uri:
            prefix: /api
      route:
        - destination:
            host: api
            port:
              number: 8080
    # /ws/* → CPM api WebSocket
    - match:
        - uri:
            prefix: /ws
      route:
        - destination:
            host: api
            port:
              number: 8080
      websocketUpgrade: true
    # / → UI
    - match:
        - uri:
            prefix: /
      route:
        - destination:
            host: ui
            port:
              number: 3001
{{- end }}
```

- [ ] **Step 6: Install Kiali (mesh observability)**

```bash
kubectl apply -f https://raw.githubusercontent.com/istio/istio/release-1.22/samples/addons/kiali.yaml
kubectl apply -f https://raw.githubusercontent.com/istio/istio/release-1.22/samples/addons/prometheus.yaml  # Kiali dependency
kubectl -n istio-system rollout status deploy/kiali
```

Access the Kiali dashboard via port-forward:
```bash
istioctl dashboard kiali
```

This gives a live service graph showing mTLS status, request rates, and error rates across all platform services.

- [ ] **Step 7: Add Istio new file paths to Helm chart File Structure**

Add to `deploy/helm/aispm/templates/` listing:
```
istio-peerauthentication.yaml
istio-authorizationpolicies.yaml
istio-gateway.yaml
istio-virtualservices.yaml
```

Add to `deploy/istio/`:
```
istio-values.yaml      # reference values for istioctl / helm install
```

- [ ] **Step 8: Verify mTLS + AuthorizationPolicy end-to-end**

```bash
# Check mTLS is enforced — a pod without a sidecar should be rejected:
kubectl run test-no-mesh --image=curlimages/curl:8.6.0 \
  -n default --restart=Never \
  --command -- curl -m 5 http://spm-api.aispm.svc.cluster.local:8092/health
kubectl logs test-no-mesh
# Expected: connection refused / reset (no mTLS cert → rejected by PeerAuthentication STRICT)
kubectl delete pod test-no-mesh

# Check an in-mesh pod can reach spm-api normally:
kubectl -n aispm exec deploy/api -- \
  curl -s http://spm-api.aispm.svc.cluster.local:8092/health
# Expected: {"status":"ok"}

# Check agent AuthorizationPolicy (simulate from aispm-agents → spm-mcp):
kubectl run test-agent-reach --image=curlimages/curl:8.6.0 \
  -n aispm-agents \
  --labels="role=agent-runtime" \
  --restart=Never \
  --overrides='{"spec":{"serviceAccountName":"agent-runtime"}}' \
  --command -- curl -m 5 http://spm-mcp.aispm.svc.cluster.local:8500/health
kubectl logs test-agent-reach -n aispm-agents
# Expected: {"status":"ok"}
kubectl delete pod test-agent-reach -n aispm-agents
```

- [ ] **Step 9: Add Istio items to Review Pass 1 Checklist**

The following checks are added (at the end of the checklist in Task 16):
- `aispm` namespace has `istio-injection: enabled` label.
- `aispm-agents` namespace has `istio.io/dataplane-mode: ambient` label (not `istio-injection`).
- `PeerAuthentication` is `STRICT` — not `PERMISSIVE`.
- `AuthorizationPolicy` `agent-allow-spm-api` restricts agent callbacks to only `/agents/*/ready`, `/agents/*/bootstrap`, `/secrets/*` — not all of spm-api.
- Kiali shows green mTLS lock icons on all intra-platform edges.
- The Istio Gateway TLS credential references the same cert-manager-issued Secret as the ingress in Task 11.

- [ ] **Step 10: Commit**

```bash
git add deploy/istio/ \
        deploy/k8s/namespaces/ \
        deploy/helm/aispm/templates/istio-*.yaml
git commit -m "feat(istio): service mesh — sidecar/STRICT-mTLS for aispm, Ambient for aispm-agents, AuthorizationPolicies, Gateway + VirtualServices"
```

---

## Task 16: Runtime Security — Falco + Tetragon (agent pods only)
**Effort:** L (3 h)

**Split:** Tetragon enforces hard stops inline (0ms, process never completes). Falco watches behavioral patterns and fires alerts to Kafka + PagerDuty. Both are scoped exclusively to `aispm-agents`.

**Files:**
- Create: `deploy/helm/aispm/templates/falco-rules-configmap.yaml`
- Create: `deploy/helm/aispm/templates/tetragon-tracingpolicies.yaml`
- Create: `deploy/falco/falco-values.yaml`
- Create: `deploy/tetragon/tetragon-values.yaml`

---

### Part A — Tetragon (inline enforcement)

- [ ] **Step 1: Install Tetragon via Helm**

```bash
helm repo add cilium https://helm.cilium.io
helm repo update
helm install tetragon cilium/tetragon \
  --namespace kube-system \
  --set tetragon.enablePolicyFilter=true
kubectl -n kube-system rollout status ds/tetragon
```

`enablePolicyFilter=true` means TracingPolicies can be scoped to a namespace — essential so our agent policies don't affect platform pods.

- [ ] **Step 2: Write TracingPolicies for agent pods**

```yaml
# deploy/helm/aispm/templates/tetragon-tracingpolicies.yaml

# Policy 1 — kill any exec inside an agent pod.
# Agents run loader.py, which exec()s the customer's agent.py.
# Any FURTHER exec (spawning a shell, running a binary) is an attack.
apiVersion: cilium.io/v1alpha1
kind: TracingPolicy
metadata:
  name: agent-no-exec
  namespace: {{ .Values.agentRuntime.namespace }}
spec:
  podSelector:
    matchLabels:
      role: agent-runtime
  kprobes:
    - call: "sys_execve"
      syscall: true
      args:
        - index: 0
          type: "string"
      selectors:
        - matchNamespaces:
            - operator: In
              values: ["{{ .Values.agentRuntime.namespace }}"]
          matchActions:
            - action: Sigkill   # kill the process before exec completes
---
# Policy 2 — kill on raw socket creation (exfil/C2 channel attempt)
apiVersion: cilium.io/v1alpha1
kind: TracingPolicy
metadata:
  name: agent-no-raw-socket
  namespace: {{ .Values.agentRuntime.namespace }}
spec:
  podSelector:
    matchLabels:
      role: agent-runtime
  kprobes:
    - call: "sys_socket"
      syscall: true
      args:
        - index: 0
          type: "int"
      selectors:
        - matchArgs:
            - index: 0
              operator: Equal
              values: ["17"]   # AF_PACKET (raw socket family)
          matchActions:
            - action: Sigkill
---
# Policy 3 — kill on writes to /proc or /sys (container escape pattern)
apiVersion: cilium.io/v1alpha1
kind: TracingPolicy
metadata:
  name: agent-no-proc-write
  namespace: {{ .Values.agentRuntime.namespace }}
spec:
  podSelector:
    matchLabels:
      role: agent-runtime
  kprobes:
    - call: "sys_openat"
      syscall: true
      args:
        - index: 1
          type: "string"
      selectors:
        - matchArgs:
            - index: 1
              operator: Prefix
              values: ["/proc/", "/sys/"]
          matchCapabilities:
            - type: Effective
              operator: NotIn
              values: []
          matchActions:
            - action: Sigkill
```

- [ ] **Step 3: Apply and verify Tetragon policies**

```bash
helm upgrade --install aispm deploy/helm/aispm/ -n aispm \
  --set secrets.spmDbPassword=testpass

kubectl get tracingpolicies -n {{ agentRuntime.namespace }}
# Expected: agent-no-exec, agent-no-raw-socket, agent-no-proc-write

# Smoke test — spawn a test pod and try to exec a shell:
kubectl run test-tetragon \
  --image=python:3.12-slim \
  --labels="role=agent-runtime" \
  --restart=Never \
  -n aispm-agents \
  --command -- python -c "import subprocess; subprocess.run(['sh','-c','id'])"

kubectl logs test-tetragon -n aispm-agents
# Expected: process killed — no output from `id`

# Check Tetragon audit log:
kubectl -n kube-system exec ds/tetragon -c tetragon -- \
  tetra getevents --namespaces aispm-agents | head -20

kubectl delete pod test-tetragon -n aispm-agents
```

---

### Part B — Falco (behavioral alerting)

- [ ] **Step 4: Create Falco Helm values scoped to aispm-agents**

```yaml
# deploy/falco/falco-values.yaml
# Falco watches only aispm-agents — no noise from platform services.
falco:
  rules_file:
    - /etc/falco/falco_rules.yaml
    - /etc/falco/agent_rules.yaml

  # Watch only agent namespace pods
  namespaces:
    - aispm-agents

  # Output to stdout + gRPC (Falcosidekick picks up gRPC)
  json_output: true
  log_level: info

  grpc:
    enabled: true
    bind_address: "unix:///run/falco/falco.sock"

falcosidekick:
  enabled: true
  config:
    kafka:
      hostport: kafka-broker.aispm.svc.cluster.local:9092
      topic: cpm.t1.security.falco
      # Existing Kafka infrastructure — no new broker needed
    slack:
      webhookurl: ""        # set via --set falcosidekick.config.slack.webhookurl=
    pagerduty:
      routingKey: ""        # set via --set falcosidekick.config.pagerduty.routingKey=
    kubernetesPodName: true
    minimumpriority: warning
```

- [ ] **Step 5: Install Falco**

```bash
helm repo add falcosecurity https://falcosecurity.github.io/charts
helm repo update
helm install falco falcosecurity/falco \
  --namespace falco \
  --create-namespace \
  -f deploy/falco/falco-values.yaml \
  --set driver.kind=ebpf            # eBPF driver — no kernel module needed on RKE2
kubectl -n falco rollout status ds/falco
```

- [ ] **Step 6: Write agent-specific Falco rules**

```yaml
# deploy/helm/aispm/templates/falco-rules-configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: falco-agent-rules
  namespace: falco
data:
  agent_rules.yaml: |
    # ── Macros ────────────────────────────────────────────────────────────
    - macro: agent_pod
      condition: >
        k8s.ns.name = "aispm-agents" and
        k8s.pod.label.role = "agent-runtime"

    # ── Rules ─────────────────────────────────────────────────────────────

    - rule: Agent Spawned Shell
      desc: An agent pod spawned a shell — likely an injection or escape attempt
      condition: >
        agent_pod and
        spawned_process and
        proc.name in (sh, bash, zsh, dash, ash)
      output: >
        CRITICAL: Agent spawned shell
        (pod=%k8s.pod.name agent=%k8s.pod.label.agent-id
         cmd=%proc.cmdline user=%user.name)
      priority: CRITICAL
      tags: [agent, shell, escape]

    - rule: Agent Write Outside Allowed Path
      desc: Agent wrote a file outside /agent/ or /tmp/
      condition: >
        agent_pod and
        open_write and
        not fd.name startswith "/agent/" and
        not fd.name startswith "/tmp/"
      output: >
        WARNING: Agent wrote outside allowed path
        (pod=%k8s.pod.name path=%fd.name agent=%k8s.pod.label.agent-id)
      priority: WARNING
      tags: [agent, filesystem]

    - rule: Agent Unexpected Network Destination
      desc: Agent connected to something other than spm-mcp, spm-llm-proxy, kafka, spm-api
      condition: >
        agent_pod and
        outbound and
        not fd.sip.name in (
          "spm-mcp.aispm.svc.cluster.local",
          "spm-llm-proxy.aispm.svc.cluster.local",
          "kafka-broker.aispm.svc.cluster.local",
          "spm-api.aispm.svc.cluster.local"
        )
      output: >
        CRITICAL: Agent connected to unexpected destination
        (pod=%k8s.pod.name dest=%fd.sip.name:%fd.sport
         agent=%k8s.pod.label.agent-id)
      priority: CRITICAL
      tags: [agent, network, exfil]

    - rule: Agent Read Sensitive File
      desc: Agent read /etc/passwd, /etc/shadow, or service account token
      condition: >
        agent_pod and
        open_read and
        fd.name in (
          /etc/passwd, /etc/shadow, /etc/sudoers,
          /var/run/secrets/kubernetes.io/serviceaccount/token
        )
      output: >
        CRITICAL: Agent read sensitive file
        (pod=%k8s.pod.name file=%fd.name agent=%k8s.pod.label.agent-id)
      priority: CRITICAL
      tags: [agent, credential-access]

    - rule: Agent High Outbound Connection Rate
      desc: Agent making unusually high number of outbound connections (C2 beacon pattern)
      condition: >
        agent_pod and
        outbound and
        evt.count > 50 within 10s
      output: >
        WARNING: Agent high connection rate — possible C2 beacon
        (pod=%k8s.pod.name count=%evt.count agent=%k8s.pod.label.agent-id)
      priority: WARNING
      tags: [agent, network, c2]
```

- [ ] **Step 7: Mount the rules ConfigMap into Falco**

Add to `deploy/falco/falco-values.yaml`:
```yaml
extraVolumes:
  - name: agent-rules
    configMap:
      name: falco-agent-rules
extraVolumeMounts:
  - name: agent-rules
    mountPath: /etc/falco/agent_rules.yaml
    subPath: agent_rules.yaml
```

Upgrade Falco:
```bash
helm upgrade falco falcosecurity/falco \
  --namespace falco \
  -f deploy/falco/falco-values.yaml \
  --set driver.kind=ebpf
```

- [ ] **Step 8: Verify Falco alerts flow to Kafka**

```bash
# Trigger a test alert — run a shell inside an agent-labeled pod:
kubectl run test-falco \
  --image=python:3.12-slim \
  --labels="role=agent-runtime" \
  --restart=Never \
  -n aispm-agents \
  --command -- sh -c "id; sleep 2"

# Check Falco caught it:
kubectl -n falco logs ds/falco | grep "Agent Spawned Shell"
# Expected: CRITICAL Agent Spawned Shell pod=test-falco ...

# Check it arrived on Kafka:
kubectl -n aispm exec deploy/api -- \
  python -c "
from kafka import KafkaConsumer
import json
c = KafkaConsumer('cpm.t1.security.falco',
                  bootstrap_servers='kafka-broker:9092',
                  auto_offset_reset='earliest',
                  consumer_timeout_ms=5000)
for m in c:
    print(json.loads(m.value))
    break
"

kubectl delete pod test-falco -n aispm-agents
```

- [ ] **Step 9: Add to Review Pass 1 Checklist**

- Tetragon `TracingPolicy` resources exist in `aispm-agents` and have `podSelector: role=agent-runtime`.
- `agent-no-exec` policy uses `action: Sigkill` — not just log.
- Falco rules ConfigMap is mounted into the Falco DaemonSet pods.
- `agent_pod` macro correctly matches `k8s.ns.name = "aispm-agents"` — Falco only fires on agent pods, not platform services.
- Falcosidekick Kafka output points to `cpm.t1.security.falco` — consistent with the existing topic naming convention.
- Tetragon and Falco are both installed in separate namespaces (`kube-system` and `falco`) — not `aispm`.

- [ ] **Step 10: Commit**

```bash
git add deploy/falco/ \
        deploy/tetragon/ \
        deploy/helm/aispm/templates/falco-rules-configmap.yaml \
        deploy/helm/aispm/templates/tetragon-tracingpolicies.yaml
git commit -m "feat(security): Tetragon inline enforcement + Falco behavioral alerting scoped to aispm-agents"
```

---

## Task 17: E2E Smoke Test
**Effort:** M (1.5 h)

A single Python script that drives the full agent lifecycle against the deployed cluster and asserts every step succeeds.

**Files:**
- Create: `tests/e2e/test_k8s_agent_lifecycle.py`
- Create: `tests/e2e/conftest.py`

- [ ] **Step 1: Write the smoke test**

```python
# tests/e2e/test_k8s_agent_lifecycle.py
"""E2E smoke test: full agent lifecycle on the k8s cluster.

Prerequisites:
  - AISPM_BASE_URL env var pointing at the spm-api ingress
    e.g. https://aispm.yourdomain.com/api/spm
  - A valid admin JWT in AISPM_ADMIN_JWT env var
  - kubectl context pointing at the target cluster

The test registers an agent, deploys it, waits for running state,
sends a chat message, then retires the agent.  Each assertion also
checks the expected k8s object state via the k8s Python client.
"""
import os
import time
import pytest
import httpx
from kubernetes import client, config

BASE = os.environ["AISPM_BASE_URL"]   # https://host/api/spm
JWT  = os.environ["AISPM_ADMIN_JWT"]
NS   = os.environ.get("AGENT_POD_NAMESPACE", "aispm-agents")

HEADERS = {"Authorization": f"Bearer {JWT}"}

AGENT_PY = '''
import aispm
aispm.ready()
# Minimal agent — just signals ready and idles.
while True:
    import time; time.sleep(60)
'''


@pytest.fixture(scope="module")
def k8s():
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.CoreV1Api()


def test_full_agent_lifecycle(k8s):
    # 1. Register agent
    resp = httpx.post(
        f"{BASE}/agents",
        headers=HEADERS,
        files={"file": ("agent.py", AGENT_PY.encode(), "text/x-python")},
        data={"name": "smoke-test-agent", "version": "1.0.0",
              "agent_type": "custom", "owner": "e2e"},
        timeout=30,
    )
    assert resp.status_code == 201, f"register failed: {resp.text}"
    agent_id = resp.json()["id"]

    try:
        # 2. Deploy
        resp = httpx.post(
            f"{BASE}/agents/{agent_id}/start",
            headers=HEADERS, timeout=60,
        )
        assert resp.status_code == 200, f"start failed: {resp.text}"

        # 3. Wait for running state (poll up to 60s)
        for _ in range(60):
            time.sleep(1)
            r = httpx.get(f"{BASE}/agents/{agent_id}", headers=HEADERS)
            if r.json().get("runtime_state") == "running":
                break
        else:
            pytest.fail(f"agent never reached running; last state: {r.json()}")

        # 4. Verify Pod exists in k8s with Kata runtime
        pod = k8s.read_namespaced_pod(name=f"agent-{agent_id}", namespace=NS)
        assert pod.spec.runtime_class_name == "kata", \
            f"expected kata, got {pod.spec.runtime_class_name}"
        assert pod.metadata.labels.get("role") == "agent-runtime"

        # 5. Verify ConfigMap exists
        cm = k8s.read_namespaced_config_map(
            name=f"agent-code-{agent_id}", namespace=NS)
        assert "agent.py" in cm.data

        # 6. Verify NetworkPolicy is in place
        net = client.NetworkingV1Api()
        policies = net.list_namespaced_network_policy(namespace=NS)
        names = [p.metadata.name for p in policies.items]
        assert "default-deny-all" in names
        assert "agent-allow-egress" in names

        # 7. Stop the agent
        resp = httpx.post(
            f"{BASE}/agents/{agent_id}/stop",
            headers=HEADERS, timeout=30,
        )
        assert resp.status_code == 200

    finally:
        # 8. Retire (cleanup) — runs even if assertions fail
        httpx.delete(
            f"{BASE}/agents/{agent_id}",
            headers=HEADERS, timeout=30,
        )
        # Verify Pod and ConfigMap are gone
        time.sleep(3)
        try:
            k8s.read_namespaced_pod(name=f"agent-{agent_id}", namespace=NS)
            pytest.fail("Pod still exists after retire")
        except client.exceptions.ApiException as e:
            assert e.status == 404
```

- [ ] **Step 2: Write the conftest**

```python
# tests/e2e/conftest.py
import os
import pytest

def pytest_configure(config):
    if not os.environ.get("AISPM_BASE_URL"):
        pytest.skip("AISPM_BASE_URL not set — skipping E2E tests", allow_module_level=True)
```

- [ ] **Step 3: Run the smoke test against the deployed cluster**

```bash
export AISPM_BASE_URL=https://aispm.yourdomain.com/api/spm
export AISPM_ADMIN_JWT=<your-admin-jwt>
pytest tests/e2e/test_k8s_agent_lifecycle.py -v --tb=short
```

Expected: `1 passed` with the full lifecycle completing in under 90s.

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/
git commit -m "test(e2e): k8s agent lifecycle smoke test — register, deploy, kata verify, retire"
```

---

## Task 18: Final Lint, Diff, and Helm Release
**Effort:** S (30 min)

- [ ] **Step 1: Full helm lint pass**

```bash
helm lint deploy/helm/aispm/ --strict
```

Expected: 0 failures.

- [ ] **Step 2: Template render and diff against current cluster state**

```bash
helm diff upgrade aispm deploy/helm/aispm/ -n aispm \
  --set secrets.spmDbPassword=testpass \
  | head -200
```

Install the helm-diff plugin if needed: `helm plugin install https://github.com/databus23/helm-diff`

- [ ] **Step 3: Verify all platform services are Ready**

```bash
kubectl -n aispm get pods -o wide
# All pods should be in Running/Completed state, none in CrashLoopBackOff.
```

- [ ] **Step 4: Run unit tests**

```bash
pytest services/spm_api/tests/ tests/spm_api/ -v --tb=short
```

Expected: all pass.

- [ ] **Step 5: Tag the release in Rancher**

In the Rancher UI: Apps → aispm → Upgrade → set `global.imagePullPolicy=IfNotPresent` → confirm.

- [ ] **Step 6: Final commit + tag**

```bash
git add .
git commit -m "chore(helm): finalize aispm chart v1.0.0 — k8s migration complete"
git tag k8s-migration-v1.0.0
git push origin main --tags
```

---

## Review Pass 1 Checklist

After the plan is written, verify each of the following before execution:

- [ ] Every docker-compose service has a corresponding k8s object (Deployment, StatefulSet, or Job).
- [ ] `agent_controller.py` no longer imports `docker`; all calls use `kubernetes.client`.
- [ ] `spawn_agent_pod` sets `runtimeClassName: kata` on every Pod spec.
- [ ] `stop_agent_pod` cleans up both the Pod and the `agent-code-{id}` ConfigMap.
- [ ] The `spm-api` Deployment uses `serviceAccountName: spm-api`, which has a Role in `aispm-agents` allowing pod/configmap CRUD.
- [ ] `agent-runtime` ServiceAccount in `aispm-agents` has `automountServiceAccountToken: false`.
- [ ] NetworkPolicy `default-deny-all` covers all Pods in `aispm-agents`.
- [ ] NetworkPolicy `agent-allow-egress` covers DNS (port 53) so hostname resolution works inside agent Pods.
- [ ] `startup-orchestrator` Job has `helm.sh/hook: post-install,post-upgrade` so it runs after the Kafka StatefulSet is ready.
- [ ] `flink-pyjob-submitter` Job has the same hook annotation.
- [ ] All JWT key references use the `jwt-keys` Secret with volume mounts at `/keys`.
- [ ] `SPM_DB_URL` env vars are assembled from ConfigMap values + Secret refs (not hardcoded).
- [ ] Longhorn PVCs use `Retain` reclaim policy so a `helm uninstall` does not destroy data.
- [ ] The E2E test asserts `runtimeClassName == "kata"` on the spawned Pod.
- [ ] `values.yaml` contains no plaintext secrets (all secret values under `secrets.*` key, defaulting to placeholder strings).

---

## Review Pass 2 Checklist

- [ ] **Startup ordering:** Kafka + spm-db + Redis are StatefulSets with readiness probes. The `startup-orchestrator` Job hook has `helm.sh/hook-weight: -5` — verify this runs only after the StatefulSets' pods are Ready by adding an `initContainer` that waits on Kafka:
  ```yaml
  initContainers:
    - name: wait-for-kafka
      image: busybox
      command: ['sh', '-c', 'until nc -z kafka-broker.aispm.svc.cluster.local 9092; do sleep 2; done']
  ```
- [ ] **agent-orchestrator SQLite vs Postgres:** The compose service uses `DB_PATH: /data/agent_orchestrator.db`. If that code path still exists in the service, Task 11 needs a PVC at `/data` (add a 1Gi Longhorn PVC named `agent-orchestrator-data`). Check `services/agent-orchestrator-service/` for SQLite usage.
- [ ] **Flink ReadWriteMany:** Longhorn RWX requires the Longhorn NFS provisioner to be enabled. Add a note to `values.yaml` or use `storageClass: longhorn-single` (RWO) with `podAffinity` to co-locate JobManager and TaskManager on the same node if RWX is unavailable.
- [ ] **guard-model extra_hosts:** The compose service has `extra_hosts: host.docker.internal:host-gateway` to reach host Ollama. In k8s this becomes a Node-IP based Service or an ExternalName Service. Add an `ExternalName` Service in the chart if `GROQ_BASE_URL` points to an Ollama instance on the node:
  ```yaml
  apiVersion: v1
  kind: Service
  metadata:
    name: host-ollama
    namespace: aispm
  spec:
    type: ExternalName
    externalName: <node-ip>
  ```
  Set `GROQ_BASE_URL: http://host-ollama.aispm.svc.cluster.local:11434/v1` in values.
- [ ] **image registry:** `values.yaml` has `global.imageRegistry: ""`. Before production deployment, push all images to a private registry (e.g. Rancher's built-in Harbor or GHCR) and update `imageRegistry`. Add `imagePullSecrets` to the chart for private registries.
- [ ] **Secrets hygiene:** The `secrets.yaml` template writes secrets via `stringData`. In production, use Rancher's Secrets management or External Secrets Operator to inject values rather than `--set secrets.spmDbPassword=...` on the CLI, which leaks to shell history.
- [ ] **Prometheus scrape targets:** `prometheus.yml` uses Docker service names (e.g. `api:8080`). Update it to use k8s service DNS names (`api.aispm.svc.cluster.local:8080`) or switch to Prometheus ServiceMonitor CRDs (kube-prometheus-stack) for auto-discovery.
- [ ] **Resource requests on all Deployments:** Task 8 adds resource limits only to guard-model as an example. Before production deployment, add `resources.requests` and `resources.limits` to every Deployment template via a `values.yaml` `resources:` map, e.g.:
  ```yaml
  resources:
    api:
      requests: { cpu: 200m, memory: 256Mi }
      limits:   { cpu: 1000m, memory: 1Gi }
  ```
