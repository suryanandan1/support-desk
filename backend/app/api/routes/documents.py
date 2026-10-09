from typing import Annotated

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status

from app.api.dependencies import AdminUser, ClientIp, DbSession
from app.core.config import get_settings
from app.core.exceptions import BusinessRuleError
from app.models.document import Document
from app.schemas.common import ErrorResponse, Page, PageParams
from app.schemas.document import (
    ChunkRead,
    DocumentListParams,
    DocumentRead,
    IndexStatusRead,
    ReindexAllResult,
    UploadResult,
)
from app.services import document_service

router = APIRouter(
    prefix="/documents",
    tags=["Knowledge base (admin)"],
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Admins only"},
    },
)


@router.post("/upload", response_model=UploadResult, status_code=status.HTTP_201_CREATED)
def upload_documents(
    files: Annotated[list[UploadFile], File(description="PDF, DOCX, TXT or MD files")],
    db: DbSession,
    admin: AdminUser,
    ip_address: ClientIp,
    category: Annotated[str | None, Form(max_length=50)] = None,
) -> UploadResult:
    """Upload one or more files. Each is validated separately; accepted files are
    queued for processing and their status can be polled with GET /documents/{id}."""
    settings = get_settings()
    if len(files) > settings.max_files_per_upload:
        raise BusinessRuleError(f"Upload at most {settings.max_files_per_upload} files at a time.")
    limit = settings.max_upload_size_bytes
    # Read one byte past the limit so oversized files are detected without reading them fully.
    payload = [(upload.filename, upload.file.read(limit + 1)) for upload in files]
    return document_service.upload_documents(
        db, files=payload, category=category, actor=admin, ip_address=ip_address
    )


@router.get("", response_model=Page[DocumentRead])
def list_documents(
    params: Annotated[DocumentListParams, Query()], db: DbSession, _admin: AdminUser
) -> Page[DocumentRead]:
    return document_service.list_documents(db, params)


@router.get("/index-status", response_model=IndexStatusRead)
def index_status(db: DbSession, _admin: AdminUser) -> IndexStatusRead:
    return document_service.index_status(db)


@router.post("/reindex", response_model=ReindexAllResult, status_code=status.HTTP_202_ACCEPTED)
def rebuild_index(db: DbSession, admin: AdminUser, ip_address: ClientIp) -> ReindexAllResult:
    """Rebuild the whole search index (needed after changing the embedding model)."""
    return ReindexAllResult(queued=document_service.rebuild_index(db, actor=admin, ip_address=ip_address))


@router.get("/{document_id}", response_model=DocumentRead, responses={404: {"model": ErrorResponse}})
def get_document(document_id: int, db: DbSession, _admin: AdminUser) -> Document:
    return document_service.get_document(db, document_id)


@router.get("/{document_id}/chunks", response_model=Page[ChunkRead])
def list_chunks(
    document_id: int, params: Annotated[PageParams, Query()], db: DbSession, _admin: AdminUser
) -> Page[ChunkRead]:
    return document_service.list_chunks(db, document_id, params)


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def delete_document(document_id: int, db: DbSession, admin: AdminUser, ip_address: ClientIp) -> Response:
    document_service.delete_document(db, document_id=document_id, actor=admin, ip_address=ip_address)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{document_id}/reindex",
    response_model=DocumentRead,
    status_code=status.HTTP_202_ACCEPTED,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def reindex_document(document_id: int, db: DbSession, admin: AdminUser, ip_address: ClientIp) -> Document:
    return document_service.reindex_document(
        db, document_id=document_id, actor=admin, ip_address=ip_address
    )
