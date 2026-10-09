"""Alembic environment.

The database URL comes from app settings (DATABASE_URL in backend/.env) and the target
schema from the SQLAlchemy models, so migrations always match the running application.
"""

from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import create_engine, pool

import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.core.config import get_settings
from app.db.base import Base, UTCDateTime

config = context.config

# Callers such as the test suite can skip this so their own logging stays intact.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    # An explicit URL (used by tests) wins over the application setting.
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def _render_item(type_: str, obj: Any, _autogen_context: Any) -> str | bool:
    # Write the custom UTC type as a plain SQLAlchemy type, so migration files never
    # import application code that might change later.
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime(timezone=True)"
    return False


def _context_options(url: str) -> dict[str, Any]:
    return {
        "target_metadata": target_metadata,
        # SQLite cannot ALTER most things; batch mode rebuilds the table instead.
        "render_as_batch": url.startswith("sqlite"),
        "compare_type": True,
        "render_item": _render_item,
    }


def run_migrations_offline() -> None:
    url = _database_url()
    context.configure(
        url=url, literal_binds=True, dialect_opts={"paramstyle": "named"}, **_context_options(url)
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _database_url()
    # A plain engine (no foreign-key PRAGMA): SQLite batch migrations recreate tables,
    # which fails while foreign-key enforcement is switched on.
    connectable = create_engine(url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, **_context_options(url))
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
