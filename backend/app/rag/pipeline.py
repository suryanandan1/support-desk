"""The RAG decision pipeline: question in, grounded answer or escalation decision out.

Steps (numbers match the project specification):
  3-5. embed the question, retrieve passages, apply similarity thresholds
  6-7. build the grounded prompt and generate an answer
  8.   attach the cited sources
  9.   check the evidence (before generation) and the citations (after)
  10.  return the answer, or the reason to escalate

Nothing here touches conversations or tickets; chat_service persists the result.
"""

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.ticket import EscalationReason
from app.rag.evaluation import assess_evidence, groundedness, wants_human
from app.rag.generation import AnswerGenerator, get_answer_generator
from app.rag.providers.base import ChatMessage, EmbeddingProvider, ProviderError
from app.rag.retrieval import RetrievalResult, RetrievedChunk, retrieve
from app.rag.text import terms
from app.rag.vector_store import FaissVectorStore, VectorStoreError

logger = logging.getLogger(__name__)

# An answer without any [n] citation is accepted only if its wording is this strongly
# supported by the retrieved passages; otherwise it is treated as ungrounded.
MIN_GROUNDEDNESS_WITHOUT_CITATIONS = 0.6
INFERRED_CITATION_COUNT = 3


@dataclass
class PipelineResult:
    answered: bool
    answer: str | None = None
    # (citation number used in the answer text, passage)
    sources: list[tuple[int, RetrievedChunk]] = field(default_factory=list)
    escalation_reason: EscalationReason | None = None
    # Scores, thresholds, timings and model names. Never prompts, keys, or user data.
    metadata: dict[str, Any] = field(default_factory=dict)


# Openers and pronouns that only make sense with the previous question ("and express?",
# "is it free?", "what about Canada?").
_FOLLOW_UP_CUES = re.compile(
    r"^\s*(and|also|what about|how about|what if|same for|then)\b|\b(it|that|this|they|them|those|these)\b",
    re.IGNORECASE,
)


def build_retrieval_query(question: str, history: list[ChatMessage]) -> str:
    """Give short follow-up questions the context of the previous customer question."""
    if len(terms(question)) <= 3 and _FOLLOW_UP_CUES.search(question):
        previous = next((m.content for m in reversed(history) if m.role == "user"), None)
        if previous:
            return f"{previous}\n{question}"
    return question


def _retrieval_summary(retrieval: RetrievalResult) -> dict[str, Any]:
    return {
        "candidates": retrieval.candidates,
        "kept": len(retrieval.chunks),
        "best_score": retrieval.best_score,
        "min_score": retrieval.min_score,
        "min_top_score": retrieval.min_top_score,
        "hits": [
            {"document_id": c.document_id, "chunk_id": c.chunk_id, "score": c.score}
            for c in retrieval.chunks
        ],
    }


def answer_question(
    db: Session,
    question: str,
    history: list[ChatMessage] | None = None,
    *,
    category: str | None = None,
    generator: AnswerGenerator | None = None,
    embedder: EmbeddingProvider | None = None,
    store: FaissVectorStore | None = None,
) -> PipelineResult:
    settings = get_settings()
    history = history or []
    generator = generator or get_answer_generator()
    started = time.perf_counter()
    metadata: dict[str, Any] = {
        "generator": f"{generator.name}:{generator.model}",
        "demo_mode": generator.is_demo,
    }

    def elapsed_ms() -> int:
        return round((time.perf_counter() - started) * 1000)

    def escalate(reason: EscalationReason, **details: Any) -> PipelineResult:
        metadata.update(details, decision="escalate", escalation_reason=reason.value, total_ms=elapsed_ms())
        return PipelineResult(answered=False, escalation_reason=reason, metadata=metadata)

    # Explicit request for a person: no point searching first.
    if wants_human(question):
        return escalate(EscalationReason.HUMAN_REQUESTED)

    query = build_retrieval_query(question, history)
    metadata["query_expanded"] = query != question
    try:
        retrieval = retrieve(db, query, category=category, embedder=embedder, store=store)
    except (ProviderError, VectorStoreError) as exc:
        logger.warning("Retrieval failed: %s", exc)
        return escalate(EscalationReason.PROVIDER_FAILURE, stage="retrieval", error=str(exc))
    metadata["retrieval"] = _retrieval_summary(retrieval)
    metadata["retrieval_ms"] = elapsed_ms()

    assessment = assess_evidence(
        query,
        retrieval,
        min_chunks=settings.escalation_min_chunks,
        min_coverage=settings.escalation_min_coverage,
    )
    metadata["coverage"] = round(assessment.coverage, 3)
    if not assessment.sufficient:
        return escalate(assessment.reason)  # type: ignore[arg-type]

    try:
        generation_started = time.perf_counter()
        generated = generator.generate(
            question, history[-settings.chat_history_turns :] if settings.chat_history_turns else [], retrieval.chunks
        )
        metadata["generation_ms"] = round((time.perf_counter() - generation_started) * 1000)
    except ProviderError as exc:
        logger.warning("Answer generation failed: %s", exc)
        return escalate(EscalationReason.PROVIDER_FAILURE, stage="generation", error=str(exc))

    if generated.abstained:
        return escalate(EscalationReason.INSUFFICIENT_EVIDENCE, model_abstained=True)

    if generated.cited:
        sources = [(number, retrieval.chunks[number - 1]) for number in generated.cited]
        score = groundedness(generated.text, [chunk.content for _, chunk in sources])
    else:
        score = groundedness(generated.text, [chunk.content for chunk in retrieval.chunks])
        if score < MIN_GROUNDEDNESS_WITHOUT_CITATIONS:
            return escalate(
                EscalationReason.INSUFFICIENT_EVIDENCE, uncited_answer=True, groundedness=round(score, 3)
            )
        sources = list(enumerate(retrieval.chunks[:INFERRED_CITATION_COUNT], start=1))
        metadata["citations_inferred"] = True

    metadata.update(groundedness=round(score, 3), decision="answer", total_ms=elapsed_ms())
    return PipelineResult(answered=True, answer=generated.text, sources=sources, metadata=metadata)
