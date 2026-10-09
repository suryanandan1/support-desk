from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.conversation import Conversation, ConversationStatus, Message, MessageRole
from app.repositories.pagination import escape_like, paginate


def get(db: Session, conversation_id: int) -> Conversation | None:
    return db.get(Conversation, conversation_id)


def get_with_messages(db: Session, conversation_id: int) -> Conversation | None:
    return db.scalar(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(selectinload(Conversation.messages).selectinload(Message.sources))
    )


def list_for_customer(
    db: Session,
    customer_id: int,
    *,
    offset: int,
    limit: int,
    search: str | None = None,
    status: ConversationStatus | None = None,
) -> tuple[list[Conversation], int]:
    query = select(Conversation).where(Conversation.customer_id == customer_id)
    if status is not None:
        query = query.where(Conversation.status == status)
    if search and search.strip():
        query = query.where(Conversation.title.ilike(f"%{escape_like(search.strip())}%", escape="\\"))
    query = query.order_by(Conversation.updated_at.desc(), Conversation.id.desc())
    return paginate(db, query, offset=offset, limit=limit)


def message_stats(db: Session, conversation_ids: list[int]) -> dict[int, tuple[int, str | None]]:
    """conversation_id -> (message count, preview of the latest message)."""
    if not conversation_ids:
        return {}
    rows = db.execute(
        select(Message.conversation_id, func.count(), func.max(Message.id))
        .where(Message.conversation_id.in_(conversation_ids))
        .group_by(Message.conversation_id)
    ).all()
    latest_ids = [latest for _, _, latest in rows]
    previews = dict(db.execute(select(Message.id, Message.content).where(Message.id.in_(latest_ids))).all())
    return {conversation_id: (count, previews.get(latest)) for conversation_id, count, latest in rows}


def message_by_client_id(db: Session, conversation_id: int, client_message_id: str) -> Message | None:
    return db.scalar(
        select(Message).where(
            Message.conversation_id == conversation_id, Message.client_message_id == client_message_id
        )
    )


def reply_to(db: Session, message: Message) -> Message | None:
    """The assistant message that answered ``message`` (the next AI message after it)."""
    return db.scalar(
        select(Message)
        .where(
            Message.conversation_id == message.conversation_id,
            Message.id > message.id,
            Message.role == MessageRole.AI,
        )
        .order_by(Message.id)
        .limit(1)
        .options(selectinload(Message.sources))
    )


def recent_messages(db: Session, conversation_id: int, *, before_id: int, limit: int) -> list[Message]:
    rows = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.id < before_id)
        .order_by(Message.id.desc())
        .limit(limit)
    ).all()
    return list(reversed(rows))


def get_message(db: Session, message_id: int) -> Message | None:
    return db.scalar(
        select(Message).where(Message.id == message_id).options(selectinload(Message.conversation))
    )
