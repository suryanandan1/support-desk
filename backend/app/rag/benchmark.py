"""Offline evaluation of the RAG pipeline against the sample knowledge base.

Used by scripts/evaluate_rag.py (human-readable report, threshold sweep) and by the
test suite (regression guard). Metric definitions:

  retrieval_hit_rate        answerable questions where a passage from an expected
                            document was retrieved
  attribution_rate          answered, answerable questions citing an expected document
  citation_precision        share of cited sources that come from expected documents
  groundedness              mean lexical support of answers by their cited sources
  fact_match_rate           answered, answerable questions containing every expected fact
  correct_escalation_rate   should-escalate questions that were escalated
  false_escalation_rate     answerable questions that were escalated anyway
  human_request_detection   explicit "talk to a person" requests escalated for that reason
  decision_accuracy         questions where answer-vs-escalate matched the expectation
  provider_failure_rate     questions escalated because the AI provider failed
"""

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import BACKEND_DIR, get_settings
from app.models.document import Document
from app.models.ticket import EscalationReason
from app.rag.embeddings import get_embedding_provider, retrieval_thresholds
from app.rag.evaluation import assess_evidence, wants_human
from app.rag.generation import AnswerGenerator
from app.rag.ingestion import ingest_document
from app.rag.pipeline import answer_question
from app.rag.providers.base import EmbeddingProvider
from app.rag.retrieval import RetrievalResult, retrieve
from app.rag.vector_store import FaissVectorStore
from app.repositories import document_repository
from app.services.document_service import import_file

SAMPLE_KB_DIR = BACKEND_DIR / "sample_data" / "knowledge_base"
DATASET_PATH = BACKEND_DIR / "eval" / "dataset.json"

SAMPLE_CATEGORIES = {
    "refund_policy.md": "returns",
    "shipping_and_delivery.md": "shipping",
    "subscription_plans.txt": "billing",
    "warranty_terms.pdf": "warranty",
    "account_and_security.docx": "account",
    "smarthub_troubleshooting.md": "technical",
}


def load_sample_knowledge_base(
    db: Session,
    *,
    uploader_id: int | None = None,
    embedder: EmbeddingProvider | None = None,
    store: FaissVectorStore | None = None,
) -> list[Document]:
    """Import and index the sample files in-process. Files already present are skipped."""
    loaded = []
    for filename, category in SAMPLE_CATEGORIES.items():
        data = (SAMPLE_KB_DIR / filename).read_bytes()
        document = import_file(db, filename=filename, data=data, category=category, uploader_id=uploader_id)
        if document is not None:
            loaded.append(ingest_document(db, document.id, embedder=embedder, store=store))
    return [d for d in loaded if d is not None]


@dataclass
class EvalCase:
    id: str
    kind: str
    question: str
    expected: str  # "answer" or "escalate"
    documents: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)


@dataclass
class CaseResult:
    case: EvalCase
    answered: bool
    reason: str | None
    answer: str | None
    cited_documents: list[str]
    retrieved_documents: list[str]
    groundedness: float | None
    total_ms: int | None

    @property
    def correct_decision(self) -> bool:
        return self.answered == (self.case.expected == "answer")

    @property
    def facts_present(self) -> bool:
        text = (self.answer or "").lower()
        return all(fact.lower() in text for fact in self.case.facts)


