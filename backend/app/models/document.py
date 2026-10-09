import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, enum_type, utcnow

if TYPE_CHECKING:
    from app.models.user import User


class DocumentStatus(enum.StrEnum):
    PENDING = "pending"  # stored, waiting for the ingestion worker
    PROCESSING = "processing"  # extracting, chunking, embedding
    INDEXED = "indexed"  # searchable
    FAILED = "failed"  # see error_message


class Document(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    # Random name used on disk. Never derived from user input (path traversal safety).
    stored_filename: Mapped[str] = mapped_column(String(255), unique=True)
    file_extension: Mapped[str] = mapped_column(String(10))
    content_type: Mapped[str | None] = mapped_column(String(100))
    size_bytes: Mapped[int]
    # SHA-256 of the file bytes; uploading the same file twice is rejected.
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # Optional label usable as a retrieval filter (e.g. "billing", "shipping").
    category: Mapped[str | None] = mapped_column(String(50), index=True)

    status: Mapped[DocumentStatus] = mapped_column(
        enum_type(DocumentStatus), default=DocumentStatus.PENDING, index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None]
    chunk_count: Mapped[int] = mapped_column(default=0)
    # Incremented on every successful (re)index; 0 means never indexed.
    index_version: Mapped[int] = mapped_column(default=0)
    # Embedding model that produced the stored vectors. A change means re-index.
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    # Celery task id of the most recent ingestion job, for status polling.
    task_id: Mapped[str | None] = mapped_column(String(64))
    indexed_at: Mapped[datetime | None]
    uploaded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    uploaded_by: Mapped["User | None"] = relationship()
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DocumentChunk.chunk_index",
    )


class DocumentChunk(Base):
    """One retrievable passage of a document.

    The primary key doubles as the vector id inside the FAISS index. The
    sqlite_autoincrement option guarantees ids are never reused after a delete, so a
    stale vector can never point at a different, newer chunk.
    """

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    chunk_index: Mapped[int]
    content: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int | None]
    section: Mapped[str | None] = mapped_column(String(255))
    char_start: Mapped[int]
    char_end: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    document: Mapped[Document] = relationship(back_populates="chunks")
