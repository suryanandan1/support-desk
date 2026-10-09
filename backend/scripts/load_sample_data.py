"""Load the sample knowledge base (fictional "Acme Home Devices") into your database.

The six files in sample_data/knowledge_base cover every supported format (MD, TXT,
PDF, DOCX). They are stored and indexed directly in this process, so this one-off setup
step works even before Memurai and the Celery worker are running. Files that are
already loaded are skipped.

Usage (from backend/, virtual environment active, after `alembic upgrade head`):
    python scripts/load_sample_data.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make "app" importable

from sqlalchemy import select  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from app.core.logging import setup_logging  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.rag.benchmark import SAMPLE_CATEGORIES, load_sample_knowledge_base  # noqa: E402


def main() -> int:
    setup_logging("WARNING")
    try:
        with SessionLocal() as db:
            admin = db.scalar(select(User).where(User.role == UserRole.ADMIN).order_by(User.id))
            documents = load_sample_knowledge_base(db, uploader_id=admin.id if admin else None)
    except OperationalError as exc:
        if "no such table" in str(exc):
            print("The database has no tables yet. Run this first:  alembic upgrade head")
            return 1
        raise

    skipped = len(SAMPLE_CATEGORIES) - len(documents)
    for document in documents:
        detail = f"{document.chunk_count} chunks" if document.status.value == "indexed" else document.error_message
        print(f"  {document.status.value:<8} {document.original_filename:<28} {detail}")
    if skipped:
        print(f"  {skipped} file(s) were already loaded and were skipped.")
    failed = [d for d in documents if d.status.value != "indexed"]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
