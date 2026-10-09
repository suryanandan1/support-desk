"""Knowledge-base management: upload, list, delete, re-index."""

import hashlib
import logging
import mimetypes

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.core.storage import UploadRejected, delete_file, safe_display_name, save_file, validate_upload
from app.models.document import Document, DocumentStatus
from app.models.user import User
from app.rag.embeddings import get_embedding_provider
from app.rag.vector_store import VectorStoreError, get_vector_store
from app.repositories import audit_repository, document_repository
from app.schemas.common import Page, PageParams
from app.schemas.document import (
    ChunkRead,
    DocumentListParams,
    DocumentRead,
    IndexStatusRead,
    UploadError,
    UploadResult,
)

logger = logging.getLogger(__name__)

QUEUE_UNAVAILABLE = (
    "Could not queue the processing job: the task queue (Redis/Memurai) is unreachable. "
    "Start Memurai and the Celery worker, then click Re-index."
)


def _mark_queue_unavailable(db: Session, document: Document) -> None:
    document.status = DocumentStatus.FAILED
    document.error_message = QUEUE_UNAVAILABLE
    db.commit()


def _enqueue_ingestion(db: Session, document: Document) -> bool:
    """Queue the ingestion job. Returns False (and marks the document) if the queue is down."""
    # Imported here so the API can start (and tests can run) without loading Celery early.
    from app.tasks.document_tasks import ingest_document_task

    try:
        result = ingest_document_task.apply_async(args=[document.id])
    except Exception as exc:  # noqa: BLE001 - kombu raises several connection error types
        logger.error("Could not queue ingestion of document %s: %s", document.id, type(exc).__name__)
        _mark_queue_unavailable(db, document)
        return False
    document.task_id = result.id
    db.commit()
    return True


def _enqueue_all(db: Session, documents: list[Document]) -> None:
    # Each failed publish waits for a connection timeout, so after the first failure
    # the rest are marked immediately instead of making the request hang.
    for position, document in enumerate(documents):
        if not _enqueue_ingestion(db, document):
            for remaining in documents[position + 1 :]:
                _mark_queue_unavailable(db, remaining)
            return


def _store_new_document(
    *, name: str, extension: str, data: bytes, digest: str, category: str | None, uploader_id: int | None
) -> Document:
    """Save the file to disk and build its (not yet added) database row."""
    return Document(
        original_filename=name,
        stored_filename=save_file(data, extension),
        file_extension=extension,
        content_type=mimetypes.guess_type(name)[0],
        size_bytes=len(data),
        content_hash=digest,
        category=category,
        uploaded_by_id=uploader_id,
        status=DocumentStatus.PENDING,
    )


def import_file(
    db: Session, *, filename: str, data: bytes, category: str | None, uploader_id: int | None
) -> Document | None:
    """Validate and store one file for a script (e.g. sample data); None if already present.

    Unlike uploads, nothing is queued: the caller ingests the document itself.
    Raises UploadRejected for invalid files.
    """
    name, extension = validate_upload(filename, data)
    digest = hashlib.sha256(data).hexdigest()
    if document_repository.get_by_hash(db, digest) is not None:
        return None
    document = _store_new_document(
        name=name,
        extension=extension,
        data=data,
        digest=digest,
        category=(category or "").strip().lower() or None,
        uploader_id=uploader_id,
    )
    db.add(document)
    db.commit()
    return document


def _ensure_not_processing(document: Document) -> None:
    if document.status == DocumentStatus.PROCESSING:
        raise ConflictError("The document is being processed right now. Try again shortly.")


def get_document(db: Session, document_id: int) -> Document:
    document = document_repository.get(db, document_id)
    if document is None:
        raise NotFoundError("Document not found")
    return document


