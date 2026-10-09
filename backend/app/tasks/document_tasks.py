"""Document ingestion jobs."""

import logging

from app.db.session import SessionLocal
from app.rag.ingestion import ingest_document
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="documents.ingest")
def ingest_document_task(document_id: int) -> None:
    """Extract, chunk, embed and index one document. Failures are recorded on the row."""
    with SessionLocal() as db:
        ingest_document(db, document_id)
