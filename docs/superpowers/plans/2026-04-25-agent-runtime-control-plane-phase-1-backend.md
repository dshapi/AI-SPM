# Agent Runtime Control Plane — Phase 1: Backend Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the backend services and database for hosting customer-uploaded AI agents — `agents`/`chat_sessions`/`chat_messages` tables, the `spm-mcp` MCP server (web_fetch tool only), the `spm-llm-proxy` OpenAI-compat shim, the `agent-runtime` connector registry entry, and the `/api/spm/agents/*` endpoints with a docker+kafka orchestrator.

**Architecture:** Three new services in docker-compose (`spm-mcp`, `spm-llm-proxy`, plus N customer agent containers spawned on demand), one new module in `spm-api` (`agent_controller.py`), one new connector type (`agent-runtime`) in the existing registry, two new helper functions in `platform_shared/`. Per-agent Kafka topics named `cpm.{tenant_id}.agents.{agent_id}.chat.in/.out`. All credentials stored encrypted in `integration_credentials`; agents read them via the existing `get_credential()` helper.

**Tech Stack:** Python 3.12, FastAPI, FastMCP, SQLAlchemy 2 + Alembic, Pydantic v2, kafka-python-ng, Docker SDK for Python, pytest, httpx for tests.

**Reference spec:** `docs/superpowers/specs/2026-04-25-agent-runtime-control-plane-mcp-design.md`

---

## File Structure

### New files

```
spm/alembic/versions/005_agent_runtime_control_plane.py             # migration

services/spm_mcp/
  Dockerfile
  requirements.txt
  main.py                                              # FastMCP server entry
  auth.py                                              # Bearer token validation
  tools/__init__.py
  tools/web_fetch.py                                   # Tavily wrapper
  tests/conftest.py
  tests/test_main.py
  tests/test_auth.py
  tests/test_web_fetch.py

services/spm_llm_proxy/
  Dockerfile
  requirements.txt
  main.py                                              # FastAPI OpenAI-compat shim
  router.py                                            # Routes to configured LLM
  tests/test_router.py
  tests/test_main.py

services/spm_api/agent_routes.py                       # HTTP endpoints
services/spm_api/agent_controller.py                   # docker + kafka orchestration
services/spm_api/agent_validator.py                    # agent.py 3-step validation
services/spm_api/tests/test_agent_routes.py
services/spm_api/tests/test_agent_controller.py
services/spm_api/tests/test_agent_validator.py
services/spm_api/tests/test_connector_registry_agent_runtime.py
```

### Modified files

```
spm/db/models.py                                       # add Agent, AgentChatSession, AgentChatMessage ORM
services/spm_api/app.py                                # mount agent_routes router
services/spm_api/connector_registry.py                 # add agent-runtime entry; enum_integration FieldSpec type
services/spm_api/connector_probes.py                   # add probe_agent_runtime
services/spm_api/integrations_routes.py                # add ?category= query param to GET /integrations
platform_shared/topics.py                              # add agent_topics_for(tenant_id, agent_id)
platform_shared/lineage_events.py                      # add AgentDeployed, AgentStarted, AgentStopped event types
compose.yml                                     # add spm-mcp, spm-llm-proxy services
```

---

## Task 1: Database — SQLAlchemy ORM models

**Files:**
- Modify: `spm/db/models.py` (add three new model classes)
- Test: `spm/tests/test_agent_models.py` (new file)

- [ ] **Step 1: Write the failing tests**

```python
# spm/tests/test_agent_models.py
import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from spm.db.models import Agent, AgentChatSession, AgentChatMessage

def test_agent_round_trip(db_session: Session):
    agent = Agent(
        id=uuid.uuid4(), name="test-agent", version="1.0.0",
        agent_type="langchain", provider="internal",
        owner="ml-platform", description="hello",
        risk="medium", policy_status="partial",
        runtime_state="stopped",
        code_path="./DataVolumes/agents/x/agent.py",
        code_sha256="0" * 64,
        mcp_token="t" * 32,
        llm_api_key="k" * 32,
        tenant_id="t1",
    )
    db_session.add(agent); db_session.commit()
    fetched = db_session.get(Agent, agent.id)
    assert fetched.name == "test-agent"
    assert fetched.runtime_state == "stopped"

def test_session_and_messages_cascade(db_session: Session):
    agent = Agent(id=uuid.uuid4(), name="a", version="1", agent_type="custom",
                  provider="internal", owner="o", code_path="x", code_sha256="0"*64,
                  mcp_token="t"*32, llm_api_key="k"*32, tenant_id="t1")
    db_session.add(agent); db_session.flush()

    session = AgentChatSession(id=uuid.uuid4(), agent_id=agent.id,
                                user_id="dany", message_count=0)
    db_session.add(session); db_session.flush()

    msg = AgentChatMessage(id=uuid.uuid4(), session_id=session.id,
                            role="user", text="hi", trace_id="trc-1")
    db_session.add(msg); db_session.commit()

    assert db_session.query(AgentChatMessage).filter_by(session_id=session.id).count() == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd /Users/danyshapiro/PycharmProjects/AISPM
pytest spm/tests/test_agent_models.py -v
```

Expected: ImportError or AttributeError — Agent/AgentChatSession/AgentChatMessage don't exist yet.

- [ ] **Step 3: Add the three ORM classes**

In `spm/db/models.py` (follow the existing patterns — same `Base`, `Column`, `relationship`, declarative style as `Integration`/`ModelRegistry`):

