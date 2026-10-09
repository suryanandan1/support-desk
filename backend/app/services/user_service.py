"""Admin user management: listing accounts, changing roles, (de)activating."""

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.models.user import User
from app.repositories import audit_repository, user_repository
from app.schemas.auth import UserRead
from app.schemas.common import Page
from app.schemas.user import UserListParams, UserUpdate

logger = logging.getLogger(__name__)


def list_users(db: Session, params: UserListParams) -> Page[UserRead]:
    users, total = user_repository.list_users(
        db,
        offset=params.offset,
        limit=params.page_size,
        role=params.role,
        is_active=params.is_active,
        search=params.search,
    )
    return Page[UserRead].build([UserRead.model_validate(u) for u in users], total, params)


def update_user(
    db: Session,
    *,
    actor: User,
    user_id: int,
    data: UserUpdate,
    ip_address: str | None = None,
) -> User:
    user = user_repository.get_by_id(db, user_id)
    if user is None:
        raise NotFoundError("User not found")

    requested = {field: value for field, value in data.model_dump().items() if value is not None}

    # An admin can never lock themselves out. Since only admins change roles, this
    # also guarantees at least one active admin always remains.
    if user.id == actor.id:
        if "role" in requested and requested["role"] != user.role:
            raise BusinessRuleError("You cannot change your own role")
        if requested.get("is_active") is False:
            raise BusinessRuleError("You cannot deactivate your own account")

    changes: dict[str, Any] = {}
    for field, new_value in requested.items():
        old_value = getattr(user, field)
        if old_value != new_value:
            setattr(user, field, new_value)
            changes[field] = {"from": old_value, "to": new_value}

    if changes:
        audit_repository.record(
            db,
            action="user.updated",
            actor_id=actor.id,
            entity_type="user",
            entity_id=user.id,
            details=changes,
            ip_address=ip_address,
        )
        db.commit()
        logger.info("User updated", extra={"user_id": user.id, "fields": sorted(changes)})
    return user
