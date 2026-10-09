"""Find the knowledge-base passages most relevant to a question."""

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.rag.embeddings import get_embedding_provider, retrieval_thresholds
from app.rag.providers.base import EmbeddingProvider
from app.rag.vector_store import FaissVectorStore, get_vector_store

logger = logging.getLogger(__name__)

# Ask FAISS for extra candidates because some are dropped afterwards (deleted
# documents, failed re-indexes, category filter).
_OVERSAMPLE = 4


@dataclass
class RetrievedChunk:
    chunk_id: int
    document_id: int
    document_name: str
    page_number: int | None
    section: str | None
    content: str
    score: float

    @property
    def location(self) -> str | None:
        if self.page_number is not None:
            return f"page {self.page_number}"
        return self.section


@dataclass
class RetrievalResult:
    query: str
    chunks: list[RetrievedChunk] = field(default_factory=list)  # best first, above min_score
    best_score: float | None = None  # best valid hit, even if below the threshold
    candidates: int = 0
    min_score: float = 0.0
    min_top_score: float = 0.0


def retrieve(
    db: Session,
    query: str,
    *,
    top_k: int | None = None,
    category: str | None = None,
    embedder: EmbeddingProvider | None = None,
    store: FaissVectorStore | None = None,
    min_score: float | None = None,
) -> RetrievalResult:
    """Embed ``query``, search the index, and keep passages from live, indexed documents.

    ``min_score`` overrides the configured threshold (the calibration sweep uses 0).
    Raises ProviderError (embedding failed) or VectorStoreError (index unusable).
    """
    embedder = embedder or get_embedding_provider()
    store = store or get_vector_store()
    top_k = top_k or get_settings().retrieval_top_k
    configured_min_score, min_top_score = retrieval_thresholds(embedder)
    if min_score is None:
        min_score = configured_min_score
    result = RetrievalResult(query=query, min_score=min_score, min_top_score=min_top_score)

    hits = store.search(embedder.embed_query(query), top_k * _OVERSAMPLE, embedder.signature)
    result.candidates = len(hits)
    if not hits:
        return result

    # Join back to the database: vectors of deleted or failed documents are ignored here,
    # which is what makes deletion take effect immediately.
    statement = (
        select(DocumentChunk, Document)
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(DocumentChunk.id.in_([chunk_id for chunk_id, _ in hits]))
        .where(Document.status == DocumentStatus.INDEXED)
    )
    if category:
        statement = statement.where(Document.category == category.strip().lower())
    rows = {chunk.id: (chunk, document) for chunk, document in db.execute(statement).all()}

    for chunk_id, score in hits:  # hits are already sorted best first
        if chunk_id not in rows:
            continue
        if result.best_score is None:
            result.best_score = score
        if score < min_score:
            continue
        chunk, document = rows[chunk_id]
        result.chunks.append(
            RetrievedChunk(
                chunk_id=chunk.id,
                document_id=document.id,
                document_name=document.original_filename,
                page_number=chunk.page_number,
                section=chunk.section,
                content=chunk.content,
                score=round(score, 4),
            )
        )
        if len(result.chunks) == top_k:
            break
    return result
