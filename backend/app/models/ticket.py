import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, enum_type, utcnow

if TYPE_CHECKING:
    from app.models.conversation import Conversation
    from app.models.user import User


class TicketStatus(enum.StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    WAITING_FOR_CUSTOMER = "waiting_for_customer"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TicketPriority(enum.StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class TicketCategory(enum.StrEnum):
    GENERAL = "general"
    BILLING = "billing"
    TECHNICAL = "technical"
    ACCOUNT = "account"
    PRODUCT = "product"
    OTHER = "other"


class EscalationReason(enum.StrEnum):
    NO_RELEVANT_CONTENT = "no_relevant_content"  # retrieval found nothing usable
    LOW_RETRIEVAL_SCORE = "low_retrieval_score"  # best evidence below the threshold
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"  # sources do not cover the question
    PROVIDER_FAILURE = "provider_failure"  # AI provider still failing after retries
    HUMAN_REQUESTED = "human_requested"  # customer asked for a person


class TicketAuthorRole(enum.StrEnum):
    CUSTOMER = "customer"
    AGENT = "agent"  # support agents and admins
    SYSTEM = "system"  # automatic events, e.g. "Status changed to Resolved"


class SupportTicket(TimestampMixin, Base):
    __tablename__ = "support_tickets"
    __table_args__ = (
        Index("ix_support_tickets_status_priority", "status", "priority"),
        Index("ix_support_tickets_updated_at", "updated_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), index=True
    )
    # The customer message that triggered an automatic escalation. Unique, so one
    # escalation event can never produce two tickets, even under concurrent requests.
    trigger_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), unique=True
    )

    subject: Mapped[str] = mapped_column(String(200))
    # Exactly what the customer asked. Written once, never edited.
    original_question: Mapped[str] = mapped_column(Text)
    # Recent conversation turns and a retrieval summary captured at escalation time.
    context_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    category: Mapped[TicketCategory] = mapped_column(
        enum_type(TicketCategory), default=TicketCategory.GENERAL, index=True
    )
    priority: Mapped[TicketPriority] = mapped_column(
        enum_type(TicketPriority), default=TicketPriority.MEDIUM
    )
    status: Mapped[TicketStatus] = mapped_column(
        enum_type(TicketStatus), default=TicketStatus.OPEN
    )
    # None for tickets a customer opened directly.
    escalation_reason: Mapped[EscalationReason | None] = mapped_column(
        enum_type(EscalationReason)
    )

    assigned_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None]
    closed_at: Mapped[datetime | None]

    customer: Mapped["User"] = relationship(foreign_keys=[customer_id])
    assigned_agent: Mapped["User | None"] = relationship(foreign_keys=[assigned_agent_id])
    conversation: Mapped["Conversation | None"] = relationship()
    messages: Mapped[list["TicketMessage"]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TicketMessage.id",
    )
    assignments: Mapped[list["TicketAssignment"]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TicketAssignment.id",
    )


class TicketMessage(Base):
    """The ticket thread: customer follow-ups, agent replies, internal notes, events."""

    __tablename__ = "ticket_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("support_tickets.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    author_role: Mapped[TicketAuthorRole] = mapped_column(enum_type(TicketAuthorRole))
    body: Mapped[str] = mapped_column(Text)
    # Internal notes are visible to agents and admins only, never to the customer.
    is_internal: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    ticket: Mapped[SupportTicket] = relationship(back_populates="messages")
    author: Mapped["User | None"] = relationship()


class TicketAssignment(Base):
    """Assignment history: one row every time a ticket changes hands."""

    __tablename__ = "ticket_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("support_tickets.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[int | None] = mapped_column(  # None = unassigned
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    assigned_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    ticket: Mapped[SupportTicket] = relationship(back_populates="assignments")
    agent: Mapped["User | None"] = relationship(foreign_keys=[agent_id])
