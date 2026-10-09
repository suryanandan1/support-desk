"""Document ingestion pipeline: extract -> chunk -> embed -> index.

Runs inside the Celery worker. Status moves pending -> processing -> indexed | failed,
and the reason for a failure is stored on the document for the admin UI.
"""

import logging
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.storage import stored_file_path
from app.db.base import utcnow
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.rag.chunking import chunk_blocks
from app.rag.embeddings import get_embedding_provider
from app.rag.extraction import ExtractionError, extract_file
from app.rag.providers.base import EmbeddingProvider, ProviderError
from app.rag.vector_store import FaissVectorStore, VectorStoreError, get_vector_store

logger = logging.getLogger(__name__)

UNEXPECTED_FAILURE = "Unexpected error while processing the document. Check the worker log."


def embedding_text(document: Document, chunk: DocumentChunk) -> str:
    """Text that gets embedded: title and section give each passage its context."""
    title = Path(document.original_filename).stem.replace("_", " ").replace("-", " ")
    return "\n".join(part for part in (title, chunk.section, chunk.content) if part)


def _mark_failed(db: Session, document_id: int, message: str) -> None:
    document = db.get(Document, document_id)
    if document is not None:
        document.status = DocumentStatus.FAILED
        document.error_message = message
        db.commit()


def ingest_document(
    db: Session,
    document_id: int,
    *,
    embedder: EmbeddingProvider | None = None,
    store: FaissVectorStore | None = None,
) -> Document | None:
    document = db.get(Document, document_id)
    if document is None:
        logger.info("Document %s was deleted before ingestion started", document_id)
        return None

    settings = get_settings()
    embedder = embedder or get_embedding_provider()
    store = store or get_vector_store()

    document.status = DocumentStatus.PROCESSING
    document.error_message = None
    db.commit()

    try:
        extracted = extract_file(stored_file_path(document.stored_filename), document.file_extension)
        specs = chunk_blocks(extracted.blocks, settings.chunk_size, settings.chunk_overlap)
        if not specs:
            raise ExtractionError("The document contains no text to index.")

        old_chunk_ids = list(
            db.scalars(select(DocumentChunk.id).where(DocumentChunk.document_id == document.id))
        )
        db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
        chunks = [
            DocumentChunk(
                document_id=document.id,
                chunk_index=position,
                content=spec.content,
                page_number=spec.page_number,
                section=spec.section[:255] if spec.section else None,
                char_start=spec.char_start,
                char_end=spec.char_end,
            )
            for position, spec in enumerate(specs)
        ]
        db.add_all(chunks)
        db.flush()  # assigns chunk ids, which double as vector ids

        vectors = embedder.embed_documents([embedding_text(document, c) for c in chunks])
        store.replace(
            remove_ids=old_chunk_ids,
            add_ids=[c.id for c in chunks],
            vectors=vectors,
            signature=embedder.signature,
        )

        document.status = DocumentStatus.INDEXED
        document.chunk_count = len(chunks)
        document.page_count = extracted.page_count
        document.index_version += 1
        document.embedding_model = embedder.signature
        document.indexed_at = utcnow()
        db.commit()
        logger.info(
            "Indexed document %s: %d chunks (version %d)",
            document.id,
            len(chunks),
            document.index_version,
        )
        return document
    except (ExtractionError, ProviderError, VectorStoreError) as exc:
        db.rollback()
        logger.warning("Ingestion of document %s failed: %s", document_id, exc)
        _mark_failed(db, document_id, str(exc))
    except Exception:
        db.rollback()
        logger.exception("Ingestion of document %s crashed", document_id)
        _mark_failed(db, document_id, UNEXPECTED_FAILURE)
    return db.get(Document, document_id)
