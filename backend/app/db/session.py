"""Engine and session factory."""

from collections.abc import Iterator
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def _configure_sqlite_connection(dbapi_connection: Any, _connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    # SQLite ignores foreign keys (and therefore ON DELETE CASCADE) unless told otherwise.
    cursor.execute("PRAGMA foreign_keys=ON")
    # Write-ahead logging lets the API read while a background worker writes.
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def build_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite"):
        engine = create_engine(
            database_url,
            # FastAPI runs sync routes in a thread pool; allow cross-thread use and
            # wait up to 15 s for a locked database instead of failing immediately.
            connect_args={"check_same_thread": False, "timeout": 15},
        )
        event.listen(engine, "connect", _configure_sqlite_connection)
        return engine
    return create_engine(database_url, pool_pre_ping=True)


engine = build_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed afterwards."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