def upload_documents(
    db: Session,
    *,
    files: list[tuple[str | None, bytes]],
    category: str | None,
    actor: User,
    ip_address: str | None,
) -> UploadResult:
    errors: list[UploadError] = []
    created: list[Document] = []
    stored_names: list[str] = []
    seen_hashes: set[str] = set()
    category = (category or "").strip().lower() or None

    try:
        for filename, data in files:
            try:
                name, extension = validate_upload(filename, data)
            except UploadRejected as rejected:
                errors.append(
                    UploadError(filename=safe_display_name(filename), code=rejected.code, message=rejected.message)
                )
                continue

            digest = hashlib.sha256(data).hexdigest()
            existing = document_repository.get_by_hash(db, digest)
            if existing is not None or digest in seen_hashes:
                where = f" as '{existing.original_filename}'" if existing is not None else " in this batch"
                errors.append(
                    UploadError(
                        filename=name,
                        code="duplicate",
                        message=f"This exact file was already uploaded{where}.",
                    )
                )
                continue
            seen_hashes.add(digest)

            document = _store_new_document(
                name=name, extension=extension, data=data, digest=digest, category=category, uploader_id=actor.id
            )
            stored_names.append(document.stored_filename)
            db.add(document)
            created.append(document)

        if created:
            db.flush()
            for document in created:
                audit_repository.record(
                    db,
                    action="document.uploaded",
                    actor_id=actor.id,
                    entity_type="document",
                    entity_id=document.id,
                    details={"filename": document.original_filename, "size_bytes": document.size_bytes},
                    ip_address=ip_address,
                )
            db.commit()
    except IntegrityError as exc:
        # The same file uploaded twice at the same moment: the unique hash catches it.
        db.rollback()
        for stored in stored_names:
            delete_file(stored)
        raise ConflictError("A file in this upload was just added by another request.") from exc
    except Exception:
        db.rollback()
        for stored in stored_names:
            delete_file(stored)
        raise

    _enqueue_all(db, created)
    for document in created:
        db.refresh(document)
    return UploadResult(documents=[DocumentRead.model_validate(d) for d in created], errors=errors)


def list_documents(db: Session, params: DocumentListParams) -> Page[DocumentRead]:
    documents, total = document_repository.list_documents(
        db,
        offset=params.offset,
        limit=params.page_size,
        status=params.status,
        category=params.category.strip().lower() if params.category else None,
        search=params.search,
    )
    return Page[DocumentRead].build([DocumentRead.model_validate(d) for d in documents], total, params)


def list_chunks(db: Session, document_id: int, params: PageParams) -> Page[ChunkRead]:
    get_document(db, document_id)
    chunks, total = document_repository.list_chunks(
        db, document_id, offset=params.offset, limit=params.page_size
    )
    return Page[ChunkRead].build([ChunkRead.model_validate(c) for c in chunks], total, params)


def delete_document(db: Session, *, document_id: int, actor: User, ip_address: str | None) -> None:
    document = get_document(db, document_id)
    _ensure_not_processing(document)
    chunk_ids = document_repository.chunk_ids(db, document.id)
    stored = document.stored_filename

    # Chunks are deleted by cascade. Citations keep their text snapshot (FK set to NULL).
    db.delete(document)
    audit_repository.record(
        db,
        action="document.deleted",
        actor_id=actor.id,
        entity_type="document",
        entity_id=document_id,
        details={"filename": document.original_filename, "chunks": len(chunk_ids)},
        ip_address=ip_address,
    )
    db.commit()

    # Search results are joined against the database, so the deleted chunks are already
    # unreachable; removing the vectors keeps the index file tidy.
    try:
        get_vector_store().remove(chunk_ids)
    except VectorStoreError:
        logger.warning("Could not remove vectors of deleted document %s", document_id, exc_info=True)
    delete_file(stored)


def reindex_document(db: Session, *, document_id: int, actor: User, ip_address: str | None) -> Document:
    document = get_document(db, document_id)
    _ensure_not_processing(document)
    document.status = DocumentStatus.PENDING
    document.error_message = None
    audit_repository.record(
        db,
        action="document.reindex_requested",
        actor_id=actor.id,
        entity_type="document",
        entity_id=document.id,
        ip_address=ip_address,
    )
    db.commit()
    _enqueue_ingestion(db, document)
    db.refresh(document)
    return document


def rebuild_index(db: Session, *, actor: User, ip_address: str | None) -> int:
    """Start a fresh index with the current embedding model and re-ingest everything."""
    embedder = get_embedding_provider()
    documents = [
        d for d in document_repository.all_documents(db) if d.status != DocumentStatus.PROCESSING
    ]
    get_vector_store().reset(embedder.signature, embedder.dimensions)
    for document in documents:
        document.status = DocumentStatus.PENDING
        document.error_message = None
    audit_repository.record(
        db,
        action="document.index_rebuilt",
        actor_id=actor.id,
        entity_type="vector_index",
        details={"documents": len(documents), "signature": embedder.signature},
        ip_address=ip_address,
    )
    db.commit()
    _enqueue_all(db, documents)
    return len(documents)


def index_status(db: Session) -> IndexStatusRead:
    embedder = get_embedding_provider()
    status = get_vector_store().status()
    counts = {s.value: 0 for s in DocumentStatus}
    counts.update({s.value: n for s, n in document_repository.count_by_status(db).items()})
    return IndexStatusRead(
        vector_count=status.vector_count,
        index_signature=status.signature,
        expected_signature=embedder.signature,
        needs_rebuild=status.exists and status.signature != embedder.signature,
        updated_at=status.updated_at,
        document_counts=counts,
        categories=document_repository.categories(db),
    )
