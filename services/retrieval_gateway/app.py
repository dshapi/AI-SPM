"""
Retrieval Gateway — enriches raw events with verified context.

In production: replace _fetch_contexts() with calls to your vector store
(pgvector, Qdrant, Weaviate). The ingestion_hash must be stored at index time
and verified here at retrieval time.
"""
from __future__ import annotations
import time
import logging
from platform_shared.base_service import ConsumerService
from platform_shared.models import RawEvent, RetrievedContextItem, RetrievedEvent
from platform_shared.topics import topics_for_tenant
from platform_shared.trust import assess_contexts
from platform_shared.risk import compute_content_hash, _jaccard_similarity
from platform_shared.audit import emit_audit, emit_security_alert
from platform_shared.kafka_utils import safe_send, send_event

log = logging.getLogger("retrieval-gateway")


# ─────────────────────────────────────────────────────────────────────────────
# Demo knowledge base (replace with vector store in production)
# ─────────────────────────────────────────────────────────────────────────────

_KNOWLEDGE_BASE = [
    {
        "source": "calendar_system",
        "owner": "system",
        "classification": "internal",
        "freshness_days": 0,
        "content": "Architecture Review scheduled for 10:00 AM today. Attendees: Engineering team.",
        "tags": ["calendar", "meeting", "schedule", "today"],
    },
    {
        "source": "calendar_system",
        "owner": "system",
        "classification": "internal",
        "freshness_days": 0,
        "content": "Security Sync at 14:00. Weekly security posture review with CISO.",
        "tags": ["calendar", "security", "meeting", "schedule"],
    },
    {
        "source": "company_handbook",
        "owner": "hr",
        "classification": "internal",
        "freshness_days": 30,
        "content": "Employee onboarding process: complete IT setup, security training, and badge request.",
        "tags": ["onboarding", "hr", "process"],
    },
    {
        "source": "public_docs",
        "owner": "marketing",
        "classification": "public",
        "freshness_days": 120,
        "content": "Company overview: Founded in 2020, specialising in AI security infrastructure.",
        "tags": ["company", "overview", "public"],
    },
    {
        "source": "email_inbox",
        "owner": "user",
        "classification": "confidential",
        "freshness_days": 1,
        "content": "Project Nexus update: Q3 milestones achieved. Board presentation next week.",
        "tags": ["email", "project", "update", "confidential"],
    },
]

# Pre-compute ingestion hashes (done at index time in production)
for _item in _KNOWLEDGE_BASE:
    _item["ingestion_hash"] = compute_content_hash(_item["content"])


def _fetch_contexts(prompt: str, max_results: int = 3) -> list[RetrievedContextItem]:
    """
    Retrieve context items relevant to the prompt.
    Uses Jaccard similarity over tags + content for demo.
    In production: vector similarity search.
    """
    prompt_tokens = set(prompt.lower().split())
    scored = []
    for item in _KNOWLEDGE_BASE:
        # Score: tag overlap + content similarity
        tag_overlap = len(prompt_tokens & set(item["tags"])) / max(len(prompt_tokens), 1)
        content_sim = _jaccard_similarity(item["content"], prompt)
        score = round((tag_overlap * 0.6 + content_sim * 0.4), 4)
        scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for rank, (sim, item) in enumerate(scored[:max_results]):
        ctx = RetrievedContextItem(
            source=item["source"],
            owner=item["owner"],
            classification=item["classification"],
            freshness_days=item["freshness_days"],
            content=item["content"],
            ingestion_hash=item["ingestion_hash"],
            semantic_coherence=sim,
            retrieval_rank=rank,
        )
        results.append(ctx)
    return results


class RetrievalGateway(ConsumerService):
    service_name = "retrieval-gateway"

    def __init__(self):
        t = topics_for_tenant("t1")
        super().__init__([t.raw], "cpm-retrieval")

    def handle(self, payload: dict) -> None:
        t0 = time.time()
        event = RawEvent(**payload)
        topics = topics_for_tenant(event.tenant_id)

        # Fetch and assess context
        raw_items = _fetch_contexts(event.prompt)
        assessed_items = assess_contexts(raw_items)

        # Detect tampered documents
        tampered = [i for i in assessed_items if i.ingestion_hash and not i.hash_verified]
        if tampered:
            emit_security_alert(
                event.tenant_id, self.service_name,
                "context_tampering_detected",
                ttp_codes=["AML.T0048"],
                event_id=event.event_id,
                principal=event.user_id,
                session_id=event.session_id,
                details={
                    "tampered_sources": [i.source for i in tampered],
                    "tampered_count": len(tampered),
                },
            )

        retrieved = RetrievedEvent(
            event_id=event.event_id,
            ts=event.ts,
            tenant_id=event.tenant_id,
            user_id=event.user_id,
            session_id=event.session_id,
            prompt=event.prompt,
            auth_context=event.auth_context,
            metadata=event.metadata,
            retrieved_contexts=assessed_items,
            retrieval_latency_ms=int((time.time() - t0) * 1000),
            guard_verdict=event.guard_verdict,
            guard_score=event.guard_score,
            guard_categories=event.guard_categories,
        )

        send_event(
            self.producer, topics.retrieved, retrieved,
            event_type="context.retrieved",
            source_service="retrieval-gateway",
        )

        emit_audit(
            event.tenant_id, self.service_name, "context_retrieved",
            event_id=event.event_id, principal=event.user_id,
            session_id=event.session_id,
            correlation_id=event.event_id,
            details={
                "items_retrieved": len(assessed_items),
                "tampered": len(tampered),
                "avg_trust": round(
                    sum(i.trust_score for i in assessed_items) / max(len(assessed_items), 1), 4
                ),
                "latency_ms": retrieved.retrieval_latency_ms,
            },
        )


if __name__ == "__main__":
    RetrievalGateway().run()
