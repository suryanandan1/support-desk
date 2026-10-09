from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.document import Document, DocumentChunk, DocumentStatus
from app.repositories.pagination import escape_like, paginate


def get(db: Session, document_id: int) -> Document | None:
    return db.get(Document, document_id, options=[selectinload(Document.uploaded_by)])


def get_by_hash(db: Session, content_hash: str) -> Document | None:
    return db.scalar(select(Document).where(Document.content_hash == content_hash))


def list_documents(
    db: Session,
    *,
    offset: int,
    limit: int,
    status: DocumentStatus | None = None,
    category: str | None = None,
    search: str | None = None,
) -> tuple[list[Document], int]:
    query = select(Document).options(selectinload(Document.uploaded_by))
    if status is not None:
        query = query.where(Document.status == status)
    if category:
        query = query.where(Document.category == category)
    if search and search.strip():
        pattern = f"%{escape_like(search.strip())}%"
        query = query.where(
            or_(
                Document.original_filename.ilike(pattern, escape="\\"),
                Document.category.ilike(pattern, escape="\\"),
            )
        )
    return paginate(db, query.order_by(Document.created_at.desc(), Document.id.desc()), offset=offset, limit=limit)


def all_documents(db: Session) -> list[Document]:
    return list(db.scalars(select(Document).order_by(Document.id)))


def chunk_ids(db: Session, document_id: int) -> list[int]:
    return list(db.scalars(select(DocumentChunk.id).where(DocumentChunk.document_id == document_id)))


def list_chunks(db: Session, document_id: int, *, offset: int, limit: int) -> tuple[list[DocumentChunk], int]:
    query = (
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
    )
    return paginate(db, query, offset=offset, limit=limit)


def categories(db: Session) -> list[str]:
    rows = db.scalars(
        select(Document.category).where(Document.category.is_not(None)).distinct().order_by(Document.category)
    )
    return [c for c in rows if c]


def count_by_status(db: Session) -> dict[DocumentStatus, int]:
    rows = db.execute(select(Document.status, func.count()).group_by(Document.status)).all()
    return {status: count for status, count in rows}
