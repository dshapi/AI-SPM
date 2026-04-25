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
        code_path="./DataVolums/agents/x/agent.py",
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
