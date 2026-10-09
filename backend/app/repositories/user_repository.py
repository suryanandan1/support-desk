"""All database access for users. Services call these; routes never query directly."""

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.repositories.pagination import escape_like, paginate


def get_by_id(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def get_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.strip().lower()))


def create(
    db: Session,
    *,
    email: str,
    full_name: str,
    hashed_password: str,
    role: UserRole = UserRole.CUSTOMER,
) -> User:
    user = User(
        email=email.strip().lower(),
        full_name=full_name,
        hashed_password=hashed_password,
        role=role,
    )
    db.add(user)
    db.flush()  # assigns user.id; raises IntegrityError on a duplicate email
    return user


def list_users(
    db: Session,
    *,
    offset: int,
    limit: int,
    role: UserRole | None = None,
    is_active: bool | None = None,
    search: str | None = None,
) -> tuple[list[User], int]:
    query = select(User)
    if role is not None:
        query = query.where(User.role == role)
    if is_active is not None:
        query = query.where(User.is_active == is_active)
    if search and search.strip():
        pattern = f"%{escape_like(search.strip())}%"
        query = query.where(
            or_(
                User.email.ilike(pattern, escape="\\"),
                User.full_name.ilike(pattern, escape="\\"),
            )
        )
    return paginate(db, query.order_by(User.id), offset=offset, limit=limit)
