"""Shared pytest fixtures.

Environment variables are set before any app module is imported, so the suite never
touches the development database, real API keys, or real storage folders.
"""

import itertools
import os
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path

_TEST_ROOT = Path(tempfile.mkdtemp(prefix="support-tests-"))
os.environ.update(
    {
        "APP_ENV_FILE": "none",  # never read the developer's backend/.env
        "ENVIRONMENT": "test",
        "SECRET_KEY": "test-secret-key-that-is-long-enough-for-hs256-0123456789",
        "ACCESS_TOKEN_EXPIRE_MINUTES": "60",
        "DATABASE_URL": f"sqlite:///{(_TEST_ROOT / 'unused.db').as_posix()}",
        "LLM_PROVIDER": "demo",
        "EMBEDDING_PROVIDER": "local",
        "GEMINI_API_KEY": "unused-in-tests",
        "CELERY_TASK_ALWAYS_EAGER": "true",
        "LLM_RETRY_BASE_DELAY_SECONDS": "0",
        "UPLOAD_DIR": str(_TEST_ROOT / "uploads"),
        "VECTOR_INDEX_DIR": str(_TEST_ROOT / "vector_index"),
        "LOG_LEVEL": "WARNING",
        "LOG_JSON": "false",
    }
)

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

import app.models  # noqa: E402,F401
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.session import SessionLocal, build_engine, get_db  # noqa: E402
from app.rag.embeddings import get_embedding_provider  # noqa: E402
from app.rag.vector_store import get_vector_store  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402

TEST_PASSWORD = "Password123"
_TEST_PASSWORD_HASH = hash_password(TEST_PASSWORD)  # Argon2 is slow on purpose; hash once.


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """A fresh SQLite database file per test (same engine setup as production)."""
    test_engine = build_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    Base.metadata.create_all(test_engine)
    # Code that opens its own sessions (Celery tasks, scripts) uses this database too.
    SessionLocal.configure(bind=test_engine)
    yield test_engine
    test_engine.dispose()


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Give every test its own upload folder and vector index."""
    settings = get_settings()
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "vector_index_dir", tmp_path / "vector_index")
    get_vector_store.cache_clear()
    get_embedding_provider.cache_clear()
    yield
    get_vector_store.cache_clear()
    get_embedding_provider.cache_clear()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def db(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """A session for arranging data and asserting on it.

    The API uses its own sessions, so call ``db.expire_all()`` before re-reading rows
    the API may have changed.
    """
    with session_factory() as session:
        yield session


@pytest.fixture
def app(session_factory: sessionmaker[Session]) -> FastAPI:
    application = create_app()

    def override_get_db() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    application.dependency_overrides[get_db] = override_get_db
    return application


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def make_user(db: Session) -> Callable[..., User]:
    counter = itertools.count(1)

    def _make_user(
        role: UserRole = UserRole.CUSTOMER,
        *,
        email: str | None = None,
        password: str = TEST_PASSWORD,
        is_active: bool = True,
        full_name: str | None = None,
    ) -> User:
        n = next(counter)
        user = User(
            email=email or f"{role.value}{n}@example.com",
            full_name=full_name or f"Test {role.value.title()} {n}",
            hashed_password=_TEST_PASSWORD_HASH if password == TEST_PASSWORD else hash_password(password),
            role=role,
            is_active=is_active,
        )
        db.add(user)
        db.commit()
        return user

    return _make_user


@pytest.fixture
def customer(make_user: Callable[..., User]) -> User:
    return make_user(UserRole.CUSTOMER)


@pytest.fixture
def agent(make_user: Callable[..., User]) -> User:
    return make_user(UserRole.AGENT)


@pytest.fixture
def admin(make_user: Callable[..., User]) -> User:
    return make_user(UserRole.ADMIN)


@pytest.fixture
def auth_headers() -> Callable[[User], dict[str, str]]:
    def _auth_headers(user: User) -> dict[str, str]:
        token, _ = create_access_token(user.id, user.role.value)
        return {"Authorization": f"Bearer {token}"}

    return _auth_headers
