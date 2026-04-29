# Runtime page doesn't show custom-agent chat sessions

**Filed:** 2026-04-29
**Status:** known gap, deferred — fix path agreed (Option C, Kafka bridge)
**Severity:** UI surface gap. Data is captured (audit_export, audit Kafka topic);
just not surfaced in the place a user would expect to find it.

---

## Symptom

The Runtime page in the admin UI lists 0 sessions for the custom agent
even after multiple successful chat round-trips. Pages like Posture,
Models, Integrations populate fine; only Runtime is empty.

## Root cause — two parallel session stores

When a user chats with a custom agent in the UI:

```
UI → spm-api  POST /agents/{id}/chat
            └─ writes to agent_chat_sessions (spm-db, spm-api owned)
            └─ produces to Kafka  cpm.t1.audit
                                 cpm.t1.decision
                                 (etc.)
```

The Runtime page reads sessions from `agent-orchestrator-service`:

```
UI → /api/v1/sessions  →  agent-orchestrator-service
                         └─ reads from agent_sessions / session_events
                            (same spm-db, but different tables, owned
                             by the orchestrator)
```

So chat events go to one table, Runtime queries another. The `agent_sessions`
table is currently populated only by the simulator path (Garak runs,
single-prompt sims), which DOES go through agent-orchestrator-service.

Confirmed empirically (2026-04-29):

```
agent_chat_sessions = 14 rows  (chat history present)
agent_sessions      =  0 rows  (Runtime queries this — empty)
session_events      =  0 rows
audit_export        =  populated  (spm-aggregator mirrors Kafka audit here)
```

## Why this is the right gap to close, not just a UI hack

The Runtime page semantically should be a single pane of glass over every
agent invocation — chat, simulator probe, agent-orchestrator-driven
sessions, all of it. Splitting the read path (UI calls spm-api for chats
+ orchestrator for sims, then merges client-side) leaves a permanent
asymmetry: cases, threat findings, lineage all live behind the
orchestrator's `/api/v1/...` endpoints. Forcing the UI to know about
two session sources means every future feature (filtering, search,
case-from-session, etc.) has to handle both.

Fixing the data flow once is cheaper than maintaining two read paths.

## Considered options

### Option A — UI merges both sources

`fetchAllSessions()` calls both `/api/v1/sessions` and a new
`/api/agents/{id}/chat-sessions` and concatenates results.

- ✅ Smallest diff (UI only)
- ❌ Two parallel session sources forever
- ❌ Every downstream feature (cases, lineage, filtering, search) has to
  remember "is this a chat session or an orchestrator session?"
- ❌ Doesn't solve the underlying schema fragmentation

### Option B — spm-api dual-writes to agent_sessions

`agent_chat.py:_ensure_session()` also INSERTs into the orchestrator's
`agent_sessions` table with sensible defaults for the simulator-shaped
fields.