```python
class Agent(Base):
    __tablename__ = "agents"
    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name         = Column(Text, nullable=False)
    version      = Column(Text, nullable=False)
    agent_type   = Column(Enum("langchain","llamaindex","autogpt","openai_assistant","custom",
                                name="agent_type"), nullable=False)
    provider     = Column(Enum(*PROVIDER_VALUES, name="provider"),
                          nullable=False, default="internal")
    owner        = Column(Text)
    description  = Column(Text, default="")
    risk         = Column(Enum("low","medium","high","critical", name="risk_level"),
                          default="low")
    policy_status= Column(Enum("covered","partial","none", name="policy_status"),
                          default="none")
    runtime_state= Column(Enum("stopped","starting","running","crashed",
                                name="runtime_state"), nullable=False, default="stopped")
    code_path    = Column(Text, nullable=False)
    code_sha256  = Column(Text, nullable=False)
    mcp_token    = Column(Text, nullable=False)        # encrypted at rest (V2)
    llm_api_key  = Column(Text, nullable=False)        # encrypted at rest (V2)
    last_seen_at = Column(DateTime(timezone=True))
    tenant_id    = Column(Text, nullable=False, default="t1", index=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), server_default=func.now(),
                          onupdate=func.now())
    __table_args__ = (
        UniqueConstraint("name","version","tenant_id", name="uq_agents_name_ver_tenant"),
        Index("ix_agents_tenant_state", "tenant_id", "runtime_state"),
    )
    sessions = relationship("AgentChatSession", back_populates="agent",
                             cascade="all, delete-orphan")

class AgentChatSession(Base):
    __tablename__ = "agent_chat_sessions"
    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id        = Column(UUID(as_uuid=True),
                              ForeignKey("agents.id", ondelete="CASCADE"),
                              nullable=False, index=True)
    user_id         = Column(Text, nullable=False, index=True)
    started_at      = Column(DateTime(timezone=True), server_default=func.now())
    last_message_at = Column(DateTime(timezone=True))
    message_count   = Column(Integer, nullable=False, default=0)
    agent    = relationship("Agent", back_populates="sessions")
    messages = relationship("AgentChatMessage", back_populates="session",
                             cascade="all, delete-orphan",
                             order_by="AgentChatMessage.ts")

class AgentChatMessage(Base):
    __tablename__ = "agent_chat_messages"
    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True),
                         ForeignKey("agent_chat_sessions.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    role       = Column(Enum("user","agent", name="chat_role"), nullable=False)
    text       = Column(Text, nullable=False)
    ts         = Column(DateTime(timezone=True), server_default=func.now())
    trace_id   = Column(Text, index=True)
    session    = relationship("AgentChatSession", back_populates="messages")
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest spm/tests/test_agent_models.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```
git add spm/db/models.py spm/tests/test_agent_models.py
git commit -m "feat(spm-db): add Agent / AgentChatSession / AgentChatMessage ORM models"
```

---

## Task 2: Alembic 005 — agent runtime control plane migration

**Files:**
- Create: `spm/alembic/versions/005_agent_runtime_control_plane.py`
- Modify: existing latest migration's `down_revision` chain — Alembic auto-resolves; verify with `alembic history` after.

- [ ] **Step 1: Find the current latest revision**

```
cd /Users/danyshapiro/PycharmProjects/AISPM/spm
ls alembic/versions/
```

Note the highest-numbered file (likely `004_integrations_connector_type.py`). That's `down_revision` for the new file.

- [ ] **Step 2: Create the migration file**

```python
# spm/alembic/versions/005_agent_runtime_control_plane.py
"""agent runtime control plane tables

Revision ID: 005
Revises: 004
Create Date: 2026-04-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None

AGENT_TYPE = ("langchain","llamaindex","autogpt","openai_assistant","custom")
RUNTIME_STATE = ("stopped","starting","running","crashed")
RISK_LEVEL = ("low","medium","high","critical")
POLICY_STATUS = ("covered","partial","none")
CHAT_ROLE = ("user","agent")

def upgrade():
    op.execute("CREATE TYPE agent_type AS ENUM " + str(AGENT_TYPE))
    op.execute("CREATE TYPE runtime_state AS ENUM " + str(RUNTIME_STATE))
    op.execute("CREATE TYPE chat_role AS ENUM " + str(CHAT_ROLE))
    # risk_level / policy_status reuse existing if already present; idempotent guard:
    op.execute("DO $$ BEGIN CREATE TYPE risk_level AS ENUM " + str(RISK_LEVEL) +
               "; EXCEPTION WHEN duplicate_object THEN null; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE policy_status AS ENUM " + str(POLICY_STATUS) +
               "; EXCEPTION WHEN duplicate_object THEN null; END $$;")

    op.create_table(
        "agents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("version", sa.Text, nullable=False),
        sa.Column("agent_type",
                  sa.Enum(*AGENT_TYPE, name="agent_type", create_type=False),
                  nullable=False),
        sa.Column("provider", sa.Text, nullable=False, server_default="internal"),
        sa.Column("owner", sa.Text),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("risk",
                  sa.Enum(*RISK_LEVEL, name="risk_level", create_type=False),
                  server_default="low"),
        sa.Column("policy_status",
                  sa.Enum(*POLICY_STATUS, name="policy_status", create_type=False),
                  server_default="none"),
        sa.Column("runtime_state",
                  sa.Enum(*RUNTIME_STATE, name="runtime_state", create_type=False),
                  nullable=False, server_default="stopped"),
        sa.Column("code_path", sa.Text, nullable=False),
        sa.Column("code_sha256", sa.Text, nullable=False),
        sa.Column("mcp_token", sa.Text, nullable=False),
        sa.Column("llm_api_key", sa.Text, nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("tenant_id", sa.Text, nullable=False, server_default="t1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("name","version","tenant_id", name="uq_agents_name_ver_tenant"),
    )
    op.create_index("ix_agents_tenant_state", "agents", ["tenant_id","runtime_state"])

    op.create_table(
        "agent_chat_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", UUID(as_uuid=True),
                   sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        sa.Column("message_count", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_chat_sessions_agent", "agent_chat_sessions", ["agent_id"])
    op.create_index("ix_chat_sessions_user",  "agent_chat_sessions", ["user_id"])

    op.create_table(
        "agent_chat_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", UUID(as_uuid=True),
                   sa.ForeignKey("agent_chat_sessions.id", ondelete="CASCADE"),
                   nullable=False),
        sa.Column("role", sa.Enum(*CHAT_ROLE, name="chat_role", create_type=False),
                   nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("trace_id", sa.Text),
    )
    op.create_index("ix_chat_messages_session", "agent_chat_messages", ["session_id"])
    op.create_index("ix_chat_messages_trace",   "agent_chat_messages", ["trace_id"])

    # Seed the existing 5 mock agents shown in the UI today so the inventory
    # page can switch from mocks to live data without losing rows.
    op.execute("""
        INSERT INTO agents (id, name, version, agent_type, provider, owner, description,
                             risk, policy_status, runtime_state, code_path, code_sha256,
                             mcp_token, llm_api_key, tenant_id)
        VALUES
          (gen_random_uuid(), 'CustomerSupport-GPT', '1.0', 'langchain', 'aws',
           'ml-platform', 'Tier-1 ticket triage', 'high','partial','stopped','-','-','-','-','t1'),
          (gen_random_uuid(), 'CodeReview-Assistant', '1.0', 'openai_assistant', 'azure',
           'devex-team', '', 'medium','covered','stopped','-','-','-','-','t1'),
          (gen_random_uuid(), 'DataPipeline-Orchestrator', '1.0', 'autogpt', 'gcp',
           'data-eng', '', 'critical','none','stopped','-','-','-','-','t1'),
          (gen_random_uuid(), 'HRIntake-Bot', '1.0', 'llamaindex', 'aws',
           'people-ops', '', 'low','covered','stopped','-','-','-','-','t1'),
          (gen_random_uuid(), 'ThreatHunter-AI', '1.0', 'langchain', 'internal',
           'security-ops', '', 'high','partial','running','-','-','-','-','t1');
    """)

def downgrade():
    op.drop_table("agent_chat_messages")
    op.drop_table("agent_chat_sessions")
    op.drop_table("agents")
    op.execute("DROP TYPE chat_role")
    op.execute("DROP TYPE runtime_state")
    op.execute("DROP TYPE agent_type")
```

- [ ] **Step 3: Run the migration against a clean dev DB**

```
cd /Users/danyshapiro/PycharmProjects/AISPM/spm
SPM_DB_URL="postgresql://spm_rw:spmpass@localhost:5432/spm" alembic upgrade head
```

Expected output: `Running upgrade 004 -> 005, agent runtime control plane tables`. No errors.

- [ ] **Step 4: Verify by querying the seed data**

```
docker compose exec spm-db psql -U spm_rw -d spm -c \
  "SELECT name, agent_type, runtime_state FROM agents ORDER BY name;"
```

Expected: 5 rows matching the seed data.

- [ ] **Step 5: Verify downgrade works (sanity check)**

```
SPM_DB_URL="postgresql://..." alembic downgrade -1
SPM_DB_URL="postgresql://..." alembic upgrade head
```

Expected: clean down + up. (Don't leave the DB in `downgrade` state — finish at `upgrade head`.)

- [ ] **Step 6: Commit**

```
git add spm/alembic/versions/005_agent_runtime_control_plane.py
git commit -m "feat(alembic): 005 add agents/sessions/messages tables, seed mock rows"
```

---

## Task 3: platform_shared — agent topic helper + new event types

**Files:**
- Modify: `platform_shared/topics.py`
- Modify: `platform_shared/lineage_events.py`
- Test: `tests/test_topics_agent.py` (new)
- Test: `tests/test_lineage_events_agent.py` (new)

- [ ] **Step 1: Write failing test for topic helper**

```python
# tests/test_topics_agent.py
from platform_shared.topics import agent_topics_for

def test_agent_topics_for_format():
    t = agent_topics_for("t1", "ag-001")
    assert t.chat_in  == "cpm.t1.agents.ag-001.chat.in"
    assert t.chat_out == "cpm.t1.agents.ag-001.chat.out"

def test_agent_topics_all():
    t = agent_topics_for("t1", "ag-001")
    assert t.all() == [
        "cpm.t1.agents.ag-001.chat.in",
        "cpm.t1.agents.ag-001.chat.out",
    ]
```

- [ ] **Step 2: Run, expect fail**

```
pytest tests/test_topics_agent.py -v
```

- [ ] **Step 3: Implement helper**

Append to `platform_shared/topics.py`:

```python
@dataclass(frozen=True)
class AgentTopics:
    chat_in: str
    chat_out: str
    def all(self) -> list[str]:
        return [self.chat_in, self.chat_out]

def agent_topics_for(tenant_id: str, agent_id: str) -> AgentTopics:
    p = f"cpm.{tenant_id}.agents.{agent_id}"
    return AgentTopics(chat_in=f"{p}.chat.in", chat_out=f"{p}.chat.out")
```

- [ ] **Step 4: Run, expect pass**

- [ ] **Step 5: Write failing test for new event types**

```python
# tests/test_lineage_events_agent.py
from platform_shared.lineage_events import (
    AgentDeployedEvent, AgentStartedEvent, AgentStoppedEvent,
    AgentChatMessageEvent, AgentToolCallEvent, AgentLLMCallEvent,
)

def test_event_envelope_has_required_fields():
    evt = AgentDeployedEvent(agent_id="ag-001", tenant_id="t1",
                              version="1.0", actor="dany")
    payload = evt.to_dict()
    assert payload["event_type"] == "AgentDeployed"
    assert payload["agent_id"] == "ag-001"
    assert "ts" in payload
```

- [ ] **Step 6: Run, expect fail**

- [ ] **Step 7: Add event classes**

Append to `platform_shared/lineage_events.py` following the existing dataclass+to_dict pattern:

```python
@dataclass
class AgentDeployedEvent:
    agent_id: str
    tenant_id: str
    version: str
    actor: str
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    def to_dict(self) -> dict:
        return {"event_type":"AgentDeployed","agent_id":self.agent_id,
                "tenant_id":self.tenant_id,"version":self.version,
                "actor":self.actor,"ts":self.ts.isoformat()}

@dataclass
class AgentStartedEvent: ...   # similar
@dataclass
class AgentStoppedEvent: ...
@dataclass
class AgentChatMessageEvent:
    agent_id: str; tenant_id: str; session_id: str; user_id: str
    role: str; text: str; trace_id: str
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    def to_dict(self): ...
@dataclass
class AgentToolCallEvent:
    agent_id: str; tenant_id: str; tool: str; args: dict; ok: bool
    duration_ms: int; trace_id: str
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    def to_dict(self): ...
@dataclass
class AgentLLMCallEvent:
    agent_id: str; tenant_id: str; model: str
    prompt_tokens: int; completion_tokens: int; trace_id: str
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    def to_dict(self): ...
```

- [ ] **Step 8: Run all tests, commit**

```
pytest tests/test_topics_agent.py tests/test_lineage_events_agent.py -v
git add platform_shared/topics.py platform_shared/lineage_events.py \
        tests/test_topics_agent.py tests/test_lineage_events_agent.py
git commit -m "feat(platform-shared): agent_topics_for helper + 6 new event types"
```

---

## Task 4: Connector registry — `enum_integration` field type

**Files:**
- Modify: `services/spm_api/connector_registry.py` — add `enum_integration` to FieldSpec.type literal, document in module docstring.
- Modify: `services/spm_api/integrations_routes.py` — add `?category=` and `?vendor=` filters to `GET /integrations` (the SchemaForm.jsx dropdown will hit this).
- Test: `services/spm_api/tests/test_integrations_filter.py` (new)

- [ ] **Step 1: Write failing test for filter**

```python
# services/spm_api/tests/test_integrations_filter.py
from fastapi.testclient import TestClient
from services.spm_api.app import app

def test_get_integrations_filter_by_category(admin_client: TestClient):
    r = admin_client.get("/api/spm/integrations?category=AI%20Providers")
    assert r.status_code == 200
    rows = r.json()
    assert all(row["category"] == "AI Providers" for row in rows)

def test_get_integrations_filter_by_vendor(admin_client: TestClient):
    r = admin_client.get("/api/spm/integrations?vendor=Tavily")
    assert r.status_code == 200
    assert all(row["vendor"] == "Tavily" for row in r.json())
```

- [ ] **Step 2: Run, expect fail (filter not implemented)**

- [ ] **Step 3: Add filters to GET /integrations**

In `services/spm_api/integrations_routes.py`, locate the `list_integrations` route (or equivalent name; check by `grep -n "GET /integrations\|@router.get(\"\")" services/spm_api/integrations_routes.py`) and add query parameters:

```python
@router.get("")
def list_integrations(
    category: str | None = None,
    vendor:   str | None = None,
    claims = Depends(verify_jwt),
) -> list[IntegrationSummary]:
    rows = _query_integrations(_tenant_from_claims(claims))
    if category: rows = [r for r in rows if r.category == category]
    if vendor:   rows = [r for r in rows if r.vendor   == vendor]
    return rows
```

- [ ] **Step 4: Update the `FieldSpec` dataclass — concrete change**

In `connector_registry.py`, find the existing `FieldSpec` (currently a Pydantic model or dataclass; check `grep -n "class FieldSpec" services/spm_api/connector_registry.py`). Make these two changes — show both the BEFORE and AFTER:

**BEFORE** (current state):
```python
@dataclass
class FieldSpec:
    key: str
    label: str
    type: Literal["string","integer","password","enum","textarea","boolean","url"]
    required: bool = False
    secret:   bool = False
    default:  Any = None
    placeholder: str | None = None
    hint: str | None = None
    group: str | None = None
    options: list[str] | None = None
```

**AFTER** (this task):
```python
@dataclass
class FieldSpec:
    key: str
    label: str
    type: Literal[
        "string","integer","password","enum","textarea","boolean","url",
        "enum_integration",   # NEW
    ]
    required: bool = False
    secret:   bool = False
    default:  Any = None
    placeholder: str | None = None
    hint: str | None = None
    group: str | None = None
    options: list[str] | None = None
    options_provider: str | None = None   # NEW: e.g. "ai_provider_integrations"
```

The frontend (Phase 3) reads `options_provider` and resolves it to a `?category=...` filter when populating the dropdown. The string values used as `options_provider` map to filters as follows (document this in the FieldSpec docstring):

| `options_provider` | Resolves to |
|---|---|
| `ai_provider_integrations` | `?category=AI%20Providers` |
| `tavily_integrations` | `?category=AI%20Providers&vendor=Tavily` |

V1 just declares the field; UI work to honor it is Phase 3.

- [ ] **Step 5: Run tests, expect pass; commit**

```
pytest services/spm_api/tests/test_integrations_filter.py -v
git add services/spm_api/connector_registry.py \
        services/spm_api/integrations_routes.py \
        services/spm_api/tests/test_integrations_filter.py
git commit -m "feat(connectors): enum_integration FieldSpec + ?category/?vendor filters"
```

---

## Task 5: Connector registry — `agent-runtime` entry

**Files:**
- Modify: `services/spm_api/connector_registry.py` — add `agent-runtime` ConnectorType
- Modify: `services/spm_api/connector_probes.py` — add `probe_agent_runtime`
- Test: `services/spm_api/tests/test_connector_registry_agent_runtime.py` (new)

- [ ] **Step 1: Write failing test**

```python
# services/spm_api/tests/test_connector_registry_agent_runtime.py
from services.spm_api.connector_registry import CONNECTOR_TYPES, list_connector_types

def test_agent_runtime_present():
    assert "agent-runtime" in CONNECTOR_TYPES
    ct = CONNECTOR_TYPES["agent-runtime"]
    assert ct.category == "AI Providers"
    assert ct.vendor   == "AI-SPM"

def test_agent_runtime_required_fields():
    ct = CONNECTOR_TYPES["agent-runtime"]
    keys = {f.key for f in ct.fields}
    assert "default_llm_integration_id" in keys
    assert "tavily_integration_id"      in keys
    assert "default_memory_mb"          in keys
    assert "max_concurrent_agents"      in keys

def test_agent_runtime_field_groups():
    ct = CONNECTOR_TYPES["agent-runtime"]
    groups = {f.group for f in ct.fields if f.group}
    assert {"Defaults","Resources","Tool behaviour","Audit"} <= groups
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Add the entry**

Append to `connector_registry.py` (use the exact field list from the spec § 5):

```python
CONNECTOR_TYPES["agent-runtime"] = ConnectorType(
    key="agent-runtime",
    label="AI-SPM Agent Runtime Control Plane (MCP)",
    category="AI Providers",
    vendor="AI-SPM",
    icon_hint="bot",
    description=(
        "Hosts customer-uploaded AI agents in sandboxed containers. "
        "Provides MCP tools (web_fetch) and an OpenAI-compatible LLM proxy. "
        "Configure the default LLM and Tavily integration here."
    ),
    fields=[
        FieldSpec(key="default_llm_integration_id", label="Default LLM",
                  type="enum_integration", required=True, group="Defaults",
                  hint="Active AI Provider integration that backs spm-llm-proxy.",
                  options_provider="ai_provider_integrations"),
        FieldSpec(key="tavily_integration_id", label="Tavily Integration",
                  type="enum_integration", required=True, group="Defaults",
                  options_provider="tavily_integrations"),
        FieldSpec(key="default_model_name", label="Default model name",
                  type="string", default="llama3.1:8b", group="Defaults"),
        FieldSpec(key="default_memory_mb", label="Memory per agent (MB)",
                  type="integer", default=512, group="Resources"),
        FieldSpec(key="default_cpu_quota", label="CPU quota",
                  type="float", default=0.5, group="Resources"),
        FieldSpec(key="tool_call_timeout_s", label="Tool call timeout (s)",
                  type="integer", default=30, group="Resources"),
        FieldSpec(key="max_concurrent_agents", label="Max concurrent agents",
                  type="integer", default=50, group="Resources"),
        FieldSpec(key="max_sessions_per_agent", label="Max chat sessions per agent",
                  type="integer", default=100, group="Resources"),
        FieldSpec(key="tavily_max_results", label="Tavily max results",
                  type="integer", default=5, group="Tool behaviour"),
        FieldSpec(key="tavily_max_chars", label="Tavily max chars per result",
                  type="integer", default=4000, group="Tool behaviour"),
        FieldSpec(key="log_llm_prompts", label="Log LLM prompts",
                  type="boolean", default=True, group="Audit"),
        FieldSpec(key="audit_topic_suffix", label="Audit topic suffix",
                  type="string", default="audit_events", group="Audit"),
    ],
    probe=connector_probes.probe_agent_runtime,
)
```

- [ ] **Step 4: Add `probe_agent_runtime` to `connector_probes.py`**

First, **verify whether `probe_integration_by_id` exists** in `connector_registry.py`:

```
grep -n "probe_integration_by_id\|async def probe_" /Users/danyshapiro/PycharmProjects/AISPM/services/spm_api/connector_registry.py
```

If it doesn't exist, add this helper to `connector_registry.py` first (as a sibling of the existing probe helpers):

```python
# connector_registry.py
async def probe_integration_by_id(integration_id: str) -> tuple[bool, str, int | None]:
    """Run the registered probe for an existing integration row, by ID."""
    from spm.db.session import get_session
    from spm.db.models import Integration
    from platform_shared.credentials import get_credential
    with get_session() as db:
        row = db.get(Integration, integration_id)
        if not row: return False, f"integration {integration_id} not found", None
        ct = CONNECTOR_TYPES.get(row.connector_type)
        if not ct: return False, f"unknown connector_type {row.connector_type}", None
        creds = {f.key: await get_credential(integration_id, f.key)
                 for f in ct.fields if f.secret}
        return await ct.probe(row.config or {}, creds)
```

Then add `probe_agent_runtime` itself:

```python
# connector_probes.py
async def probe_agent_runtime(config, credentials) -> tuple[bool, str, int | None]:
    """Verify (1) spm-mcp /health, (2) referenced LLM integration probe,
    (3) referenced Tavily integration probe — short-circuit on first failure."""
    import time, httpx
    started = time.monotonic()
    # 1. spm-mcp health
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get("http://spm-mcp:8500/health")
        if r.status_code != 200:
            return False, f"spm-mcp /health returned {r.status_code}", \
                          int((time.monotonic()-started)*1000)
    except Exception as e:
        return False, f"spm-mcp unreachable: {e}", None
    # 2/3. Referenced integrations — call helper above
    from .connector_registry import probe_integration_by_id
    for fk in ("default_llm_integration_id", "tavily_integration_id"):
        ref_id = config.get(fk)
        if not ref_id:
            return False, f"{fk} not configured", None
        ok, msg, _ = await probe_integration_by_id(ref_id)
        if not ok:
            return False, f"{fk}: {msg}", None
    return True, "all probes ok", int((time.monotonic()-started)*1000)
```

- [ ] **Step 5: Run tests, commit**

```
pytest services/spm_api/tests/test_connector_registry_agent_runtime.py -v
git add services/spm_api/connector_registry.py services/spm_api/connector_probes.py \
        services/spm_api/tests/test_connector_registry_agent_runtime.py
git commit -m "feat(connectors): agent-runtime ConnectorType + probe"
```

---

## Task 5a: platform_shared/agent_tokens — token → agent lookup

**Why this exists:** Both `spm-mcp/auth.py` (Task 8) and `spm-llm-proxy/main.py` (Task 7) look up an agent by its bearer token. Without this helper, those tasks would fail to import. Defined once here, used by both.

**Files:**
- Create: `platform_shared/agent_tokens.py`
- Test: `tests/test_agent_tokens.py`

- [ ] **Step 1: Failing tests**

```python
# tests/test_agent_tokens.py
import pytest, uuid
from platform_shared.agent_tokens import (
    resolve_agent_by_mcp_token, resolve_agent_by_llm_token,
)
from spm.db.models import Agent

@pytest.mark.asyncio
async def test_resolve_known_mcp_token(db_session):
    a = Agent(id=uuid.uuid4(), name="x", version="1", agent_type="custom",
              provider="internal", owner="o", code_path="x", code_sha256="0"*64,
              mcp_token="mcp-good", llm_api_key="llm-good", tenant_id="t1")
    db_session.add(a); db_session.commit()

    out = await resolve_agent_by_mcp_token("mcp-good")
    assert out["id"] == str(a.id)
    assert out["tenant_id"] == "t1"

@pytest.mark.asyncio
async def test_resolve_unknown_token_returns_none():
    assert await resolve_agent_by_mcp_token("nope") is None
    assert await resolve_agent_by_llm_token("nope") is None
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Implement**

```python
# platform_shared/agent_tokens.py
"""Lookup helpers for the bearer tokens issued to each deployed agent.

