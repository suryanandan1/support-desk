"""Application settings, loaded from environment variables and the backend/.env file.

Every tunable value lives here so nothing environment-specific is hardcoded elsewhere.
Use ``get_settings()`` everywhere instead of instantiating ``Settings`` directly.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# backend/ directory. Relative paths in settings are resolved against it so the app
# behaves the same no matter which folder a command is launched from.
BACKEND_DIR = Path(__file__).resolve().parents[2]

PLACEHOLDER_SECRET = "replace-me-with-a-long-random-string"

# Which .env file to read. Tests and the offline evaluation set APP_ENV_FILE=none so a
# developer's local settings can never change their results.
_ENV_FILE_SETTING = os.environ.get("APP_ENV_FILE", str(BACKEND_DIR / ".env"))
ENV_FILE = None if _ENV_FILE_SETTING.lower() == "none" else _ENV_FILE_SETTING


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        # "RETRIEVAL_MIN_SCORE=" in .env means "not set", not an empty string.
        env_ignore_empty=True,
    )

    # ---- Application ----
    app_name: str = "AI Customer Support"
    environment: Literal["development", "production", "test"] = "development"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_json: bool = False

    # ---- Security ----
    secret_key: SecretStr
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_expire_minutes: int = Field(default=60, ge=1, le=24 * 60)

    # ---- Database ----
    database_url: str = "sqlite:///./support.db"

    # ---- CORS ----
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    # ---- AI providers ----
    # "demo" answers by quoting the retrieved passages, with no LLM (offline, no key).
    llm_provider: Literal["gemini", "demo"] = "gemini"
    # "local" uses offline hashed word features instead of a neural embedding model.
    embedding_provider: Literal["gemini", "local"] = "gemini"
    gemini_api_key: SecretStr | None = None
    gemini_chat_model: str = "gemini-flash-latest"
    gemini_embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = Field(default=768, ge=64, le=4096)
    embedding_batch_size: int = Field(default=50, ge=1, le=100)
    llm_temperature: float = Field(default=0.2, ge=0, le=1)
    llm_max_output_tokens: int = Field(default=2048, ge=64, le=8192)
    llm_timeout_seconds: float = Field(default=30, gt=0, le=300)
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    llm_retry_base_delay_seconds: float = Field(default=1.0, ge=0, le=30)

    # ---- File storage ----
    upload_dir: Path = Path("./storage/uploads")
    vector_index_dir: Path = Path("./storage/vector_index")
    max_upload_size_mb: int = Field(default=20, ge=1, le=200)
    max_files_per_upload: int = Field(default=20, ge=1, le=100)
    allowed_upload_extensions: Annotated[list[str], NoDecode] = [".pdf", ".docx", ".txt", ".md"]

    # ---- RAG pipeline ----
    chunk_size: int = Field(default=1000, ge=100, le=8000)
    chunk_overlap: int = Field(default=150, ge=0)
    retrieval_top_k: int = Field(default=5, ge=1, le=50)
    # Similarity scales differ between embedding models. Leave these unset to use the
    # embedding provider's own defaults; set them to override after calibrating with
    # scripts/evaluate_rag.py.
    retrieval_min_score: float | None = Field(default=None, ge=0, le=1)
    escalation_min_top_score: float | None = Field(default=None, ge=0, le=1)
    escalation_min_chunks: int = Field(default=1, ge=1)
    # Share of the question's key terms that must appear in the retrieved passages.
    escalation_min_coverage: float = Field(default=0.3, ge=0, le=1)
    chat_history_turns: int = Field(default=6, ge=0, le=20)
    max_question_length: int = Field(default=2000, ge=10, le=10000)

    # ---- Background jobs ----
    redis_url: str = "redis://localhost:6379/0"
    # Runs Celery tasks inside the calling process. For the automated tests only.
    celery_task_always_eager: bool = False

    # ------------------------------------------------------------------ validators

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        # Accept "http://a,http://b" from .env as well as a real list.
        if isinstance(value, str):
            return [item.strip().rstrip("/") for item in value.split(",") if item.strip()]
        return value

    @field_validator("allowed_upload_extensions", mode="before")
    @classmethod
    def _split_extensions(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.split(",")
        if isinstance(value, list):
            cleaned = [str(ext).strip().lower() for ext in value if str(ext).strip()]
            return [ext if ext.startswith(".") else f".{ext}" for ext in cleaned]
        return value

    @field_validator("secret_key")
    @classmethod
    def _check_secret_key(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if secret == PLACEHOLDER_SECRET:
            raise ValueError(
                "SECRET_KEY still has the placeholder value from .env.example. Generate one with: "
                "python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        if len(secret) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long")
        return value

    @model_validator(mode="after")
    def _check_consistency(self) -> "Settings":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
        if (
            self.escalation_min_top_score is not None
            and self.retrieval_min_score is not None
            and self.escalation_min_top_score < self.retrieval_min_score
        ):
            raise ValueError("ESCALATION_MIN_TOP_SCORE must be >= RETRIEVAL_MIN_SCORE")
        self.upload_dir = _resolve_path(self.upload_dir)
        self.vector_index_dir = _resolve_path(self.vector_index_dir)
        self.database_url = _resolve_sqlite_url(self.database_url)
        return self

    # ------------------------------------------------------------------ helpers

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


def _resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else (BACKEND_DIR / path).resolve()


def _resolve_sqlite_url(url: str) -> str:
    """Make ``sqlite:///./x.db`` point inside backend/ instead of the current directory."""
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return url
    raw_path = url[len(prefix):]
    if not raw_path or raw_path == ":memory:" or Path(raw_path).is_absolute():
        return url
    return prefix + _resolve_path(Path(raw_path)).as_posix()


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
