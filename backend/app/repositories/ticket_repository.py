from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.ticket import (
    SupportTicket,
    TicketAssignment,
    TicketCategory,
    TicketMessage,
    TicketPriority,
    TicketStatus,
)
from app.repositories.pagination import escape_like, paginate

ACTIVE_STATUSES = (TicketStatus.OPEN, TicketStatus.IN_PROGRESS, TicketStatus.WAITING_FOR_CUSTOMER)

_SUMMARY_OPTIONS = (selectinload(SupportTicket.customer), selectinload(SupportTicket.assigned_agent))


def get(db: Session, ticket_id: int, *, with_thread: bool = False) -> SupportTicket | None:
    options = list(_SUMMARY_OPTIONS)
    if with_thread:
        options += [
            selectinload(SupportTicket.messages).selectinload(TicketMessage.author),
            selectinload(SupportTicket.assignments).selectinload(TicketAssignment.agent),
            selectinload(SupportTicket.assignments).selectinload(TicketAssignment.assigned_by),
        ]
    return db.scalar(select(SupportTicket).where(SupportTicket.id == ticket_id).options(*options))


def by_trigger_message(db: Session, message_id: int) -> SupportTicket | None:
    return db.scalar(select(SupportTicket).where(SupportTicket.trigger_message_id == message_id))


def active_for_conversation(db: Session, conversation_id: int) -> SupportTicket | None:
    return db.scalar(
        select(SupportTicket)
        .where(SupportTicket.conversation_id == conversation_id, SupportTicket.status.in_(ACTIVE_STATUSES))
        .order_by(SupportTicket.id.desc())
        .limit(1)
    )


def by_ids(db: Session, ticket_ids: list[int]) -> list[SupportTicket]:
    if not ticket_ids:
        return []
    return list(db.scalars(select(SupportTicket).where(SupportTicket.id.in_(ticket_ids))))


def visible_query(*, customer_id: int | None = None, agent_id: int | None = None) -> Select:
    """Base query limited to what a user may see. No ids = everything (admins)."""
    query = select(SupportTicket)
    if customer_id is not None:
        query = query.where(SupportTicket.customer_id == customer_id)
    if agent_id is not None:
        query = query.where(
            or_(SupportTicket.assigned_agent_id == agent_id, SupportTicket.assigned_agent_id.is_(None))
        )
    return query


def list_tickets(
    db: Session,
    query: Select,
    *,
    offset: int,
    limit: int,
    status: TicketStatus | None = None,
    priority: TicketPriority | None = None,
    category: TicketCategory | None = None,
    assigned_to: int | None = None,
    unassigned: bool = False,
    active_only: bool = False,
    search: str | None = None,
) -> tuple[list[SupportTicket], int]:
    if status is not None:
        query = query.where(SupportTicket.status == status)
    if active_only:
        query = query.where(SupportTicket.status.in_(ACTIVE_STATUSES))
    if priority is not None:
        query = query.where(SupportTicket.priority == priority)
    if category is not None:
        query = query.where(SupportTicket.category == category)
    if assigned_to is not None:
        query = query.where(SupportTicket.assigned_agent_id == assigned_to)
    if unassigned:
        query = query.where(SupportTicket.assigned_agent_id.is_(None))
    if search and search.strip():
        term = search.strip()
        pattern = f"%{escape_like(term)}%"
        query = query.where(
            or_(
                SupportTicket.ticket_number.ilike(pattern, escape="\\"),
                SupportTicket.subject.ilike(pattern, escape="\\"),
            )
        )
    query = query.options(*_SUMMARY_OPTIONS).order_by(SupportTicket.updated_at.desc(), SupportTicket.id.desc())
    return paginate(db, query, offset=offset, limit=limit)


def count_by(db: Session, column, query: Select) -> dict:
    subquery = query.subquery()
    rows = db.execute(select(getattr(subquery.c, column.key), func.count()).group_by(getattr(subquery.c, column.key))).all()
    return dict(rows)
