from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.feedback import FeedbackRating
from app.schemas.common import PageParams


class FeedbackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: int
    rating: FeedbackRating
    comment: str | None = Field(default=None, max_length=1000)

    @field_validator("comment")
    @classmethod
    def _clean(cls, value: str | None) -> str | None:
        value = value.strip() if value else None
        return value or None


class FeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    message_id: int
    conversation_id: int
    rating: FeedbackRating
    comment: str | None
    created_at: datetime
    updated_at: datetime


class FeedbackAdminRead(FeedbackRead):
    """Feedback with the question and answer, to spot gaps in the knowledge base."""

    customer_name: str
    question: str | None
    answer_excerpt: str


class FeedbackListParams(PageParams):
    rating: FeedbackRating | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
