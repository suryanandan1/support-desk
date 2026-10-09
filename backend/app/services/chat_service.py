"""Customer conversations with the AI assistant.

post_message() persists each turn around the RAG pipeline:
  1. store the customer message (committed before the AI runs, so it is never lost)
  2. run the pipeline (retrieve, check evidence, generate, check citations)
  3. store the AI reply with its citations, or an escalation notice and a ticket
"""

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import BusinessRuleError, NotFoundError
from app.db.base import utcnow
from app.models.conversation import AnswerStatus, Conversation, ConversationStatus, Message, MessageRole, MessageSource
from app.models.feedback import Feedback
from app.models.ticket import EscalationReason
from app.models.user import User, UserRole
from app.rag.pipeline import PipelineResult, answer_question
from app.rag.providers.base import ChatMessage
from app.repositories import conversation_repository
from app.schemas.chat import (
    ChatTurnRead,
    ConversationCreate,
    ConversationDetail,
    ConversationListParams,
    ConversationRead,
    FeedbackSummary,
    MessageCreate,
    MessageRead,
    SourceRead,
    TicketReference,
)
from app.schemas.common import Page
from app.services import ticket_service

logger = logging.getLogger(__name__)

DEFAULT_TITLE = "New conversation"
SNIPPET_CHARS = 300

ESCALATION_NOTICES = {
    EscalationReason.HUMAN_REQUESTED: (
        "Of course. I've passed your request to our support team, and a member of staff "
        "will reply to you here."
    ),
    EscalationReason.PROVIDER_FAILURE: (
        "Sorry, the assistant is having technical difficulties right now, so I've forwarded "
        "your question to our support team. They will get back to you."
    ),
}
DEFAULT_NOTICE = (
    "I couldn't find a reliable answer to that in our documentation, so I've forwarded your "
    "question to our support team rather than guess. They will get back to you."
)


def _title_from(question: str) -> str:
    title = " ".join(question.split())
    return title if len(title) <= 60 else title[:57].rsplit(" ", 1)[0] + "..."


# --------------------------------------------------------------------------- reads


def _get_for_customer(db: Session, customer: User, conversation_id: int) -> Conversation:
    conversation = conversation_repository.get(db, conversation_id)
    # Someone else's conversation looks exactly like a missing one: no existence leak.
    if conversation is None or conversation.customer_id != customer.id:
        raise NotFoundError("Conversation not found")
    return conversation


def _to_read(conversation: Conversation, stats: tuple[int, str | None] | None) -> ConversationRead:
    count, preview = stats or (0, None)
    return ConversationRead(
        id=conversation.id,
        title=conversation.title,
        status=conversation.status,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        message_count=count,
        last_message_preview=preview[:120] if preview else None,
    )


def _message_reads(db: Session, messages: list[Message], viewer: User) -> list[MessageRead]:
    ai_ids = [m.id for m in messages if m.role == MessageRole.AI]
    feedback = {
        f.message_id: f
        for f in db.scalars(select(Feedback).where(Feedback.message_id.in_(ai_ids), Feedback.user_id == viewer.id))
    } if ai_ids else {}
    tickets = ticket_service.tickets_for_messages(db, messages)
    reads = []
    for message in messages:
        read = MessageRead.model_validate(message)
        read.sources = [SourceRead.model_validate(s) for s in message.sources]
        if message.id in feedback:
            read.feedback = FeedbackSummary(rating=feedback[message.id].rating, comment=feedback[message.id].comment)
        if message.id in tickets:
            ticket = tickets[message.id]
            read.ticket = TicketReference(id=ticket.id, ticket_number=ticket.ticket_number, status=ticket.status.value)
        reads.append(read)
    return reads


def create_conversation(db: Session, *, customer: User, data: ConversationCreate) -> ConversationRead:
    title = (data.title or "").strip() or DEFAULT_TITLE
    conversation = Conversation(customer_id=customer.id, title=title)
    db.add(conversation)
    db.commit()
    return _to_read(conversation, None)


def list_conversations(db: Session, *, customer: User, params: ConversationListParams) -> Page[ConversationRead]:
    items, total = conversation_repository.list_for_customer(
        db, customer.id, offset=params.offset, limit=params.page_size, search=params.search, status=params.status
    )
    stats = conversation_repository.message_stats(db, [c.id for c in items])
    return Page[ConversationRead].build([_to_read(c, stats.get(c.id)) for c in items], total, params)


