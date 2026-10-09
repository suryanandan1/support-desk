"""Declarative base, shared column helpers, and database-portable column types."""

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from sqlalchemy import DateTime, Dialect, MetaData, TypeDecorator
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names. Alembic needs these to alter or drop constraints
# later, especially on SQLite where migrations rebuild tables in "batch" mode.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC datetimes on every database.

    SQLite has no timezone support and returns naive values. This type stores UTC and
    always returns aware datetimes, so date arithmetic (e.g. ticket resolution time)
    behaves the same on SQLite and PostgreSQL.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetime passed to the database; use datetime.now(UTC)")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def enum_type(enum_cls: type[Enum]) -> SQLEnum:
    """Store an Enum by its string value (e.g. "in_progress") in a VARCHAR column.

    ``native_enum=False`` avoids PostgreSQL ENUM types, which need hand-written
    migrations every time a value is added.
    """
    return SQLEnum(
        enum_cls,
        native_enum=False,
        length=32,
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    # Every ``Mapped[datetime]`` column uses the UTC-safe type automatically.
    type_annotation_map: dict[Any, Any] = {datetime: UTCDateTime()}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
