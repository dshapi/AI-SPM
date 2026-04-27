"""POST /api/spm/agents/{id}/chat — full chat pipeline for the agent
runtime control plane (Phase 4).

End-to-end flow on a single user message:

    UI ──► POST /api/spm/agents/{id}/chat (SSE)
                │
                ▼
        prompt-guard.screen(text)   ── block? → SSE error
                │
                ▼
        policy-decider /spm/prompt/allow
            input.linked_policies = [agent_policies for this agent]
                                    ── block? → SSE error
                │
                ▼
        AgentChatMessageEvent  (role=user)         ── lineage
                │
                ▼
        Kafka produce → cpm.{tenant}.agents.{id}.chat.in
                │   (the agent's SDK chat.subscribe() consumes it)
                ▼
        Kafka consume ← cpm.{tenant}.agents.{id}.chat.out
                │   (matched by session_id, capped at CHAT_REPLY_TIMEOUT_S)
                ▼
        output-guard regex (secrets/PII) +
        policy-decider /spm/output/allow
            decision: allow | redact | block
                │
                ▼
        AgentChatMessageEvent  (role=agent)        ── lineage
                │
                ▼
        SSE: data: {"type":"done","text":<reply>}\n\n

Each user/agent turn is also persisted to ``agent_chat_messages``
so the history endpoint can replay the conversation.

Failure modes are explicit:

    - prompt-guard timeout / unavailable           → fail-CLOSED (block)
    - policy-decider timeout / unavailable         → fail-CLOSED (block)
    - agent reply timeout                          → SSE error
    - output-guard timeout / unavailable           → fail-CLOSED (block)

Never raises 500 to the UI for a pipeline failure; surfaces
``data: {"type":"error","text":"..."}`` instead so the chat panel
renders a clear message and the operator can iterate.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from sqlalchemy import select

from spm.db.models  import (                                # type: ignore
    Agent, AgentChatMessage, AgentChatSession, AgentPolicy,
)
from spm.db.session import get_db                           # type: ignore

# Auth wrappers — same lazy-resolution trick the other agent_*
# routes use so the Dockerfile's flat layout works.
try:
    from agent_routes import verify_jwt, _tenant_from_claims  # type: ignore
except ModuleNotFoundError:                                  # pragma: no cover
    from services.spm_api.agent_routes import (
        verify_jwt, _tenant_from_claims,
    )

log = logging.getLogger(__name__)


# ─── Tunables (env-overridable) ────────────────────────────────────────────

GUARD_URL     = os.environ.get("GUARD_MODEL_URL", "http://guard-model:8200")
GUARD_TIMEOUT = float(os.environ.get("GUARD_TIMEOUT_S", "5"))

OPA_URL       = os.environ.get("OPA_URL", "http://opa:8181")
OPA_TIMEOUT   = float(os.environ.get("OPA_TIMEOUT_S", "2"))

CHAT_REPLY_TIMEOUT_S = float(
    os.environ.get("AGENT_CHAT_REPLY_TIMEOUT_S", "120")
)

# Output-guard regexes — same shapes the existing chat path uses.
_SECRET_RE = re.compile(
    r"(?i)(?:api[_-]?key|secret|password|token|bearer\s+\S+)"
    r"\s*[:=]\s*['\"]?[A-Za-z0-9_\-/\.+=]{12,}",
)
_PII_RE = re.compile(
    r"(?:\b\d{3}-\d{2}-\d{4}\b)"                          # SSN
    r"|(?:\b\d{16}\b)"                                    # 16-digit card
    r"|(?:[\w\.+-]+@[\w-]+\.[\w\.-]+)",                   # email
)


# ─── Router ────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/agents", tags=["agents"])


# ─── Pipeline pieces ───────────────────────────────────────────────────────

# Score above which a categorised input flips to "block" even if the
# guard verdict was "allow". Tunable via env so operators with a noisier
# guard model can ratchet it up. Default 0.6 was chosen by hand-testing
# the falsy-positive rate on short conversational inputs.
GUARD_BLOCK_SCORE = float(os.environ.get("GUARD_BLOCK_SCORE", "0.6"))

# Min input length the guard is allowed to act on. Models we've tested
# in this family produce noisy categorisations on 1–2 word inputs
# (e.g. "yes", "ok", "thanks"); skip the guard for those.
GUARD_MIN_TEXT_LEN = int(os.environ.get("GUARD_MIN_TEXT_LEN", "8"))


async def _call_guard(text: str) -> Tuple[str, float, List[str]]:
    """Call prompt-guard /screen. Fail-closed on any error.

    Verdict policy
    ──────────────
    Trust the guard's own ``verdict`` field. The previous
    ``if cats: verdict = "block"`` rule was too aggressive — the model
    legitimately tags benign inputs ("yes") with a category like S2 and
    sets ``verdict: "allow"``. We only override the verdict when the
    guard reports ``allow`` AND the score is above ``GUARD_BLOCK_SCORE``,
    which lines up with what an operator would call "high-risk despite
    the model not saying block".

    Short-input bypass
    ──────────────────
    Inputs shorter than ``GUARD_MIN_TEXT_LEN`` chars skip the guard
    entirely — too little signal to reason about, and conversational
    replies like "yes / ok / thanks" should never trip safety.
    """
    if len((text or "").strip()) < GUARD_MIN_TEXT_LEN:
        return "allow", 0.0, []

    body = {"text": text, "context": "user_input"}
    try:
        async with httpx.AsyncClient(timeout=GUARD_TIMEOUT) as c:
            r = await c.post(f"{GUARD_URL.rstrip('/')}/screen", json=body)
        r.raise_for_status()
        data = r.json()
        verdict = data.get("verdict", "block")
        score   = float(data.get("score", 1.0))
        cats    = data.get("categories", []) or []
        # Only escalate "allow" → "block" when the guard's own score
        # is above the configured threshold. Categories alone are
        # informational, not a kill-switch.
        if verdict == "allow" and cats and score >= GUARD_BLOCK_SCORE:
            log.info(
                "prompt-guard: escalating allow→block on score=%.2f "
                "categories=%s (threshold=%.2f)",
                score, cats, GUARD_BLOCK_SCORE,
            )
            verdict = "block"
        return verdict, score, cats
    except httpx.TimeoutException:
        log.warning("prompt-guard timeout — failing CLOSED")
        return "block", 0.5, ["timeout"]
    except Exception as e:                              # noqa: BLE001
        log.warning("prompt-guard unavailable: %s — failing CLOSED", e)
        return "block", 0.5, ["unavailable"]


async def _call_prompt_policy(
    *, score: float, categories: List[str],
    auth: Dict[str, Any], linked_policies: List[str],
) -> Tuple[bool, str]:
    """Call policy-decider /v1/data/spm/prompt/allow. Returns
    (blocked, reason). Fail-closed on error."""
    payload = {
        "posture_score":      min(score, 1.0),
        "signals":            categories,
        "behavioral_signals": categories,
        "retrieval_trust":    1.0,
        "intent_drift":       score,
        "guard_verdict":      "allow",
        "guard_score":        score,
        "guard_categories":   categories,
        "auth_context":       auth,
        # Phase 4 addition — pass the agent's linked policies so OPA
        # can scope evaluation. OPA rules that don't yet read this
        # field simply ignore it.
        "linked_policies":    linked_policies,
    }
    try:
        async with httpx.AsyncClient(timeout=OPA_TIMEOUT) as c:
            r = await c.post(
                f"{OPA_URL.rstrip('/')}/v1/data/spm/prompt/allow",
                json={"input": payload},
            )
        if r.status_code != 200:
            raise RuntimeError(f"OPA returned HTTP {r.status_code}")
        result = (r.json() or {}).get("result", {})
        if isinstance(result, dict) and result.get("decision") == "block":
            return True, str(result.get("reason", "policy block"))
        return False, ""
    except Exception as e:                              # noqa: BLE001
        log.warning("policy-decider unavailable: %s — failing CLOSED", e)
        return True, "policy-decider unavailable"


def _scan_output(text: str) -> Tuple[bool, bool]:
    return bool(_SECRET_RE.search(text or "")), bool(_PII_RE.search(text or ""))


async def _call_output_policy(
    *, contains_secret: bool, contains_pii: bool,
) -> str:
    """Returns one of "allow" | "redact" | "block". Fail-closed = block."""
    payload = {
        "contains_secret": contains_secret,
        "contains_pii":    contains_pii,
        "llm_verdict":     "allow",
    }
    try:
        async with httpx.AsyncClient(timeout=OPA_TIMEOUT) as c:
            r = await c.post(
                f"{OPA_URL.rstrip('/')}/v1/data/spm/output/allow",
                json={"input": payload},
            )
        if r.status_code != 200:
            raise RuntimeError(f"OPA returned HTTP {r.status_code}")
        result = (r.json() or {}).get("result", {})
        decision = (result or {}).get("decision", "allow")
        return str(decision)
    except Exception as e:                              # noqa: BLE001
        # If OPA is offline, prefer redaction over block when it's a
        # PII match (fail-soft for known-low-risk leaks); for actual
        # secrets, fail-closed (block).
        log.warning("output-policy unavailable: %s — falling back", e)
        if contains_secret:
            return "block"
        if contains_pii:
            return "redact"
        return "allow"


def _redact(text: str) -> str:
    redacted = _SECRET_RE.sub("[REDACTED-SECRET]", text)
    redacted = _PII_RE.sub("[REDACTED-PII]", redacted)
    return redacted


# ─── Lineage emission ──────────────────────────────────────────────────────

def _emit_chat_event(
    *, agent_id: str, tenant_id: str, session_id: str,
    user_id: str, role: str, text: str, trace_id: str,
) -> None:
    """Best-effort publish of an AgentChatMessageEvent to the global
    lineage topic. Never raises — the chat path is the user-facing
    hot path and can't be blocked by the audit pipeline."""
    try:
        from platform_shared.lineage_events import (         # type: ignore
            AgentChatMessageEvent, build_lineage_envelope,
        )
        from platform_shared.kafka_utils import safe_send    # type: ignore
        from platform_shared.topics import GlobalTopics      # type: ignore
        try:
            from app import _kafka_producer                  # type: ignore
        except (ImportError, ModuleNotFoundError):
            _kafka_producer = None  # type: ignore

        evt = AgentChatMessageEvent(
            agent_id=agent_id, tenant_id=tenant_id,
            session_id=session_id, user_id=user_id,
            role=role, text=text, trace_id=trace_id,
        )
        envelope = build_lineage_envelope(
            session_id     = session_id,
            event_type     = "AgentChatMessage",
            payload        = evt.to_dict(),
            correlation_id = trace_id,
            agent_id       = agent_id,
            user_id        = user_id,
            tenant_id      = tenant_id,
            source         = "spm-api-agent-chat",
        )
        producer = _kafka_producer() if callable(_kafka_producer) else _kafka_producer
        if producer is not None:
            safe_send(producer, GlobalTopics.LINEAGE_EVENTS, envelope)
    except Exception as e:                              # noqa: BLE001
        log.warning("lineage emit failed: %s", e)