def load_dataset(path: Path = DATASET_PATH) -> list[EvalCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [EvalCase(**case) for case in raw["cases"]]


def run_cases(
    db: Session,
    cases: list[EvalCase],
    *,
    generator: AnswerGenerator | None = None,
    embedder: EmbeddingProvider | None = None,
    store: FaissVectorStore | None = None,
) -> list[CaseResult]:
    names = {d.id: d.original_filename for d in document_repository.all_documents(db)}
    results = []
    for case in cases:
        outcome = answer_question(db, case.question, generator=generator, embedder=embedder, store=store)
        hits = outcome.metadata.get("retrieval", {}).get("hits", [])
        results.append(
            CaseResult(
                case=case,
                answered=outcome.answered,
                reason=outcome.escalation_reason.value if outcome.escalation_reason else None,
                answer=outcome.answer,
                cited_documents=[chunk.document_name for _, chunk in outcome.sources],
                retrieved_documents=[names.get(hit["document_id"], "?") for hit in hits],
                groundedness=outcome.metadata.get("groundedness"),
                total_ms=outcome.metadata.get("total_ms"),
            )
        )
    return results


def _rate(values: list[bool]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def compute_metrics(results: list[CaseResult]) -> dict[str, Any]:
    answerable = [r for r in results if r.case.expected == "answer"]
    escalatable = [r for r in results if r.case.expected == "escalate"]
    answered_answerable = [r for r in answerable if r.answered]
    human = [r for r in results if r.case.kind == "human_request"]
    precision = [
        sum(d in r.case.documents for d in r.cited_documents) / len(r.cited_documents)
        for r in answered_answerable
        if r.cited_documents
    ]
    grounded = [r.groundedness for r in results if r.answered and r.groundedness is not None]
    latencies = sorted(r.total_ms for r in results if r.total_ms is not None)
    return {
        "cases": len(results),
        "answerable_cases": len(answerable),
        "escalation_cases": len(escalatable),
        "retrieval_hit_rate": _rate([any(d in r.case.documents for d in r.retrieved_documents) for r in answerable]),
        "attribution_rate": _rate([any(d in r.case.documents for d in r.cited_documents) for r in answered_answerable]),
        "citation_precision": round(statistics.mean(precision), 3) if precision else None,
        "groundedness": round(statistics.mean(grounded), 3) if grounded else None,
        "fact_match_rate": _rate([r.facts_present for r in answered_answerable if r.case.facts]),
        "correct_escalation_rate": _rate([not r.answered for r in escalatable]),
        "false_escalation_rate": _rate([not r.answered for r in answerable]),
        "human_request_detection": _rate([r.reason == EscalationReason.HUMAN_REQUESTED.value for r in human]),
        "decision_accuracy": _rate([r.correct_decision for r in results]),
        "provider_failure_rate": _rate([r.reason == EscalationReason.PROVIDER_FAILURE.value for r in results]),
        "latency_ms_mean": round(statistics.mean(latencies)) if latencies else None,
        "latency_ms_p95": latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))] if latencies else None,
    }


def sweep_thresholds(
    db: Session,
    cases: list[EvalCase],
    *,
    min_scores: list[float],
    min_top_scores: list[float],
    coverages: list[float],
    embedder: EmbeddingProvider | None = None,
    store: FaissVectorStore | None = None,
) -> list[dict[str, Any]]:
    """Replay the retrieval-stage escalation decision for every threshold combination.

    Retrieval runs once per question (with no threshold); the evidence check is then
    re-applied for each setting. Model abstention is not part of the sweep.
    """
    settings = get_settings()
    embedder = embedder or get_embedding_provider()
    raw: dict[str, RetrievalResult] = {
        case.id: retrieve(db, case.question, embedder=embedder, store=store, min_score=0.0)
        for case in cases
        if not wants_human(case.question)
    }
    rows = []
    for min_score in min_scores:
        for min_top in (t for t in min_top_scores if t >= min_score):
            for min_coverage in coverages:
                decisions = []
                for case in cases:
                    if case.id not in raw:
                        decisions.append((case, False))  # human request: always escalated
                        continue
                    kept = [c for c in raw[case.id].chunks if c.score >= min_score]
                    trial = RetrievalResult(query=case.question, chunks=kept, min_score=min_score, min_top_score=min_top)
                    verdict = assess_evidence(
                        case.question, trial, min_chunks=settings.escalation_min_chunks, min_coverage=min_coverage
                    )
                    decisions.append((case, verdict.sufficient))
                answerable = [answered for case, answered in decisions if case.expected == "answer"]
                escalatable = [answered for case, answered in decisions if case.expected == "escalate"]
                correct_escalation = sum(not a for a in escalatable) / len(escalatable)
                false_escalation = sum(not a for a in answerable) / len(answerable)
                rows.append(
                    {
                        "min_score": min_score,
                        "min_top_score": min_top,
                        "min_coverage": min_coverage,
                        "correct_escalation_rate": round(correct_escalation, 3),
                        "false_escalation_rate": round(false_escalation, 3),
                        "balanced_accuracy": round((correct_escalation + 1 - false_escalation) / 2, 3),
                    }
                )
    current_min, current_top = retrieval_thresholds(embedder)
    for row in rows:
        row["current"] = (
            row["min_score"] == current_min
            and row["min_top_score"] == current_top
            and row["min_coverage"] == settings.escalation_min_coverage
        )
    return sorted(rows, key=lambda r: (-r["balanced_accuracy"], r["false_escalation_rate"]))
