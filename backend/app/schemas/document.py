from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.document import DocumentStatus
from app.schemas.common import PageParams


class UserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    original_filename: str
    file_extension: str
    content_type: str | None
    size_bytes: int
    category: str | None
    status: DocumentStatus
    error_message: str | None
    page_count: int | None
    chunk_count: int
    index_version: int
    embedding_model: str | None
    indexed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    uploaded_by: UserSummary | None


class UploadError(BaseModel):
    filename: str
    code: str = Field(examples=["duplicate"])
    message: str


class UploadResult(BaseModel):
    """Files are validated one by one: valid files are accepted even if others fail."""

    documents: list[DocumentRead]
    errors: list[UploadError]


class DocumentListParams(PageParams):
    status: DocumentStatus | None = None
    category: str | None = Field(default=None, max_length=50)
    search: str | None = Field(default=None, max_length=100)


class ChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    chunk_index: int
    content: str
    page_number: int | None
    section: str | None
    char_start: int
    char_end: int


class IndexStatusRead(BaseModel):
    vector_count: int
    index_signature: str | None
    expected_signature: str
    needs_rebuild: bool = Field(description="True if the index was built with another embedding model")
    updated_at: str | None
    document_counts: dict[str, int]
    categories: list[str]


class ReindexAllResult(BaseModel):
    queued: int
