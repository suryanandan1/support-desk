"""FastAPI application factory.

Run locally from the backend/ folder:
    uvicorn app.main:app --reload
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.error_handlers import register_exception_handlers
from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.api.middleware import request_context_middleware, upload_size_limit_middleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.vector_index_dir.mkdir(parents=True, exist_ok=True)
    if settings.llm_provider == "gemini" and not (
        settings.gemini_api_key and settings.gemini_api_key.get_secret_value().strip()
    ):
        logger.warning("GEMINI_API_KEY is not set; AI answers will be unavailable")
    logger.info("Started %s (%s)", settings.app_name, settings.environment)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json)

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="AI-powered customer support with RAG answers and human escalation.",
        lifespan=lifespan,
    )
    app.middleware("http")(upload_size_limit_middleware)
    app.middleware("http")(request_context_middleware)
    # Added last, so it is the outermost middleware and also covers error responses.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    register_exception_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