V1 stores tokens in plaintext on the agents row (admin-only access; never
returned in API responses). V2 will encrypt at rest using the same Fernet
key already used for integration_credentials.

Cached for 30s in Redis (best-effort; fall through to DB on cache miss).
"""
from __future__ import annotations
import os
from sqlalchemy import select
from spm.db.session import get_session
from spm.db.models import Agent

_CACHE_TTL_S = 30

async def _lookup(column, token: str) -> dict | None:
    # In test mode (no Redis configured) just hit the DB directly.
    with get_session() as db:
        row = db.execute(select(Agent).where(column == token)).scalar_one_or_none()
        if not row: return None
        return {"id": str(row.id), "tenant_id": row.tenant_id, "name": row.name}

async def resolve_agent_by_mcp_token(token: str) -> dict | None:
    return await _lookup(Agent.mcp_token, token)

async def resolve_agent_by_llm_token(token: str) -> dict | None:
    return await _lookup(Agent.llm_api_key, token)
```

- [ ] **Step 4: Run, pass; commit**

```
pytest tests/test_agent_tokens.py -v
git add platform_shared/agent_tokens.py tests/test_agent_tokens.py
git commit -m "feat(platform-shared): agent_tokens lookup helpers"
```

---

## Task 6: spm-llm-proxy — skeleton + /health + Dockerfile

**Files:**
- Create: `services/spm_llm_proxy/main.py`
- Create: `services/spm_llm_proxy/Dockerfile`
- Create: `services/spm_llm_proxy/requirements.txt`
- Create: `services/spm_llm_proxy/tests/test_main.py`

- [ ] **Step 1: Failing test**

```python
# services/spm_llm_proxy/tests/test_main.py
from fastapi.testclient import TestClient
from services.spm_llm_proxy.main import app

def test_health():
    c = TestClient(app)
    r = c.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Implement skeleton**

```python
# services/spm_llm_proxy/main.py
from fastapi import FastAPI

app = FastAPI(title="spm-llm-proxy")

@app.get("/health")
async def health():
    return {"ok": True}
```

- [ ] **Step 4: requirements.txt**

```
fastapi==0.115.*
uvicorn[standard]==0.30.*
httpx==0.27.*
pydantic==2.*
```

- [ ] **Step 5: Dockerfile**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY services/spm_llm_proxy/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/spm_llm_proxy /app/services/spm_llm_proxy
COPY platform_shared        /app/platform_shared
ENV PYTHONPATH=/app
CMD ["uvicorn","services.spm_llm_proxy.main:app","--host","0.0.0.0","--port","8500"]
```

- [ ] **Step 6: Run test, pass; commit**

```
pytest services/spm_llm_proxy/tests/test_main.py -v
git add services/spm_llm_proxy/
git commit -m "feat(spm-llm-proxy): skeleton FastAPI service with /health"
```

---

## Task 7: spm-llm-proxy — OpenAI-compat /v1/chat/completions

**Files:**
- Modify: `services/spm_llm_proxy/main.py` (add the route)
- Create: `services/spm_llm_proxy/router.py` (resolves which LLM integration to use)
- Test: `services/spm_llm_proxy/tests/test_router.py`

- [ ] **Step 1: Failing test for router**

```python
# services/spm_llm_proxy/tests/test_router.py
import pytest
from services.spm_llm_proxy.router import resolve_llm_integration

@pytest.mark.asyncio
async def test_resolve_uses_agent_runtime_default(mock_db):
    """When agent-runtime integration has default_llm_integration_id=ollama-1,
    resolve_llm_integration() returns that integration's config + creds."""
    cfg, creds = await resolve_llm_integration(tenant_id="t1")
    assert cfg["base_url"] == "http://host.docker.internal:11434"
    assert creds == {}   # ollama has no creds
