# services/flink_pyjob — PyFlink CEP job

Apache Flink (PyFlink DataStream API) job that runs the per-user CEP
cascade over `cpm.<tenant>.posture_enriched` and emits alerts /
audit envelopes to `cpm.<tenant>.audit`. State lives in RocksDB inside
each TaskManager and is checkpointed to a host-mounted local filesystem
for exactly-once semantics.

> **Why no MinIO/S3?** Single-host deployment doesn't need an external
> blob store. JM and TM share the same host directory via bind mount,
> which is the simplest thing that works. For multi-host Kubernetes,
> swap `file://` for `s3://` in `flink-conf.yaml` and add the
> `s3-fs-presto` plugin — no other code changes needed.

## Layout

| File                  | Role                                                   |
|-----------------------|--------------------------------------------------------|
| `detection.py`        | Pure cascade — alert-level rules + payload shape       |
| `state.py`            | `CEPDetector(KeyedProcessFunction)` with managed state |
| `sinks.py`            | Kafka sink (EXACTLY_ONCE, single audit topic)          |
| `cep_job.py`          | Main entry — wires source → detector → sink per tenant |
| `Dockerfile`          | Submitter image (runs `flink run --detached`)          |
| `submit.sh`           | Bash wrapper invoked by the submitter container        |
| `requirements.txt`    | apache-flink, kafka-python-ng, boto3, pytest           |
| `tests/`              | Pure-logic tests — no Flink runtime needed             |

## Topology

```
posture_enriched (Kafka source, per tenant)
    -> JSON parse + drop malformed
    -> keyBy (tenant_id|user_id)
    -> CEPDetector (KeyedProcessFunction, managed state)
    -> Kafka sink (cpm.<tenant>.<CEP_AUDIT_TOPIC_SUFFIX>, default audit)
```

State per key (= per `(tenant_id, user_id)`):

| Field             | Flink type                 | Scope                         |
|-------------------|----------------------------|-------------------------------|
| `short_events`    | `ListState[(long, str)]`   | user                          |
| `long_events`     | `ListState[(long, str)]`   | user                          |
| `session_signals` | `MapState[str, str]` †     | session (sub-keyed)           |
| `drift_history`   | `MapState[str, str]` †     | session (sub-keyed)           |
| `posture_history` | `MapState[str, str]` †     | session (sub-keyed)           |
| `blocked_today`   | `ValueState[int]`          | user                          |

All state has a 1-day TTL via `StateTtlConfig`.

† **Session-scoped fields.** Flink keyBy is user-scoped, but these
three fields are semantically per-session. They're stored as
`MapState[session_id → JSON-encoded payload]` under the user-keyed
operator so each session has its own slice. Without this split, rule
#6 of the cascade (`posture_trend.avg > 0.50`) would see posture scores
from every session mixed together and fire incorrectly. See the module
docstring in `state.py` for details.

## Local cluster

Brought up by `make flink-up` (in repo root). Containers:

| Service                  | Purpose                                                     |
|--------------------------|-------------------------------------------------------------|
| `flink-jobmanager`       | Submits/coordinates jobs (UI on :8081). Built from this dir's Dockerfile so it has Python + apache-flink for client-side validation. |
| `flink-taskmanager`      | Executes user Python operators in-process via pemja (3 slots, matches `KAFKA_NUM_PARTITIONS`). Same image as JM. |
| `flink-pyjob-submitter`  | One-shot container that runs `flink run --python ...` against the JM REST API. |

All three containers share the same image `aispm-flink-pyjob:latest`
(only the JM service has the `build:` directive — TM and submitter
just `image:` it).

Bind mounts:
- `./DataVolums/flink-checkpoints` → `/flink/checkpoints`  (JM + TM)
- `./DataVolums/flink-savepoints`  → `/flink/savepoints`   (JM + TM)
- `./flink/flink-conf.yaml`        → `/opt/flink/conf/flink-conf.yaml:ro`  (JM + TM)
- `./services/flink_pyjob`         → `/opt/flink-pyjob/services/flink_pyjob:ro`  (TM, for hot iteration)
- `./platform_shared`              → `/opt/flink-pyjob/platform_shared:ro`  (TM, for hot iteration)

UI:
- Flink dashboard: http://localhost:8081

## Sink topic override

`CEP_AUDIT_TOPIC_SUFFIX` (default `audit`) controls the sink topic
suffix: the job writes to `cpm.<tenant>.<suffix>`. For a shadow run
— e.g., before rolling out a CEP rule rewrite — set it to
`audit_shadow` so the job writes to a side topic without polluting
the live audit stream:

```bash
CEP_AUDIT_TOPIC_SUFFIX=audit_shadow make flink-submit
```

Compare the two streams by draining both topics and diffing the
payloads. Don't point two running jobs at the same suffix — each
envelope would be double-written.

## Operational notes

**Job restart from checkpoint** is automatic via the configured
restart-strategy (exponential backoff, 10s → 5min). State is restored
from the latest completed checkpoint.

**Planned restart with state preservation:**

```bash
make flink-savepoint           # writes to file:///flink/savepoints/<id>
                               # = ./DataVolums/flink-savepoints/<id> on host
make flink-cancel
# ...deploy new job code via flink-pyjob-submitter rebuild...
docker exec cpm-flink-jobmanager flink run \
  -s file:///flink/savepoints/<id> \
  --python /opt/flink-pyjob/services/flink_pyjob/cep_job.py ...
```

**Scaling:** raise `taskmanager.numberOfTaskSlots` (currently 3, matched
to `KAFKA_NUM_PARTITIONS`) and restart from savepoint. Parallelism
per job is set via `CEP_PARALLELISM` env var in the submitter. For
true horizontal scale, run multiple TM replicas — they'll all bind-mount
the same checkpoint dir, which works on a single host but needs a
shared blob store (S3/GCS) on multi-host setups.

**Per-tenant isolation:** v1 submits one job per tenant
(`cep_job.py:main` iterates `CEP_TENANT_IDS`). Each job has its own
checkpoint stream and can be savepointed/scaled independently. A
future v2 can use a dynamic source for cross-tenant fan-in.

## Testing

```bash
make flink-test                # pure-logic tests, no cluster needed
```

Tests live in `tests/`:
- `test_detection.py` — alert-level cascade
- `test_state.py` — eviction helper + import sanity
- `test_parity.py` — synthetic event streams exercising the cascade end-to-end

The `test_state.py` `TestModuleImportsCleanWithoutPyFlink` check is a
guard: `services/flink_pyjob/state.py` MUST be importable in CI
environments that don't install `apache-flink`. Don't break the lazy
import or the optional `_Base` fallback.