def get_conversation(db: Session, *, viewer: User, conversation_id: int) -> ConversationDetail:
    conversation = conversation_repository.get_with_messages(db, conversation_id)
    # Customers see their own conversations; support staff may read any for ticket context.
    if conversation is None or (viewer.role == UserRole.CUSTOMER and conversation.customer_id != viewer.id):
        raise NotFoundError("Conversation not found")
    stats = (len(conversation.messages), conversation.messages[-1].content if conversation.messages else None)
    base = _to_read(conversation, stats)
    return ConversationDetail(
        **base.model_dump(),
        customer_id=conversation.customer_id,
        messages=_message_reads(db, conversation.messages, viewer),
    )


# --------------------------------------------------------------------------- the chat turn


def _history(db: Session, conversation_id: int, before_id: int) -> list[ChatMessage]:
    """Earlier turns for follow-up questions. Escalation notices are left out."""
    limit = get_settings().chat_history_turns
    if not limit:
        return []
    history = []
    for message in conversation_repository.recent_messages(db, conversation_id, before_id=before_id, limit=limit):
        if message.role == MessageRole.CUSTOMER:
            history.append(ChatMessage("user", message.content))
        elif message.role == MessageRole.AI and message.answer_status == AnswerStatus.ANSWERED:
            history.append(ChatMessage("assistant", message.content))
    return history


def _store_reply(
    db: Session, *, conversation: Conversation, customer: User, question: Message, result: PipelineResult
) -> Message:
    if result.answered:
        reply = Message(
            conversation_id=conversation.id,
            role=MessageRole.AI,
            content=result.answer or "",
            answer_status=AnswerStatus.ANSWERED,
            rag_metadata=result.metadata,
        )
        reply.sources = [
            MessageSource(
                rank=number,
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                document_name=chunk.document_name,
                page_number=chunk.page_number,
                section=chunk.section,
                snippet=chunk.content[:SNIPPET_CHARS],
                score=chunk.score,
            )
            for number, chunk in result.sources
        ]
        db.add(reply)
        return reply

    reason = result.escalation_reason or EscalationReason.INSUFFICIENT_EVIDENCE
    reply = Message(
        conversation_id=conversation.id,
        role=MessageRole.AI,
        content=ESCALATION_NOTICES.get(reason, DEFAULT_NOTICE),
        answer_status=AnswerStatus.ESCALATED,
        rag_metadata=result.metadata,
    )
    db.add(reply)
    db.flush()
    ticket_service.escalate_from_chat(
        db, conversation=conversation, customer=customer, question=question, reply=reply, reason=reason, result=result
    )
    conversation.status = ConversationStatus.ESCALATED
    return reply


def _answer(db: Session, *, conversation: Conversation, customer: User, question: Message, category: str | None) -> Message:
    result = answer_question(db, question.content, _history(db, conversation.id, question.id), category=category)
    reply = _store_reply(db, conversation=conversation, customer=customer, question=question, result=result)
    conversation.updated_at = utcnow()
    db.commit()
    logger.info(
        "Chat turn answered=%s reason=%s",
        result.answered,
        result.escalation_reason.value if result.escalation_reason else None,
        extra={"conversation_id": conversation.id},
    )
    return reply


def post_message(db: Session, *, customer: User, conversation_id: int, data: MessageCreate) -> ChatTurnRead:
    settings = get_settings()
    if len(data.content) > settings.max_question_length:
        raise BusinessRuleError(f"Messages can be at most {settings.max_question_length} characters long.")
    conversation = _get_for_customer(db, customer, conversation_id)
    if conversation.status == ConversationStatus.CLOSED:
        raise BusinessRuleError("This conversation is closed. Please start a new one.")

    question: Message | None = None
    if data.client_message_id:
        question = conversation_repository.message_by_client_id(db, conversation.id, data.client_message_id)

    if question is None:
        question = Message(
            conversation_id=conversation.id,
            role=MessageRole.CUSTOMER,
            content=data.content,
            client_message_id=data.client_message_id,
        )
        db.add(question)
        if conversation.title == DEFAULT_TITLE:
            conversation.title = _title_from(data.content)
        conversation.updated_at = utcnow()
        try:
            db.commit()
        except IntegrityError:
            # The same client_message_id arrived twice at once; use the stored one.
            db.rollback()
            question = conversation_repository.message_by_client_id(db, conversation.id, data.client_message_id or "")
            if question is None:
                raise

    # A retried send returns the original reply instead of asking the AI again.
    reply = conversation_repository.reply_to(db, question)
    if reply is None:
        reply = _answer(db, conversation=conversation, customer=customer, question=question, category=data.category)

    db.refresh(conversation)
    stats = conversation_repository.message_stats(db, [conversation.id]).get(conversation.id)
    customer_read, reply_read = _message_reads(db, [question, reply], customer)
    return ChatTurnRead(
        conversation=_to_read(conversation, stats), customer_message=customer_read, assistant_message=reply_read
    )
