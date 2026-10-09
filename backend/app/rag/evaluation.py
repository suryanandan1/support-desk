"""Measurable checks that decide whether an answer can be given or must be escalated.

Escalation never relies on the model rating its own confidence. It uses:
  * retrieval similarity  - was anything relevant found, and is the best match strong?
  * evidence coverage     - do the passages mention the key terms of the question?
  * explicit abstention   - the model answered INSUFFICIENT_CONTEXT (see prompts.py)
  * citation checks       - an answer without valid citations must be well supported
  * explicit requests     - the customer asked for a human
"""

import re
from dataclasses import dataclass

from app.models.ticket import EscalationReason
from app.rag.retrieval import RetrievalResult
from app.rag.text import coverage, term_matches, terms

_CITATION = re.compile(r"\[\d{1,2}\]")

_HUMAN_REQUEST_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(speak|talk|chat)\s+(to|with)\s+(a|an|some|your|real)?\s*"
        r"(human|person|people|agent|representative|rep|someone|staff|operator)\b",
        r"\b(human|live|real)\s+(agent|person|being|support|representative|operator)\b",
        r"\b(connect|transfer|put)\s+me\s+(to|with|through)\b",
        r"\b(customer\s+service|support)\s+(agent|representative|team|staff)\b",
        r"\bescalate\b",
    )
]


def wants_human(text: str) -> bool:
    """True if the customer explicitly asks for a person instead of the assistant."""
    return any(pattern.search(text) for pattern in _HUMAN_REQUEST_PATTERNS)


@dataclass
class EvidenceAssessment:
    sufficient: bool
    reason: EscalationReason | None
    top_score: float | None
    coverage: float


def assess_evidence(
    question: str,
    retrieval: RetrievalResult,
    *,
    min_chunks: int,
    min_coverage: float,
) -> EvidenceAssessment:
    chunks = retrieval.chunks
    top_score = chunks[0].score if chunks else retrieval.best_score
    if not chunks:
        return EvidenceAssessment(False, EscalationReason.NO_RELEVANT_CONTENT, top_score, 0.0)
    share = coverage(question, [chunk.content for chunk in chunks])
    if chunks[0].score < retrieval.min_top_score:
        return EvidenceAssessment(False, EscalationReason.LOW_RETRIEVAL_SCORE, top_score, share)
    if len(chunks) < min_chunks:
        return EvidenceAssessment(False, EscalationReason.NO_RELEVANT_CONTENT, top_score, share)
    if share < min_coverage:
        return EvidenceAssessment(False, EscalationReason.INSUFFICIENT_EVIDENCE, top_score, share)
    return EvidenceAssessment(True, None, top_score, share)


def groundedness(answer: str, passages: list[str]) -> float:
    """Share of the answer's content words that also appear in the passages (0..1).

    A lexical proxy: a paraphrasing model scores below 1.0 even when faithful, but an
    answer that introduces facts absent from the sources scores visibly lower.
    """
    answer_terms = terms(_CITATION.sub(" ", answer))
    if not answer_terms:
        return 0.0
    vocabulary = {t for passage in passages for t in terms(passage)}
    supported = sum(1 for term in answer_terms if term_matches(term, vocabulary))
    return supported / len(answer_terms)
