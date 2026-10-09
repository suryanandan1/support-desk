"""Create one demo account per role so the app is usable right after setup.

Usage (from backend/, with the virtual environment active):
    python scripts/seed.py
    python scripts/seed.py --password "YourOwnPass123"

Safe to run repeatedly: existing accounts are left untouched. Refuses to run when
ENVIRONMENT=production.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make "app" importable

from sqlalchemy.exc import OperationalError  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.user import UserRole  # noqa: E402
from app.repositories import user_repository  # noqa: E402
from app.schemas.auth import validate_password_strength  # noqa: E402

DEMO_USERS = [
    ("admin@example.com", "Ada Admin", UserRole.ADMIN),
    ("agent@example.com", "Sam Agent", UserRole.AGENT),
    ("customer@example.com", "Casey Customer", UserRole.CUSTOMER),
]
DEFAULT_PASSWORD = "ChangeMe123!"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--password",
        default=DEFAULT_PASSWORD,
        help=f"password for every demo account (default: {DEFAULT_PASSWORD})",
    )
    args = parser.parse_args()

    if get_settings().environment == "production":
        print("Refusing to create demo accounts with ENVIRONMENT=production.")
        return 1
    try:
        validate_password_strength(args.password)
    except ValueError as exc:
        print(f"Invalid password: {exc}")
        return 1

    created = 0
    try:
        with SessionLocal() as db:
            for email, full_name, role in DEMO_USERS:
                if user_repository.get_by_email(db, email) is not None:
                    print(f"  exists   {role.value:<9} {email}")
                    continue
                user_repository.create(
                    db,
                    email=email,
                    full_name=full_name,
                    hashed_password=hash_password(args.password),
                    role=role,
                )
                created += 1
                print(f"  created  {role.value:<9} {email}")
            db.commit()
    except OperationalError as exc:
        if "no such table" in str(exc):
            print("The database has no tables yet. Run this first:  alembic upgrade head")
            return 1
        raise

    if created:
        print(f"\nNew accounts use the password: {args.password}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
