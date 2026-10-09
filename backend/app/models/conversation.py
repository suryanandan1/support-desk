import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, enum_type, utcnow

if TYPE_CHECKING:
    from app.models.user import User


class ConversationStatus(enum.StrEnum):
    ACTIVE = "active"
    ESCALATED = "escalated"  # handed to the support team via a ticket
    CLOSED = "closed"


class MessageRole(enum.StrEnum):
    CUSTOMER = "customer"
    AI = "ai"
    SYSTEM = "system"  # automatic notices, e.g. "forwarded to the support team"


class AnswerStatus(enum.StrEnum):
    """Outcome of one AI turn. Drives the AI-resolution and escalation metrics."""

    ANSWERED = "answered"  # grounded answer backed by at least one cited source
    ESCALATED = "escalated"  # not answerable from the sources; a ticket was raised


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_customer_id_updated_at", "customer_id", "updated_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    status: Mapped[ConversationStatus] = mapped_column(
        enum_type(ConversationStatus), default=ConversationStatus.ACTIVE
    )

    customer: Mapped["User"] = relationship()
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Message.id",
    )


class Message(Base):
    """One chat turn. Agent replies are stored in ticket_messages, not here."""

    __tablename__ = "messages"
    # A client-generated id makes "retry send" idempotent: the same id is never stored twice.
    __table_args__ = (UniqueConstraint("conversation_id", "client_message_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[MessageRole] = mapped_column(enum_type(MessageRole))
    content: Mapped[str] = mapped_column(Text)
    client_message_id: Mapped[str | None] = mapped_column(String(64))
    # Set on AI messages only.
    answer_status: Mapped[AnswerStatus | None] = mapped_column(enum_type(AnswerStatus), index=True)
    # Retrieval scores, thresholds, model name, latency. Never secrets or prompts.
    rag_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    sources: Mapped[list["MessageSource"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="MessageSource.rank",
    )


class MessageSource(Base):
    """A citation: links an AI message to a knowledge-base chunk that supports it."""

    __tablename__ = "message_sources"
    __table_args__ = (UniqueConstraint("message_id", "rank"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )
    chunk_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="SET NULL"), index=True
    )
    # Snapshot of the citation, so it stays readable after the document is deleted.
    document_name: Mapped[str] = mapped_column(String(255))
    page_number: Mapped[int | None]
    section: Mapped[str | None] = mapped_column(String(255))
    snippet: Mapped[str] = mapped_column(Text)
    score: Mapped[float]
    rank: Mapped[int]  # 1 = most relevant

    message: Mapped[Message] = relationship(back_populates="sources")