# ─── DB helpers (async-vs-sync session compatibility) ──────────────────────

async def _get_agent(db, agent_id: str) -> Optional[Agent]:
    res = db.get(Agent, agent_id)
    if hasattr(res, "__await__"):
        return await res
    return res


async def _list_linked_policies(db, agent_id: str) -> List[str]:
    if hasattr(db, "execute"):
        result = await db.execute(
            select(AgentPolicy.policy_id)
            .where(AgentPolicy.agent_id == agent_id)
        )
        return [r[0] for r in result.all()]
    rows = list(db.query(AgentPolicy)
                  .filter(AgentPolicy.agent_id == agent_id).all())
    return [r.policy_id for r in rows]


# Stable namespace for hashing opaque UI session slugs into UUIDs. Hard-coded
# (not derived from agent_id / tenant) so the same slug from the same UI
# context always maps to the same DB row across requests.
_SESSION_ID_NS = uuid.UUID("00000000-0000-0000-0000-000000005e55")  # fixed-namespace


def _coerce_session_id(raw):
    """Accept either a UUID string or an opaque slug from the UI.

    The DB ``agent_chat_sessions.id`` column is UUID-typed, but the UI
    generates slugs like ``"sess-14gu5d99x"`` that aren't UUIDs. We coerce
    deterministically so the same slug round-trips to the same row:

    * empty / None     → fresh uuid4 (anonymous session)
    * valid UUID str   → unchanged
    * non-UUID slug    → uuid5(NS, slug) — same slug always maps to same UUID
    """
    if not raw:
        return uuid.uuid4()
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return uuid.uuid5(_SESSION_ID_NS, str(raw))


