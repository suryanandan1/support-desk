"""Helpers shared by every repository that returns paginated lists."""

from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session


def escape_like(term: str) -> str:
    """Escape LIKE wildcards so a search for "50%" matches the literal text."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def paginate(db: Session, query: Select[Any], *, offset: int, limit: int) -> tuple[list[Any], int]:
    """Run ``query`` for one page and return ``(items, total_matching_rows)``."""
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    items = list(db.scalars(query.offset(offset).limit(limit)).all())
    return items, total
