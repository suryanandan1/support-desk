from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.user import UserRole
from app.schemas.common import PageParams


class UserListParams(PageParams):
    role: UserRole | None = None
    is_active: bool | None = None
    search: str | None = Field(default=None, max_length=100, description="Matches email or name")


class UserUpdate(BaseModel):
    """Admin-only changes to another account. Omitted fields are left unchanged."""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    role: UserRole | None = None
    is_active: bool | None = None

    @field_validator("full_name")
    @classmethod
    def _clean_name(cls, value: str | None) -> str | None:
        return " ".join(value.split()) if value is not None else None

    @model_validator(mode="after")
    def _require_a_change(self) -> "UserUpdate":
        if self.full_name is None and self.role is None and self.is_active is None:
            raise ValueError("Provide at least one of: full_name, role, is_active")
        return self
