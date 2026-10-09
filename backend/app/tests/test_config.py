"""Settings validation. Each test builds Settings directly, ignoring the .env file."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import BACKEND_DIR, PLACEHOLDER_SECRET, Settings

GOOD_SECRET = "a-perfectly-fine-secret-key-of-48-characters-xx"


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{"secret_key": GOOD_SECRET, **overrides})


def test_placeholder_secret_key_is_rejected():
    with pytest.raises(ValidationError, match="placeholder"):
        make_settings(secret_key=PLACEHOLDER_SECRET)


def test_short_secret_key_is_rejected():
    with pytest.raises(ValidationError, match="at least 32"):
        make_settings(secret_key="too-short")


def test_chunk_overlap_must_be_smaller_than_chunk_size():
    with pytest.raises(ValidationError, match="CHUNK_OVERLAP"):
        make_settings(chunk_size=500, chunk_overlap=500)


def test_escalation_threshold_cannot_be_below_retrieval_threshold():
    with pytest.raises(ValidationError, match="ESCALATION_MIN_TOP_SCORE"):
        make_settings(retrieval_min_score=0.6, escalation_min_top_score=0.5)


def test_comma_separated_lists_are_parsed():
    settings = make_settings(
        cors_origins="http://localhost:5173/, http://127.0.0.1:5173",
        allowed_upload_extensions="PDF, .Docx,txt",
    )

    assert settings.cors_origins == ["http://localhost:5173", "http://127.0.0.1:5173"]
    assert settings.allowed_upload_extensions == [".pdf", ".docx", ".txt"]


def test_relative_paths_resolve_inside_backend_folder():
    settings = make_settings(database_url="sqlite:///./data/app.db", upload_dir="./files")

    assert settings.database_url == "sqlite:///" + (BACKEND_DIR / "data" / "app.db").as_posix()
    assert settings.upload_dir == (BACKEND_DIR / "files").resolve()


@pytest.mark.parametrize(
    "url",
    ["sqlite://", "sqlite:///:memory:", "postgresql+psycopg://u:p@localhost:5432/support"],
)
def test_non_relative_database_urls_are_left_alone(url):
    assert make_settings(database_url=url).database_url == url


def test_absolute_sqlite_path_is_left_alone(tmp_path: Path):
    url = f"sqlite:///{(tmp_path / 'x.db').as_posix()}"

    assert make_settings(database_url=url).database_url == url