- ✅ Runtime page works as-is
- ❌ Cross-service writes (spm-api writing into orchestrator's tables)
  blur ownership boundaries
- ❌ Most agent_sessions columns (`prompt_hash`, `policy_reason`,
  `policy_version`, `risk_signals`, `tools`, `context`) are vestigial
  for chat — they exist for the simulator's risk-engine output
- ❌ Schema-as-API coupling: a future migration on the orchestrator's
  side breaks spm-api silently

### Option C — Kafka bridge in agent-orchestrator-service ⭐

Add a Kafka consumer to `agent-orchestrator-service` subscribed to the
chat-relevant audit topics (`cpm.t1.audit`, `cpm.t1.decision`). For each
event, the consumer creates/updates `agent_sessions` rows and streams
events into `session_events`.

- ✅ Single read path (the Runtime page already works)
- ✅ Single source of truth for sessions (orchestrator owns the table,
  orchestrator writes to it)
- ✅ Producer-side stays clean (spm-api keeps producing audit events;
  orchestrator becomes another consumer of those events)
- ✅ Same DB so no cross-service direct writes; the orchestrator uses
  its existing async session factory (`db/`)
- ❌ More code than A or B
- ❌ Need a careful chat→agent_sessions mapping spec (see below)

## Implementation sketch (option C)

### 1. New consumer in agent-orchestrator-service

A new module: `services/agent-orchestrator-service/audit_consumer/`

```python
# audit_consumer/main.py
async def run():
    consumer = AIOKafkaConsumer(
        "cpm.t1.audit", "cpm.t1.decision",
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        group_id="agent-orchestrator-audit-bridge",
        auto_offset_reset="latest",
        enable_auto_commit=True,
    )
    await consumer.start()
    try:
        async for msg in consumer:
            await _handle_event(json.loads(msg.value))
    finally:
        await consumer.stop()
```

Wired into `main.py`'s lifespan as a background task.

### 2. Event handler

```python
async def _handle_event(event: dict) -> None:
    session_id = event.get("session_id") or event.get("details", {}).get("session_id")
    if not session_id:
        return  # not session-scoped, e.g. platform-level audit

    async with session_factory() as db:
        session = await db.get(AgentSessionORM, session_id)
        if session is None:
            session = AgentSessionORM(
                id=session_id,
                user_id=event.get("principal", "unknown"),
                agent_id=event.get("details", {}).get("agent_id", "unknown"),
                tenant_id=event.get("tenant_id", "global"),
                status="active",
                risk_score=0.0,
                decision="allow",
                prompt_hash=hashlib.sha256(
                    event.get("details", {}).get("text", "").encode()
                ).hexdigest()[:16],
                risk_tier="low",
                risk_signals="[]",
                tools="[]",
                context="{}",
                policy_reason="",
                policy_version="0",
                trace_id=event.get("correlation_id", session_id),
                created_at=datetime.fromtimestamp(event["ts"] / 1000, tz=timezone.utc),
                updated_at=datetime.fromtimestamp(event["ts"] / 1000, tz=timezone.utc),
            )
            db.add(session)

        # Stream the event itself
        db.add(SessionEventORM(
            id=event.get("event_id") or str(uuid4()),
            session_id=session_id,
            event_type=event.get("event_type", "unknown"),
            payload=json.dumps(event),
            timestamp=datetime.fromtimestamp(event["ts"] / 1000, tz=timezone.utc),
        ))

        # Update aggregate fields on the session row from this event
        details = event.get("details", {})
        if "guard_score" in details:
            session.risk_score = max(session.risk_score, details["guard_score"])
        if event.get("event_type") == "policy_decision":
            session.decision = details.get("decision", "allow")
            if session.decision != "allow":
                session.status = "blocked"
        session.updated_at = datetime.fromtimestamp(event["ts"] / 1000, tz=timezone.utc)

        await db.commit()
```

### 3. Field mapping (chat event → agent_sessions row)

| `agent_sessions` column | Source                                         | Default for chat        |
|-------------------------|------------------------------------------------|-------------------------|
| `id`                    | `event.session_id`                             | required                |
| `user_id`               | `event.principal`                              | `"unknown"`             |
| `agent_id`              | `event.details.agent_id`                       | `"unknown"`             |
| `tenant_id`             | `event.tenant_id`                              | `"global"`              |
| `status`                | derived: `active` until policy_decision arrives| `"active"`              |
| `risk_score`            | max(`event.details.guard_score`) over events   | `0.0`                   |
| `decision`              | `event.details.decision` (on policy_decision)  | `"allow"`               |
| `prompt_hash`           | sha256(first user message)[:16]                | sha256("")[:16]         |
| `risk_tier`             | derive from risk_score                         | `"low"`                 |
| `risk_signals`          | JSON aggregate                                 | `"[]"`                  |
| `tools`                 | JSON aggregate from `tool_request` events      | `"[]"`                  |
| `context`               | JSON object                                    | `"{}"`                  |
| `policy_reason`         | `event.details.reason` on block                | `""`                    |
| `policy_version`        | `event.details.policy_version`                 | `"0"`                   |
| `trace_id`              | `event.correlation_id`                         | session_id              |
| `created_at`            | first event ts                                 | required                |
| `updated_at`            | latest event ts                                | required                |

### 4. Test plan

- Unit: feed a synthetic event sequence (input → guard → decision)
  through `_handle_event`, assert the session row + N events.
- Integration: spin up agent-orchestrator-service in dev with this
  consumer enabled, send a chat in the UI, verify rows appear in
  `agent_sessions` + `session_events` within ~2 seconds.
- Regression: existing simulator path still creates sessions correctly
  (consumer should be idempotent — `agent_sessions.id` is the PK, so
  the simulator's writes win on conflict).

### 5. Idempotency

Multiple consumers can replay events without duplicating session rows
(PK conflict on `agent_sessions.id`). For `session_events`, key on
`event_id` to drop duplicates (this is what `audit_export.event_id`
already does in spm-aggregator).

## Out of scope for this PR / commit

- Implementing option C — deferred to a dedicated session.
- UI changes — once C lands, the Runtime page works without UI edits.
- Schema migrations — none needed; `agent_sessions` and `session_events`
  already exist and have all the columns we need.

## References

- `services/spm_api/agent_chat.py` — chat session writer (current path)
- `services/agent-orchestrator-service/db/models.py` —
  `AgentSessionORM` (line 30), `SessionEventORM` (line 78)
- `services/spm_aggregator/app.py:mirror_audit_event` — current
  audit-event consumer pattern, similar to what we need to add to
  agent-orchestrator-service
- `ui/src/api/simulationApi.js:fetchAllSessions` — consumer of
  `/api/v1/sessions`
- `ui/src/admin/pages/Runtime.jsx` — page that calls fetchAllSessions
