"""The Alembic migrations must build exactly the schema the models describe."""

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect

import app.models  # noqa: F401
from app.core.config import BACKEND_DIR
from app.db.base import Base


def _alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["configure_logger"] = False
    return config


def test_upgrade_matches_models_and_downgrade_removes_everything(tmp_path: Path):
    url = f"sqlite:///{(tmp_path / 'migrations.db').as_posix()}"
    config = _alembic_config(url)
    engine = create_engine(url)
    try:
        command.upgrade(config, "head")

        with engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={"compare_type": True})
            differences = compare_metadata(context, Base.metadata)
        assert differences == [], f"Models and migrations disagree: {differences}"

        command.downgrade(config, "base")

        remaining = set(inspect(engine).get_table_names()) - {"alembic_version", "sqlite_sequence"}
        assert remaining == set()
    finally:
        engine.dispose()
