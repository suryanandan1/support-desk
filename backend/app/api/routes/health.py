import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import DbSession

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])


@router.get("/health")
def health(db: DbSession) -> JSONResponse:
    """Liveness plus a database round-trip. Returns 503 if the database is unreachable."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("Health check: database unavailable")
        return JSONResponse(status_code=503, content={"status": "degraded", "database": "unavailable"})
    return JSONResponse(content={"status": "ok", "database": "ok"})