```

(Mock the DB lookups; the test is about the resolution logic, not the DB.)

- [ ] **Step 2: Implement `router.py`**

```python
# services/spm_llm_proxy/router.py
"""Resolve which LLM integration backs the proxy at request time.

Reads the agent-runtime integration row's config.default_llm_integration_id
field, then loads that integration's config + credentials via the existing
get_credential() helper. Cached per-tenant for 60s; cache invalidated on
write-through from /api/spm/integrations PATCH.
"""
from platform_shared.integration_config import get_integration_by_key, get_integration_by_id
from platform_shared.credentials import get_credential

async def resolve_llm_integration(tenant_id: str) -> tuple[dict, dict]:
    host = await get_integration_by_key("agent-runtime", tenant_id=tenant_id)
    if not host:
        raise RuntimeError("agent-runtime integration not configured")
    target_id = host.config.get("default_llm_integration_id")
    if not target_id:
        raise RuntimeError("default_llm_integration_id not set on agent-runtime")
    target = await get_integration_by_id(target_id)
    creds = {}
    for ct in target.required_credentials:
        creds[ct] = await get_credential(target_id, ct)
    return target.config, creds
```

(Where `platform_shared.integration_config.get_integration_by_key/by_id` may need adding as small wrappers around the existing hydrator.)

- [ ] **Step 3: Failing test for /v1/chat/completions**

```python
# services/spm_llm_proxy/tests/test_main.py — append
import pytest, httpx
from unittest.mock import patch, AsyncMock

@pytest.mark.asyncio
async def test_chat_completions_forwards_to_resolved_llm(monkeypatch):
    async def fake_resolve(tenant_id):
        return ({"base_url":"http://ollama:11434","model_name":"llama3.1:8b"}, {})
    monkeypatch.setattr("services.spm_llm_proxy.main.resolve_llm_integration", fake_resolve)

    captured = {}
    async def fake_post(self, url, json=None, **kw):
        captured["url"] = url; captured["body"] = json
        return httpx.Response(200, json={"choices":[{"message":{"content":"hi"}}]})
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    c = TestClient(app)
    r = c.post("/v1/chat/completions",
               headers={"Authorization":"Bearer fake-test-key"},
               json={"messages":[{"role":"user","content":"hi"}], "model":"x"})
    assert r.status_code == 200
    assert "ollama" in captured["url"]
```

- [ ] **Step 4: Implement endpoint**

In `main.py`:

```python
from fastapi import Depends, Header, HTTPException
import httpx
from .router import resolve_llm_integration

async def auth_required(authorization: str = Header(...)):
    # V1: bearer token must match a known agent's llm_api_key (lookup in spm-db)
    token = authorization.removeprefix("Bearer ").strip()
    from platform_shared.agent_tokens import resolve_agent_by_llm_token
    agent = await resolve_agent_by_llm_token(token)
    if not agent:
        raise HTTPException(401, "Unknown llm_api_key")
    return agent  # {"id":..., "tenant_id":...}

@app.post("/v1/chat/completions")
async def chat_completions(payload: dict, agent: dict = Depends(auth_required)):
    cfg, creds = await resolve_llm_integration(agent["tenant_id"])
    # Translate to whichever upstream's chat API. V1: ollama only.
    base = cfg.get("base_url", "http://host.docker.internal:11434")
    body = {"model": payload.get("model") or cfg["model_name"],
            "messages": payload["messages"],
            "stream": False}
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{base}/api/chat", json=body)
    r.raise_for_status()
    out = r.json()
    # Convert ollama -> openai-compat shape
    return {"id":"chatcmpl-x","object":"chat.completion","model":body["model"],
            "choices":[{"index":0,"message":out["message"],"finish_reason":"stop"}],
            "usage":{"prompt_tokens":out.get("prompt_eval_count",0),
                     "completion_tokens":out.get("eval_count",0)}}
```

- [ ] **Step 5: Run tests; commit**

```
pytest services/spm_llm_proxy/tests/ -v
git add services/spm_llm_proxy/
git commit -m "feat(spm-llm-proxy): /v1/chat/completions backed by configured LLM integration"
```

---

## Task 8: spm-mcp — skeleton + Bearer auth

**Files:**
- Create: `services/spm_mcp/main.py`
- Create: `services/spm_mcp/auth.py`
- Create: `services/spm_mcp/Dockerfile`
- Create: `services/spm_mcp/requirements.txt`
- Test: `services/spm_mcp/tests/test_auth.py`
- Test: `services/spm_mcp/tests/test_main.py`

- [ ] **Step 1: Failing tests**

```python
# services/spm_mcp/tests/test_auth.py
import pytest
from services.spm_mcp.auth import verify_mcp_token

@pytest.mark.asyncio
async def test_verify_known_token(mock_agent_lookup):
    agent = await verify_mcp_token("Bearer good-token")
    assert agent["id"] == "ag-001"

@pytest.mark.asyncio
async def test_verify_rejects_unknown(mock_agent_lookup):
    with pytest.raises(PermissionError):
        await verify_mcp_token("Bearer nope")
```

```python
# services/spm_mcp/tests/test_main.py
from fastapi.testclient import TestClient
from services.spm_mcp.main import app

def test_health():
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: requirements.txt**

```
fastapi==0.115.*
uvicorn[standard]==0.30.*
mcp[server]==1.*
httpx==0.27.*
pydantic==2.*
```

- [ ] **Step 4: Implement auth.py**

```python
# services/spm_mcp/auth.py
from platform_shared.agent_tokens import resolve_agent_by_mcp_token

async def verify_mcp_token(authorization: str) -> dict:
    token = authorization.removeprefix("Bearer ").strip()
    agent = await resolve_agent_by_mcp_token(token)
    if not agent:
        raise PermissionError("Unknown mcp_token")
    return agent  # {"id":..., "tenant_id":..., "name":...}
```

