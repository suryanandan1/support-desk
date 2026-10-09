"""Importing this package registers every model with Base.metadata (Alembic relies on it)."""

from app.models.audit_log import AuditLog
from app.models.conversation import (
    AnswerStatus,
    Conversation,
    ConversationStatus,
    Message,
    MessageRole,
    MessageSource,
)
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.models.feedback import Feedback, FeedbackRating
from app.models.ticket import (
    EscalationReason,
    SupportTicket,
    TicketAssignment,
    TicketAuthorRole,
    TicketCategory,
    TicketMessage,
    TicketPriority,
    TicketStatus,
)
from app.models.user import User, UserRole

__all__ = [
    "AnswerStatus",
    "AuditLog",
    "Conversation",
    "ConversationStatus",
    "Document",
    "DocumentChunk",
    "DocumentStatus",
    "EscalationReason",
    "Feedback",
    "FeedbackRating",
    "Message",
    "MessageRole",
    "MessageSource",
    "SupportTicket",
    "TicketAssignment",
    "TicketAuthorRole",
    "TicketCategory",
    "TicketMessage",
    "TicketPriority",
    "TicketStatus",
    "User",
    "UserRole",
]