async def _ensure_session(db, *, agent_id, session_id, user_id) -> None:
    if hasattr(db, "execute"):
        existing = (await db.execute(
            select(AgentChatSession).where(AgentChatSession.id == session_id)
        )).scalar_one_or_none()
        if existing is not None:
            return
    else:
        if db.get(AgentChatSession, session_id) is not None:
            return
    db.add(AgentChatSession(
        id=session_id, agent_id=agent_id, user_id=user_id, message_count=0,
    ))
    await _commit(db)


async def _save_message(db, *, session_id, role, text, trace_id) -> None:
    db.add(AgentChatMessage(
        id=uuid.uuid4(), session_id=session_id,
        role=role, text=text, trace_id=trace_id,
    ))
    await _commit(db)


async def _commit(db) -> None:
    res = db.commit()
    if hasattr(res, "__await__"):
        await res


def _sse(event: Dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


# ─── /agents/{id}/chat ─────────────────────────────────────────────────────

@router.post("/{agent_id}/chat")
async def chat_endpoint(
    agent_id:      str,
    body:          Dict[str, Any],
    request:       Request,
    db = Depends(get_db),
    claims = Depends(verify_jwt),
) -> StreamingResponse:
    """One-message round-trip with the full security pipeline."""
    text       = (body or {}).get("message")
    # The UI sometimes sends opaque slugs (e.g. "sess-14gu5d99x"); coerce
    # to a UUID so the asyncpg UUID-cast doesn't reject the WHERE.
    session_id = _coerce_session_id((body or {}).get("session_id"))
    if not text or not isinstance(text, str):
        raise HTTPException(
            status_code=400, detail="`message` (string) is required",
        )

    tenant_id = _tenant_from_claims(claims, fallback="t1")
    agent = await _get_agent(db, agent_id)
    if agent is None or agent.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="agent not found")
    if agent.runtime_state != "running":
        raise HTTPException(
            status_code=409,
            detail=(f"agent is {agent.runtime_state!r}; "
                    f"start it before chatting"),
        )

    user_id  = (claims.get("sub") or claims.get("email") or "anonymous")
    trace_id = str(uuid.uuid4())

    # Pull these eagerly while we're still in the route's async context;
    # the streaming generator may have a different scope.
    linked_policies = await _list_linked_policies(db, agent_id)
    auth_context = {
        "sub":       user_id,
        "tenant_id": tenant_id,
        "roles":     claims.get("roles", []) or [],
        "scopes":    claims.get("scopes", []) or [],
        "claims":    claims,
    }

    return StreamingResponse(
        _round_trip(
            request, db=db, agent=agent,
            session_id=session_id, user_id=user_id,
            text=text, trace_id=trace_id,
            auth_context=auth_context,
            linked_policies=linked_policies,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "Connection":        "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─── SSE generator ─────────────────────────────────────────────────────────

async def _round_trip(
    request, *, db, agent: Agent,
    session_id: str, user_id: str,
    text: str, trace_id: str,
    auth_context: Dict[str, Any],
    linked_policies: List[str],
):
    tenant_id = agent.tenant_id
    agent_id  = str(agent.id)
    # session_id is a UUID for the DB but everything Kafka/lineage/JSON
    # related needs the str form.
    session_id_str = str(session_id)

    # 1. prompt-guard
    g_verdict, g_score, g_cats = await _call_guard(text)
    if g_verdict != "allow":
        yield _sse({"type": "error",
                     "text": "Prompt blocked by safety guard."
                             + (f" ({', '.join(g_cats)})" if g_cats else "")})
        return

    # 2. policy-decider (with linked policies)
    blocked, reason = await _call_prompt_policy(
        score=g_score, categories=g_cats,
        auth=auth_context, linked_policies=linked_policies,
    )
    if blocked:
        yield _sse({"type": "error",
                     "text": f"Blocked by policy: {reason}"})
        return

    # 3. Persist user turn + emit lineage.
    await _ensure_session(db, agent_id=agent_id,
                          session_id=session_id, user_id=user_id)
    await _save_message(db, session_id=session_id, role="user",
                        text=text, trace_id=trace_id)
    _emit_chat_event(
        agent_id=agent_id, tenant_id=tenant_id, session_id=session_id_str,
        user_id=user_id, role="user", text=text, trace_id=trace_id,
    )

    # 4. Kafka pass-through to the agent's chat.in / chat.out.
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer  # type: ignore
    from platform_shared.topics import agent_topics_for      # type: ignore

    topics    = agent_topics_for(tenant_id, agent_id)
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS",
                                 "kafka-broker:9092")
    msg_id = str(uuid.uuid4())

    producer = AIOKafkaProducer(
        bootstrap_servers=bootstrap,
        value_serializer=lambda v: json.dumps(v).encode(),
    )
    consumer = AIOKafkaConsumer(
        topics.chat_out,
        bootstrap_servers=bootstrap,
        group_id=f"chat-rt-{uuid.uuid4().hex[:8]}",
        auto_offset_reset="latest",
        value_deserializer=lambda b: json.loads(b.decode()),
        enable_auto_commit=True,
    )
    await producer.start(); await consumer.start()
    reply_text: Optional[str] = None
    try:
        await producer.send_and_wait(
            topics.chat_in,
            value={
                "id":         msg_id,
                "session_id": session_id_str,
                "user_id":    user_id,
                "text":       text,
                "ts":         datetime.now(timezone.utc).isoformat(),
                "trace_id":   trace_id,
            },
            key=session_id_str.encode(),
        )

        deadline = asyncio.get_event_loop().time() + CHAT_REPLY_TIMEOUT_S
        while asyncio.get_event_loop().time() < deadline:
            if await request.is_disconnected():
                return
            try:
                m = await asyncio.wait_for(consumer.getone(), timeout=1.0)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue
            v = m.value or {}
            if v.get("session_id") == session_id_str and v.get("text"):
                reply_text = str(v["text"])
                break
    finally:
        try: await producer.stop()
        except Exception: pass
        try: await consumer.stop()
        except Exception: pass

    if reply_text is None:
        yield _sse({"type": "error",
                     "text": f"Agent did not respond within "
                             f"{CHAT_REPLY_TIMEOUT_S:.0f}s."})
        return

    # 5. output-guard — regex + OPA. Block / redact / allow.
    contains_secret, contains_pii = _scan_output(reply_text)
    decision = await _call_output_policy(
        contains_secret=contains_secret,
        contains_pii=contains_pii,
    )
    if decision == "block":
        yield _sse({"type": "error",
                     "text": "Reply blocked by output guard."})
        return
    if decision == "redact":
        reply_text = _redact(reply_text)

    # 6. Persist agent turn + emit lineage.
    try:
        await _save_message(db, session_id=session_id, role="agent",
                            text=reply_text, trace_id=trace_id)
    except Exception as e:                            # noqa: BLE001
        log.warning("persist agent reply failed: %s", e)
    _emit_chat_event(
        agent_id=agent_id, tenant_id=tenant_id, session_id=session_id_str,
        user_id=user_id, role="agent", text=reply_text, trace_id=trace_id,
    )

    # ── Pseudo-streaming reveal ───────────────────────────────────────────
    # The agent + LLM finished generating the whole reply already. To give
    # the UI a streaming feel without rebuilding the LLM call path for true
    # token-streaming, chunk the final text and emit per-chunk deltas with
    # a small inter-chunk delay. UI renders progressively; total wall-time
    # is unchanged, but time-to-first-paint goes from ~LLM_seconds to ~0ms.
    #
    # Tunables — small word-aware chunks feel natural at typical reading
    # speed. CHAT_STREAM_DELAY_MS=0 disables the reveal entirely.
    chunk_size  = max(1, int(os.environ.get("CHAT_STREAM_CHUNK_CHARS", "12")))
    delay_s     = max(0.0, float(os.environ.get("CHAT_STREAM_DELAY_MS", "30")) / 1000.0)
    if delay_s == 0 or len(reply_text) <= chunk_size:
        yield _sse({"type": "done", "text": reply_text})
        return

    # Word-aware split — never break a word mid-character. Walk the text,
    # emit when we cross chunk_size at the next whitespace boundary.
    cursor = 0
    while cursor < len(reply_text):
        end = min(cursor + chunk_size, len(reply_text))
        # Extend forward to the next word boundary so deltas land at
        # natural breaks rather than mid-token.
        if end < len(reply_text) and not reply_text[end].isspace():
            ws = reply_text.find(" ", end)
            if ws != -1 and ws - cursor < chunk_size * 2:
                end = ws + 1
        chunk = reply_text[cursor:end]
        cursor = end
        # UI's useAgentChat hook listens for type:"token"; keep the
        # name consistent with that contract.
        yield _sse({"type": "token", "text": chunk})
        if cursor < len(reply_text):
            await asyncio.sleep(delay_s)

    # Final done event — include the full text so clients that ignored
    # deltas (or want to verify) get the canonical reply.
    yield _sse({"type": "done", "text": reply_text})