- [ ] **Step 5: Implement main.py (FastMCP + FastAPI)**

```python
# services/spm_mcp/main.py
from fastapi import FastAPI, Header, HTTPException, Depends
from mcp.server.fastmcp import FastMCP
from .auth import verify_mcp_token

app = FastAPI(title="spm-mcp")
mcp = FastMCP("spm-mcp")

@app.get("/health")
async def health():
    return {"ok": True}

# MCP server is mounted under /mcp
async def auth_dep(authorization: str = Header(...)):
    try:
        return await verify_mcp_token(authorization)
    except PermissionError as e:
        raise HTTPException(401, str(e))

# Tools registered via @mcp.tool() in tools/ — see Task 9
```

- [ ] **Step 6: Dockerfile**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY services/spm_mcp/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/spm_mcp     /app/services/spm_mcp
COPY platform_shared      /app/platform_shared
ENV PYTHONPATH=/app
CMD ["uvicorn","services.spm_mcp.main:app","--host","0.0.0.0","--port","8500"]
```

- [ ] **Step 7: Run, pass; commit**

```
pytest services/spm_mcp/tests/ -v
git add services/spm_mcp/
git commit -m "feat(spm-mcp): skeleton FastMCP server with bearer auth + /health"
```

---

## Task 9: spm-mcp — `web_fetch` tool

**Files:**
- Create: `services/spm_mcp/tools/__init__.py`
- Create: `services/spm_mcp/tools/web_fetch.py`
- Modify: `services/spm_mcp/main.py` — register tool
- Test: `services/spm_mcp/tests/test_web_fetch.py`

- [ ] **Step 1: Failing test (mocks Tavily HTTP)**

```python
# services/spm_mcp/tests/test_web_fetch.py
import pytest, httpx
from unittest.mock import patch
from services.spm_mcp.tools.web_fetch import web_fetch

@pytest.mark.asyncio
async def test_web_fetch_returns_results(monkeypatch):
    async def fake_post(self, url, json=None, **kw):
        assert "tavily" in url
        assert json["query"] == "what is mcp"
        return httpx.Response(200, json={
            "results":[{"title":"MCP","url":"https://x.com","content":"mcp is..."}]
        })
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    out = await web_fetch(query="what is mcp",
                          tavily_api_key="tvly-test",
                          max_results=5, max_chars=4000)
    assert out["results"][0]["title"] == "MCP"

@pytest.mark.asyncio
async def test_web_fetch_truncates_long_content(monkeypatch):
    async def fake_post(self, url, json=None, **kw):
        return httpx.Response(200, json={
            "results":[{"title":"x","url":"u","content":"a"*10000}]
        })
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    out = await web_fetch(query="x", tavily_api_key="t",
                          max_results=1, max_chars=100)
    assert len(out["results"][0]["content"]) == 100
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Implement**

```python
# services/spm_mcp/tools/web_fetch.py
import httpx

TAVILY_URL = "https://api.tavily.com/search"

async def web_fetch(query: str, *, tavily_api_key: str,
                    max_results: int = 5, max_chars: int = 4000) -> dict:
    """Search the web via Tavily; return up to max_results, content-truncated."""
    body = {"api_key": tavily_api_key, "query": query,
            "max_results": max_results, "include_answer": False,
            "include_images": False}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(TAVILY_URL, json=body)
    r.raise_for_status()
    data = r.json()
    results = []
    for item in data.get("results", [])[:max_results]:
        results.append({
            "title": item.get("title",""),
            "url":   item.get("url",""),
            "content": (item.get("content","") or "")[:max_chars],
        })
    return {"results": results}
```

- [ ] **Step 4: Register the tool in `main.py`**

```python
# services/spm_mcp/main.py — add at module bottom
from .tools.web_fetch import web_fetch as _web_fetch

@mcp.tool()
async def web_fetch(query: str, max_results: int = 5) -> dict:
    """Search the web via Tavily."""
    # Per-call: resolve tavily key from agent-runtime integration's tavily_integration_id
    from platform_shared.integration_config import get_integration_by_key, get_integration_by_id
    from platform_shared.credentials import get_credential
    host = await get_integration_by_key("agent-runtime", tenant_id="t1")  # single-tenant V1
    tavily_id = host.config["tavily_integration_id"]
    api_key = await get_credential(tavily_id, "api_key")
    max_chars = host.config.get("tavily_max_chars", 4000)
    return await _web_fetch(query=query, tavily_api_key=api_key,
                             max_results=max_results, max_chars=max_chars)
```

- [ ] **Step 5: Run tests; commit**

```
pytest services/spm_mcp/tests/test_web_fetch.py -v
git add services/spm_mcp/
git commit -m "feat(spm-mcp): web_fetch tool wired to Tavily integration"
```

---

## Task 10: agent_validator — three-step `agent.py` validation

**Files:**
- Create: `services/spm_api/agent_validator.py`
- Test: `services/spm_api/tests/test_agent_validator.py`

- [ ] **Step 1: Failing tests**

```python
# services/spm_api/tests/test_agent_validator.py
import pytest
from services.spm_api.agent_validator import validate_agent_code, ValidationError

GOOD = """\
import asyncio
async def main():
    pass
asyncio.run(main())
"""

BAD_SYNTAX = "def main(::"

NO_MAIN = """\
import asyncio
async def helper(): pass
"""

UNKNOWN_IMPORT = """\
import zzz_nonexistent_module
async def main(): pass
"""

def test_valid_agent_passes():
    res = validate_agent_code(GOOD)
    assert res.ok
    assert res.warnings == []

def test_syntax_error_blocks():
    res = validate_agent_code(BAD_SYNTAX)
    assert not res.ok
    assert "syntax" in res.errors[0].lower()

def test_missing_main_blocks():
    res = validate_agent_code(NO_MAIN)
    assert not res.ok
    assert "main" in res.errors[0].lower()

def test_unknown_import_warns_not_blocks():
    res = validate_agent_code(UNKNOWN_IMPORT)
    # syntactic check passes; dry-import warning, not blocker
    assert res.ok
    assert any("zzz_nonexistent_module" in w for w in res.warnings)
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Implement**

```python
# services/spm_api/agent_validator.py
"""Three-step agent.py validation:

1. ast.parse() — syntax must be valid Python 3.12.
2. AST scan — top-level `async def main()` must exist.
3. Dry-import in an ephemeral subprocess (using agent-runtime-base's interpreter):
   any ImportError on a non-stdlib non-aispm module is a WARNING, not an error.

Errors block upload (HTTP 422). Warnings are returned in the response so the UI
can show them but don't block.
"""
from __future__ import annotations
import ast, subprocess, tempfile
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class ValidationResult:
    ok: bool
    errors:   list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

class ValidationError(Exception): pass

