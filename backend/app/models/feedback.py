import enum

from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, enum_type


class FeedbackRating(enum.StrEnum):
    HELPFUL = "helpful"
    UNHELPFUL = "unhelpful"


class Feedback(TimestampMixin, Base):
    """A customer's rating of one AI answer. Used for analytics only; it never edits
    the knowledge base automatically."""

    __tablename__ = "feedback"
    # One rating per answer per user; rating again updates the existing row.
    __table_args__ = (UniqueConstraint("message_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    rating: Mapped[FeedbackRating] = mapped_column(enum_type(FeedbackRating), index=True)
    comment: Mapped[str | None] = mapped_column(Text)
