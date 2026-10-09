from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.ticket import (
    EscalationReason,
    TicketAuthorRole,
    TicketCategory,
    TicketPriority,
    TicketStatus,
)
from app.schemas.common import PageParams


class UserBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str


class TicketSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_number: str
    subject: str
    status: TicketStatus
    priority: TicketPriority
    category: TicketCategory
    escalation_reason: EscalationReason | None
    conversation_id: int | None
    customer: UserBrief
    assigned_agent: UserBrief | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None


class TicketMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    author_role: TicketAuthorRole
    author: UserBrief | None
    body: str
    is_internal: bool
    created_at: datetime


class TicketAssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent: UserBrief | None
    assigned_by: UserBrief | None
    created_at: datetime


class TicketDetail(TicketSummary):
    original_question: str
    resolution_notes: str | None
    closed_at: datetime | None
    messages: list[TicketMessageRead]
    # Staff only (empty / null for customers):
    assignments: list[TicketAssignmentRead] = []
    context_snapshot: dict[str, Any] | None = None
    customer_email: str | None = None
    # Customers only: whether the "Reopen" button applies.
    can_reopen: bool = False


def _strip(value: str | None) -> str | None:
    return value.strip() if isinstance(value, str) else value


class TicketCreate(BaseModel):
    """A customer contacting support directly (not through an AI escalation)."""

    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=1, max_length=5000)
    category: TicketCategory | None = None
    conversation_id: int | None = None

    _strip_text = field_validator("subject", "description", mode="before")(_strip)


class TicketUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: TicketStatus | None = None
    priority: TicketPriority | None = None
    category: TicketCategory | None = None
    resolution_notes: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def _require_a_change(self) -> "TicketUpdate":
        if all(value is None for value in (self.status, self.priority, self.category, self.resolution_notes)):
            raise ValueError("Provide at least one field to change")
        return self


class TicketMessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=5000)
    is_internal: bool = Field(default=False, description="Internal note, never shown to the customer")

    _strip_body = field_validator("body", mode="before")(_strip)


class TicketAssign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: int | None = Field(description="Null to unassign")


class TicketListParams(PageParams):
    status: TicketStatus | None = None
    priority: TicketPriority | None = None
    category: TicketCategory | None = None
    assignment: Literal["me", "unassigned", "any"] = "any"
    search: str | None = Field(default=None, max_length=100, description="Ticket number or subject")
    active_only: bool = Field(default=False, description="Exclude resolved and closed tickets")