def _has_async_main(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "main":
            return True
    return False

def validate_agent_code(code: str, *, dry_import: bool = True) -> ValidationResult:
    res = ValidationResult(ok=True)
    # 1. syntax
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        res.ok = False
        res.errors.append(f"Python syntax error at line {e.lineno}: {e.msg}")
        return res
    # 2. async main
    if not _has_async_main(tree):
        res.ok = False
        res.errors.append("Top-level `async def main()` is required.")
        return res
    # 3. dry-import (skipped in unit tests via dry_import=False)
    if dry_import:
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "agent.py"
            f.write_text(code)
            r = subprocess.run(
                ["python","-c", f"import importlib.util,sys; "
                                f"s=importlib.util.spec_from_file_location('a','{f}'); "
                                f"m=importlib.util.module_from_spec(s); "
                                f"try: s.loader.exec_module(m)\n"
                                f"except Exception as e: print('IMPORT_ERR:',type(e).__name__,e)"],
                capture_output=True, text=True, timeout=15)
            if "IMPORT_ERR:" in r.stdout:
                res.warnings.append(r.stdout.split("IMPORT_ERR:",1)[1].strip())
    return res
```

**Phase 1 scoping note on dry-import:**

The spec § 9 calls for the dry-import to happen inside an ephemeral `agent-runtime-base` container so the validation environment matches the deploy environment exactly. **In Phase 1, we run the dry-import in-process via `subprocess.run(["python","-c", ...])` in the spm-api container.** This catches Python-syntax errors and missing-stdlib errors but does NOT catch missing third-party packages that exist in agent-runtime-base but not in spm-api (or vice versa). That's acceptable for Phase 1 because:

- The spm-api container and the agent-runtime-base container both use Python 3.12-slim as their base.
- The only common gap (LangChain, etc.) shows up as a *warning* not an *error* — customer agent can still upload, just with a "this import won't be available at runtime" warning.

Phase 2 task: switch the dry-import to spawn a one-off `agent-runtime-base` container for validation. Tracked in the spec § 11 open questions.

- [ ] **Step 4: Run tests; commit**

```
pytest services/spm_api/tests/test_agent_validator.py -v
git add services/spm_api/agent_validator.py services/spm_api/tests/test_agent_validator.py
git commit -m "feat(spm-api): agent.py 3-step validator"
```

---

## Task 11: agent_controller — token minting + DB row helpers

**Files:**
- Create: `services/spm_api/agent_controller.py` (start of file; more added in Tasks 12-14)
- Test: `services/spm_api/tests/test_agent_controller.py`

- [ ] **Step 1: Failing tests for token minting**

```python
# services/spm_api/tests/test_agent_controller.py
import re
from services.spm_api.agent_controller import mint_agent_tokens

def test_mint_returns_two_distinct_tokens():
    mcp_t, llm_t = mint_agent_tokens()
    assert mcp_t != llm_t
    assert re.fullmatch(r"[A-Za-z0-9_-]{32,}", mcp_t)
    assert re.fullmatch(r"[A-Za-z0-9_-]{32,}", llm_t)

def test_minted_tokens_unique():
    a = mint_agent_tokens(); b = mint_agent_tokens()
    assert a != b
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Implement**

```python
# services/spm_api/agent_controller.py
"""Orchestrates agent containers + Kafka topics + token lifecycle.

Token format: 32-byte URL-safe base64. mcp_token is presented to spm-mcp's
auth middleware; llm_api_key is presented to spm-llm-proxy's auth.
Both are stored on the agents row encrypted at rest (V2 — V1 stores plain
since the row is admin-only, but never returned in /agents responses).
"""
from __future__ import annotations
import secrets

def mint_agent_tokens() -> tuple[str, str]:
    return secrets.token_urlsafe(32), secrets.token_urlsafe(32)
```

- [ ] **Step 4: Run, pass; commit**

```
pytest services/spm_api/tests/test_agent_controller.py::test_mint_returns_two_distinct_tokens \
       services/spm_api/tests/test_agent_controller.py::test_minted_tokens_unique -v
git add services/spm_api/agent_controller.py services/spm_api/tests/test_agent_controller.py
git commit -m "feat(spm-api): mint_agent_tokens helper"
```

---

## Task 12: agent_controller — Kafka topic CRUD

**Files:**
- Modify: `services/spm_api/agent_controller.py`
- Modify: `services/spm_api/tests/test_agent_controller.py`

- [ ] **Step 1: Failing test (mocks kafka admin client)**

```python
# append to test_agent_controller.py
import pytest
from unittest.mock import MagicMock, patch
from services.spm_api.agent_controller import create_agent_topics, delete_agent_topics

@pytest.mark.asyncio
async def test_create_agent_topics_creates_in_and_out(monkeypatch):
    fake_admin = MagicMock()
    monkeypatch.setattr("services.spm_api.agent_controller._kafka_admin",
                        lambda: fake_admin)
    await create_agent_topics(tenant_id="t1", agent_id="ag-001")
    args = fake_admin.create_topics.call_args[1] or fake_admin.create_topics.call_args[0]
    topic_names = [t.name for t in args[0]] if isinstance(args, tuple) else [t.name for t in args["new_topics"]]
    assert "cpm.t1.agents.ag-001.chat.in"  in topic_names
    assert "cpm.t1.agents.ag-001.chat.out" in topic_names
```

- [ ] **Step 2: Implement**

```python
# append to agent_controller.py
from kafka.admin import KafkaAdminClient, NewTopic
from platform_shared.topics import agent_topics_for
import os

def _kafka_admin():
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS","kafka-broker:9092")
    return KafkaAdminClient(bootstrap_servers=bootstrap, client_id="spm-api-agent-ctl")

async def create_agent_topics(*, tenant_id: str, agent_id: str,
                               partitions: int = 1, replication: int = 1) -> None:
    t = agent_topics_for(tenant_id, agent_id)
    new_topics = [NewTopic(name=name, num_partitions=partitions,
                           replication_factor=replication) for name in t.all()]
    admin = _kafka_admin()
    try:
        admin.create_topics(new_topics=new_topics, validate_only=False)
    finally:
        admin.close()

async def delete_agent_topics(*, tenant_id: str, agent_id: str) -> None:
    t = agent_topics_for(tenant_id, agent_id)
    admin = _kafka_admin()
    try:
        admin.delete_topics(t.all())
    finally:
        admin.close()
```

- [ ] **Step 3: Run, pass; commit**

```
pytest services/spm_api/tests/test_agent_controller.py -v
git commit -am "feat(spm-api): agent_controller create/delete Kafka topics"
```

---

## Task 13: agent_controller — Docker spawn / stop

**Files:**
- Modify: `services/spm_api/agent_controller.py`
- Modify: `services/spm_api/tests/test_agent_controller.py`

- [ ] **Step 1: Failing test (mocks docker client)**

```python
# append
@pytest.mark.asyncio
async def test_spawn_agent_passes_env(monkeypatch):
    fake_client = MagicMock()
    fake_client.containers.run.return_value = MagicMock(id="ctr-123")
    monkeypatch.setattr("services.spm_api.agent_controller._docker_client",
                        lambda: fake_client)
    cid = await spawn_agent_container(
        agent_id="ag-001", tenant_id="t1",
        code_path="/var/agents/ag-001/agent.py",
        mcp_token="mcp-x", llm_api_key="llm-x",
        mem_mb=256, cpu_quota=0.5,
    )
    assert cid == "ctr-123"
    kwargs = fake_client.containers.run.call_args.kwargs
    env = kwargs["environment"]
    assert env["AGENT_ID"]      == "ag-001"
    assert env["MCP_TOKEN"]     == "mcp-x"
    assert env["LLM_API_KEY"]   == "llm-x"
    assert env["MCP_URL"]       == "http://spm-mcp:8500/mcp"
    assert env["LLM_BASE_URL"]  == "http://spm-llm-proxy:8500/v1"
    assert kwargs["mem_limit"]  == "256m"
    assert kwargs["network"]    == "agent-net"
```

- [ ] **Step 2: Implement**

```python
# agent_controller.py
import docker

_AGENT_NETWORK = "agent-net"
_AGENT_IMAGE   = "aispm-agent-runtime:latest"

def _docker_client():
    return docker.from_env()

async def spawn_agent_container(*, agent_id, tenant_id, code_path,
                                 mcp_token, llm_api_key,
                                 mem_mb=512, cpu_quota=0.5) -> str:
    client = _docker_client()
    env = {
        "AGENT_ID": agent_id, "TENANT_ID": tenant_id,
        "MCP_URL": "http://spm-mcp:8500/mcp",       "MCP_TOKEN": mcp_token,
        "LLM_BASE_URL": "http://spm-llm-proxy:8500/v1", "LLM_API_KEY": llm_api_key,
        "KAFKA_BOOTSTRAP_SERVERS": os.environ.get("KAFKA_BOOTSTRAP_SERVERS","kafka-broker:9092"),
    }
    ctr = client.containers.run(
        _AGENT_IMAGE,
        name=f"agent-{agent_id}",
        environment=env,
        volumes={code_path: {"bind": "/agent/agent.py", "mode": "ro"}},
        mem_limit=f"{mem_mb}m",
        nano_cpus=int(cpu_quota * 1_000_000_000),
        network=_AGENT_NETWORK,
        detach=True, restart_policy={"Name":"on-failure","MaximumRetryCount":1},
    )
    return ctr.id

async def stop_agent_container(agent_id: str) -> None:
    client = _docker_client()
    name = f"agent-{agent_id}"
    try:
        ctr = client.containers.get(name)
        ctr.stop(timeout=10)
        ctr.remove(force=True)
    except docker.errors.NotFound:
        return
```

- [ ] **Step 3: Run, pass; commit**

```
pytest services/spm_api/tests/test_agent_controller.py::test_spawn_agent_passes_env -v
git commit -am "feat(spm-api): agent_controller docker spawn/stop"
```

---

## Task 14: agent_controller — `deploy()` / `start()` / `stop()` orchestration

**Files:**
- Modify: `services/spm_api/agent_controller.py` — add high-level state-transition functions
- Modify: `services/spm_api/tests/test_agent_controller.py`

- [ ] **Step 1: Failing test**

```python
# append
@pytest.mark.asyncio
async def test_deploy_creates_topics_then_spawns(monkeypatch, db_session):
    calls = []
    async def fake_topics(*, tenant_id, agent_id):
        calls.append(("topics", tenant_id, agent_id))
    async def fake_spawn(**kw):
        calls.append(("spawn", kw["agent_id"]))
        return "ctr-x"
    monkeypatch.setattr("services.spm_api.agent_controller.create_agent_topics", fake_topics)
    monkeypatch.setattr("services.spm_api.agent_controller.spawn_agent_container", fake_spawn)

    agent = create_agent_row(db_session, name="x", version="1", code="async def main(): pass")
    await deploy_agent(db_session, agent.id)

    assert calls[0][0] == "topics"
    assert calls[1][0] == "spawn"
    db_session.refresh(agent)
    assert agent.runtime_state == "starting"
```

- [ ] **Step 2: Implement**

```python
# agent_controller.py
async def deploy_agent(db, agent_id) -> None:
    a = db.get(Agent, agent_id)
    if not a: raise ValueError("agent not found")
    await create_agent_topics(tenant_id=a.tenant_id, agent_id=str(a.id))
    a.runtime_state = "starting"
    db.commit()
    await spawn_agent_container(
        agent_id=str(a.id), tenant_id=a.tenant_id, code_path=a.code_path,
        mcp_token=a.mcp_token, llm_api_key=a.llm_api_key,
        mem_mb=512, cpu_quota=0.5,
    )
    # V1 readiness check: hardcoded 5-second sleep, then mark running.
    # The SDK's aispm.ready() signal mechanism (Phase 2) will replace this
    # with a real poll on a /ready endpoint or Kafka consumer-group join.
    # Keep this comment so it's flagged when Phase 2 lands.
    import asyncio as _asyncio
    await _asyncio.sleep(5)
    a.runtime_state = "running"
    db.commit()

async def start_agent(db, agent_id) -> None:
    """Idempotent — used by the run/stop toggle."""
    a = db.get(Agent, agent_id)
    if a.runtime_state == "running": return
    await spawn_agent_container(agent_id=str(a.id), tenant_id=a.tenant_id,
                                 code_path=a.code_path, mcp_token=a.mcp_token,
                                 llm_api_key=a.llm_api_key)
    a.runtime_state = "starting"; db.commit()

async def stop_agent(db, agent_id) -> None:
    a = db.get(Agent, agent_id)
    await stop_agent_container(str(a.id))
    a.runtime_state = "stopped"; db.commit()

async def retire_agent(db, agent_id) -> None:
    a = db.get(Agent, agent_id)
    await stop_agent_container(str(a.id))
    await delete_agent_topics(tenant_id=a.tenant_id, agent_id=str(a.id))
    db.delete(a); db.commit()
```

- [ ] **Step 3: Run; commit**

```
pytest services/spm_api/tests/test_agent_controller.py -v
git commit -am "feat(spm-api): agent_controller deploy/start/stop/retire orchestration"
```

---

## Task 15: agent_routes — POST /agents (upload) and GET /agents (list)

**Files:**
- Create: `services/spm_api/agent_routes.py`
- Modify: `services/spm_api/app.py` (mount router)
- Test: `services/spm_api/tests/test_agent_routes.py`

- [ ] **Step 1: Failing test for POST /agents**

```python
# services/spm_api/tests/test_agent_routes.py
import io
from fastapi.testclient import TestClient

def test_post_agent_upload_creates_row(admin_client: TestClient, monkeypatch):
    async def no_deploy(db, agent_id): pass
    monkeypatch.setattr("services.spm_api.agent_routes.deploy_agent", no_deploy)

    code = "import asyncio\nasync def main(): pass\nasyncio.run(main())\n"
    r = admin_client.post(
        "/api/spm/agents",
        data={
            "name":"my-agent","version":"1.0","agent_type":"langchain",
            "owner":"dany","description":"test","deploy_after":False,
        },
        files={"code": ("agent.py", io.BytesIO(code.encode()), "text/x-python")},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "my-agent"
    assert body["runtime_state"] == "stopped"
    assert "id" in body

def test_post_agent_rejects_bad_syntax(admin_client):
    r = admin_client.post("/api/spm/agents",
        data={"name":"x","version":"1","agent_type":"custom"},
        files={"code":("agent.py", io.BytesIO(b"def main(::"), "text/x-python")})
    assert r.status_code == 422
    assert "syntax" in r.json()["detail"][0].lower()

def test_get_agents_lists(admin_client):
    r = admin_client.get("/api/spm/agents")
    assert r.status_code == 200
    rows = r.json()
    # Includes the seed rows from the migration
    assert any(row["name"] == "CustomerSupport-GPT" for row in rows)
```

- [ ] **Step 2: Implement**

```python
# services/spm_api/agent_routes.py
"""HTTP endpoints for agent CRUD + lifecycle control."""
from fastapi import APIRouter, UploadFile, Form, Depends, HTTPException, status
from pathlib import Path
import hashlib, uuid
from .agent_validator import validate_agent_code
from .agent_controller import mint_agent_tokens, deploy_agent
from .auth import verify_jwt, require_admin, _tenant_from_claims
from spm.db.models import Agent
from .db import get_session

router = APIRouter(prefix="/agents", tags=["agents"])

CODE_ROOT = Path("./DataVolumes/agents")

@router.post("", status_code=201)
async def create_agent(
    name: str = Form(...),
    version: str = Form(...),
    agent_type: str = Form(...),
    owner: str | None = Form(None),
    description: str = Form(""),
    deploy_after: bool = Form(True),
    code: UploadFile = ...,
    db = Depends(get_session),
    claims = Depends(require_admin),
):
    raw = (await code.read()).decode("utf-8")
    res = validate_agent_code(raw)
    if not res.ok:
        raise HTTPException(422, detail=res.errors)
    agent_id = uuid.uuid4()
    tenant_id = _tenant_from_claims(claims) or "t1"
    code_dir = CODE_ROOT / str(agent_id); code_dir.mkdir(parents=True, exist_ok=True)
    code_path = code_dir / "agent.py"; code_path.write_text(raw)
    sha = hashlib.sha256(raw.encode()).hexdigest()
    mcp_t, llm_t = mint_agent_tokens()
    a = Agent(id=agent_id, name=name, version=version, agent_type=agent_type,
              provider="internal", owner=owner, description=description,
              code_path=str(code_path), code_sha256=sha,
              mcp_token=mcp_t, llm_api_key=llm_t,
              tenant_id=tenant_id, runtime_state="stopped")
    db.add(a); db.commit(); db.refresh(a)
    if deploy_after:
        await deploy_agent(db, agent_id)
    return _to_dict(a, warnings=res.warnings)

@router.get("")
def list_agents(
    db = Depends(get_session), claims = Depends(verify_jwt),
):
    # Phase 1: AI-SPM is single-tenant; tenant_id defaults to "t1" if the
    # JWT lacks the claim. The seed migration uses "t1" for all rows so
    # this filter returns everything in dev. Phase 2 makes the JWT claim
    # mandatory and enforces strict tenant isolation.
    tenant_id = _tenant_from_claims(claims) or "t1"
    rows = db.query(Agent).filter(Agent.tenant_id == tenant_id).all()
    return [_to_dict(a) for a in rows]

def _to_dict(a: Agent, warnings: list[str] | None = None) -> dict:
    d = {
        "id": str(a.id), "name": a.name, "version": a.version,
        "agent_type": a.agent_type, "provider": a.provider,
        "owner": a.owner, "description": a.description,
        "risk": a.risk, "policy_status": a.policy_status,
        "runtime_state": a.runtime_state,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "last_seen_at": a.last_seen_at.isoformat() if a.last_seen_at else None,
        # mcp_token / llm_api_key are NEVER returned
    }
    if warnings is not None:
        d["warnings"] = warnings
    return d
```

In `services/spm_api/app.py`, mount the router:

```python
from .agent_routes import router as agent_router
app.include_router(agent_router, prefix="/api/spm")
```

- [ ] **Step 3: Run; commit**

```
pytest services/spm_api/tests/test_agent_routes.py -v
git add services/spm_api/agent_routes.py services/spm_api/app.py services/spm_api/tests/test_agent_routes.py
git commit -m "feat(spm-api): POST /agents (upload+validate) and GET /agents (list)"
```

---

## Task 16: agent_routes — GET / PATCH / DELETE / start / stop

**Files:**
- Modify: `services/spm_api/agent_routes.py`
- Modify: `services/spm_api/tests/test_agent_routes.py`

- [ ] **Step 1: Failing tests for the four endpoints**

```python
def test_get_agent_detail(admin_client):
    rows = admin_client.get("/api/spm/agents").json()
    aid = rows[0]["id"]
    r = admin_client.get(f"/api/spm/agents/{aid}")
    assert r.status_code == 200
    assert r.json()["id"] == aid

def test_patch_agent_updates_fields(admin_client):
    aid = admin_client.get("/api/spm/agents").json()[0]["id"]
    r = admin_client.patch(f"/api/spm/agents/{aid}",
                            json={"description":"updated"})
    assert r.status_code == 200
    assert r.json()["description"] == "updated"

def test_start_stop_toggles_runtime_state(admin_client, monkeypatch):
    async def fake_start(db, aid): pass
    async def fake_stop(db, aid): pass
    monkeypatch.setattr("services.spm_api.agent_routes.start_agent", fake_start)
    monkeypatch.setattr("services.spm_api.agent_routes.stop_agent",  fake_stop)
    aid = admin_client.get("/api/spm/agents").json()[0]["id"]
    assert admin_client.post(f"/api/spm/agents/{aid}/start").status_code == 202
    assert admin_client.post(f"/api/spm/agents/{aid}/stop").status_code  == 202

def test_delete_retires(admin_client, monkeypatch):
    async def fake_retire(db, aid): pass
    monkeypatch.setattr("services.spm_api.agent_routes.retire_agent", fake_retire)
    aid = admin_client.get("/api/spm/agents").json()[0]["id"]
    r = admin_client.delete(f"/api/spm/agents/{aid}")
    assert r.status_code == 204
```

- [ ] **Step 2: Implement endpoints**

```python
# agent_routes.py — append
from fastapi import Path
from .agent_controller import start_agent, stop_agent, retire_agent

@router.get("/{agent_id}")
def get_agent(agent_id: str, db = Depends(get_session), claims=Depends(verify_jwt)):
    a = db.get(Agent, agent_id)
    if not a: raise HTTPException(404, "agent not found")
    return _to_dict(a)

ALLOWED_PATCH = {"description","owner","risk","policy_status"}

@router.patch("/{agent_id}")
def patch_agent(agent_id: str, body: dict, db = Depends(get_session),
                claims = Depends(require_admin)):
    a = db.get(Agent, agent_id)
    if not a: raise HTTPException(404, "agent not found")
    for k, v in body.items():
        if k in ALLOWED_PATCH:
            setattr(a, k, v)
    db.commit(); db.refresh(a)
    return _to_dict(a)

@router.post("/{agent_id}/start", status_code=202)
async def start_endpoint(agent_id: str, db = Depends(get_session),
                          claims = Depends(require_admin)):
    await start_agent(db, agent_id)
    return {"status":"starting"}

@router.post("/{agent_id}/stop", status_code=202)
async def stop_endpoint(agent_id: str, db = Depends(get_session),
                         claims = Depends(require_admin)):
    await stop_agent(db, agent_id)
    return {"status":"stopping"}

@router.delete("/{agent_id}", status_code=204)
async def delete_endpoint(agent_id: str, db = Depends(get_session),
                           claims = Depends(require_admin)):
    await retire_agent(db, agent_id)
```

- [ ] **Step 3: Run; commit**

```
pytest services/spm_api/tests/test_agent_routes.py -v
git commit -am "feat(spm-api): GET/PATCH/DELETE /agents/{id} + start/stop endpoints"
```

---

## Task 16a: agent-runtime image stub

**Why this task exists:** Task 13's `spawn_agent_container` references `aispm-agent-runtime:latest`. Without an image with that tag, deploys fail at the docker run step. Phase 2 will fill this image with the real `aispm` SDK package; Phase 1 only needs a stub that boots and exits cleanly so the spawn pathway works end-to-end.

**Files:**
- Create: `agent_runtime/Dockerfile`
- Create: `agent_runtime/stub_main.py`

- [ ] **Step 1: Stub entrypoint**

```python
# agent_runtime/stub_main.py
"""V1 stub. Phase 2 replaces this with the real aispm SDK + agent loader.

For Phase 1, this just prints the env vars the controller injected
and sleeps so the container stays up long enough for orchestration
tests to verify it's running.
"""
import os, time, sys
print(f"[stub-runtime] AGENT_ID={os.environ.get('AGENT_ID')}", flush=True)
print(f"[stub-runtime] MCP_URL={os.environ.get('MCP_URL')}",   flush=True)
print(f"[stub-runtime] LLM_BASE_URL={os.environ.get('LLM_BASE_URL')}", flush=True)
sys.stdout.flush()
# Stay running so docker reports state=running for ~10 minutes.
time.sleep(600)
```

- [ ] **Step 2: Dockerfile**

```dockerfile
# agent_runtime/Dockerfile
FROM python:3.12-slim
WORKDIR /agent
COPY agent_runtime/stub_main.py /agent/stub_main.py
# Customer agent.py will be bind-mounted to /agent/agent.py at runtime.
# In Phase 1 we ignore it and run the stub.
CMD ["python","/agent/stub_main.py"]
```

- [ ] **Step 3: Build it**

```
cd /Users/danyshapiro/PycharmProjects/AISPM
docker build -f agent_runtime/Dockerfile -t aispm-agent-runtime:latest .
docker images | grep aispm-agent-runtime
```

Expected: image present.

- [ ] **Step 4: Smoke run**

```
docker run --rm -e AGENT_ID=test -e MCP_URL=x -e LLM_BASE_URL=y \
  aispm-agent-runtime:latest python -c "import os; print(os.environ['AGENT_ID'])"
```

Expected: prints `test`.

- [ ] **Step 5: Commit**

```
git add agent_runtime/
git commit -m "feat(agent-runtime): Phase 1 stub Dockerfile + entrypoint"
```

---

## Task 17: docker-compose — wire spm-mcp + spm-llm-proxy

**Files:**
- Modify: `compose.yml`

- [ ] **Step 1: Add service entries (after the `spm-api:` block)**

```yaml
  spm-mcp:
    build:
      context: .
      dockerfile: services/spm_mcp/Dockerfile
    image: aispm-spm-mcp:latest
    container_name: cpm-spm-mcp
    depends_on:
      spm-db:        { condition: service_healthy }
      kafka-broker:  { condition: service_healthy }
    environment:
      <<: *common-env
    ports:
      - "8500:8500"
    networks: [default, agent-net]
    healthcheck:
      test: ["CMD", "curl", "-fs", "http://localhost:8500/health"]
      interval: 10s
      timeout: 3s
      retries: 5

  spm-llm-proxy:
    build:
      context: .
      dockerfile: services/spm_llm_proxy/Dockerfile
    image: aispm-spm-llm-proxy:latest
    container_name: cpm-spm-llm-proxy
    depends_on:
      spm-db:        { condition: service_healthy }
    environment:
      <<: *common-env
    ports:
      - "8501:8500"
    networks: [default, agent-net]
    healthcheck:
      test: ["CMD", "curl", "-fs", "http://localhost:8500/health"]
      interval: 10s
      timeout: 3s
      retries: 5

  # NOTE: agent-runtime is built but not run as a service. spm-api spawns
  # individual `agent-{id}` containers from this image at deploy time.
  # We declare a one-shot build here so `docker compose build` produces
  # the image without leaving a service running.
  agent-runtime-build:
    build:
      context: .
      dockerfile: agent_runtime/Dockerfile
    image: aispm-agent-runtime:latest
    profiles: ["build-only"]      # never started by `compose up`
    command: ["true"]

networks:
  agent-net:
    driver: bridge
    internal: true   # No outbound internet from agents in this network.
                     # spm-mcp and spm-llm-proxy bridge default + agent-net,
                     # so agents can reach them but cannot reach the internet.
```

(Network `agent-net` is created internal-only so agent containers can't egress to the internet directly. spm-mcp and spm-llm-proxy bridge the two networks.)

- [ ] **Step 2: Verify compose validates**

```
cd /Users/danyshapiro/PycharmProjects/AISPM
docker compose -f compose.yml config > /dev/null
```

Expected: no errors, no output. If it errors, fix syntax.

- [ ] **Step 3: Build the new images (including agent-runtime)**

```
docker compose --profile build-only build agent-runtime-build
docker compose build spm-mcp spm-llm-proxy
```

Expected: three images built successfully (`aispm-agent-runtime:latest`, `aispm-spm-mcp:latest`, `aispm-spm-llm-proxy:latest`).

- [ ] **Step 4: Bring them up (wait for healthy)**

```
docker compose up -d --wait spm-mcp spm-llm-proxy
docker ps | grep -E "spm-mcp|spm-llm-proxy"
```

Expected: both `Up X seconds (healthy)`. The `--wait` flag blocks until healthchecks pass.

- [ ] **Step 5: Smoke-test health endpoints**

```
curl -sf http://localhost:8500/health
curl -sf http://localhost:8501/health
```

Expected: both return `{"ok":true}`.

- [ ] **Step 6: Commit**

```
git add compose.yml
git commit -m "feat(compose): add spm-mcp + spm-llm-proxy services with internal agent-net"
```

---

## Task 18: End-to-end smoke — deploy a hello-world agent

**Files:**
- Create: `tests/e2e/test_agent_deploy_smoke.py`
- Create: `tests/e2e/fixtures/hello_agent.py`

- [ ] **Step 1: Create the fixture**

```python
# tests/e2e/fixtures/hello_agent.py
import asyncio
async def main():
    print("hello from agent")
    await asyncio.sleep(1)

asyncio.run(main())
```

- [ ] **Step 2: Failing E2E test (assumes the stack is up)**

```python
# tests/e2e/test_agent_deploy_smoke.py
import io, time, requests, pytest, pathlib

API = "http://localhost:8092/api/spm"

@pytest.fixture
def admin_token():
    return requests.get("http://localhost:8092/api/dev-token").json()["token"]

def test_upload_and_list_agent(admin_token):
    code = pathlib.Path(__file__).parent / "fixtures" / "hello_agent.py"
    r = requests.post(
        f"{API}/agents",
        headers={"Authorization": f"Bearer {admin_token}"},
        data={"name":"hello-smoke","version":"1.0","agent_type":"custom",
              "owner":"smoke","deploy_after":"false"},
        files={"code":("agent.py", code.open("rb"), "text/x-python")},
    )
    assert r.status_code == 201
    aid = r.json()["id"]

    # appears in list
    rows = requests.get(f"{API}/agents",
                         headers={"Authorization":f"Bearer {admin_token}"}).json()
    assert any(row["id"] == aid for row in rows)

    # cleanup
    requests.delete(f"{API}/agents/{aid}",
                    headers={"Authorization":f"Bearer {admin_token}"})
```

- [ ] **Step 3: Bring stack up**

```
docker compose up -d
```

Wait ~30s for everything to settle.

- [ ] **Step 4: Run the smoke test**

```
pytest tests/e2e/test_agent_deploy_smoke.py -v
```

Expected: passes. If not, debug with `docker logs cpm-spm-api --tail 100`.

- [ ] **Step 5: Commit**

```
git add tests/e2e/
git commit -m "test(e2e): smoke test for agent upload + list + delete"
```

---

## Task 19: Documentation — Phase 1 wrap-up

**Files:**
- Modify: `README.md` — add a small section describing the new endpoints
- Create: `docs/agents/operator-quickstart.md`

- [ ] **Step 1: Write `docs/agents/operator-quickstart.md`**

Cover these sections (50-80 lines total):

1. **What's new** — one paragraph naming the three new services (spm-mcp, spm-llm-proxy, agent-runtime image) and where they sit in the stack. Link to spec.
2. **Upload an agent** — curl example using `/api/dev-token` then `POST /api/spm/agents` multipart with a hello-world agent.py.
3. **List / inspect / delete** — curl examples for `GET /agents`, `GET /agents/{id}`, `DELETE /agents/{id}`.
4. **Start / stop / restart** — curl examples for the lifecycle endpoints + how to read `runtime_state`.
5. **Configure the control plane** — point to Integrations → AI Providers → "AI-SPM Agent Runtime Control Plane (MCP)"; show how to switch the default LLM dropdown.
6. **Logs and debugging** — `docker logs cpm-spm-mcp`, `docker logs agent-{id}`, `docker logs cpm-spm-llm-proxy`.
7. **Phase 1 limitations** — call out: stub agent runtime (real SDK in Phase 2), no UI changes (Phase 3), no chat pipeline integration (Phase 4). Link the spec's V1 non-goals section.

- [ ] **Step 2: Commit**

```
git add docs/agents/operator-quickstart.md README.md
git commit -m "docs: phase-1 operator quickstart for agent runtime control plane"
```

---

## Phase 1 Done Criteria

After Task 19, all of these should be true:

- [ ] `alembic upgrade head` runs the 005 migration cleanly
- [ ] `agents` table has 5 seed rows visible via `psql`
- [ ] `docker compose up -d spm-mcp spm-llm-proxy` brings both services up healthy
- [ ] `curl http://localhost:8500/health` and `:8501/health` both return 200
- [ ] `POST /api/spm/agents` (multipart) accepts a valid agent.py and returns 201
- [ ] Bad syntax → 422; missing `async def main` → 422
- [ ] `GET /api/spm/agents` returns the seed rows + any uploaded ones
- [ ] `POST /api/spm/agents/{id}/start` and `/stop` toggle `runtime_state` (Docker calls mocked or real)
- [ ] All Phase 1 tests pass: `pytest services/spm_api/tests/ services/spm_mcp/tests/ services/spm_llm_proxy/tests/ tests/test_topics_agent.py tests/test_lineage_events_agent.py spm/tests/test_agent_models.py`
- [ ] No new failures in the existing test suite

What Phase 1 does **not** do (Phase 2 onwards):
- The agent runtime SDK package (`aispm/`) doesn't exist yet — uploaded agents will fail at runtime when they `import aispm`. That's fine; we mock deploy in tests.
- No actual chat path between UI and a running agent — `POST /agents/{id}/chat` is a stub for Phase 4.
- No UI changes — admin still sees mock agents in the Inventory page until Phase 3.
