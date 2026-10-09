"""Uploaded-file validation and storage on local disk.

Files are saved under UPLOAD_DIR with random names; the user's filename is only ever
used for display. That rules out path traversal ("../../x") and name collisions.
"""

import re
import uuid
import zipfile
from io import BytesIO
from pathlib import Path, PurePosixPath, PureWindowsPath

from app.core.config import get_settings

_UNSAFE_NAME_CHARS = re.compile(r"[\x00-\x1f\x7f<>:\"|?*]")
MAX_DISPLAY_NAME_LENGTH = 200


class UploadRejected(Exception):
    """A file failed validation. ``code`` is machine-readable, ``message`` is for people."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def safe_display_name(filename: str | None) -> str:
    """Strip directories and unsafe characters from a client-supplied filename."""
    name = PureWindowsPath(PurePosixPath(filename or "").name).name
    name = _UNSAFE_NAME_CHARS.sub("", name)
    name = " ".join(name.split()).strip(" .")
    if not name:
        return "document"
    if len(name) > MAX_DISPLAY_NAME_LENGTH:
        suffix = Path(name).suffix[:10]
        name = name[: MAX_DISPLAY_NAME_LENGTH - len(suffix)] + suffix
    return name


def _looks_like(extension: str, data: bytes) -> bool:
    """Check the file content matches its extension (a renamed .exe is not a PDF)."""
    if extension == ".pdf":
        return b"%PDF-" in data[:1024]
    if extension == ".docx":
        try:
            with zipfile.ZipFile(BytesIO(data)) as archive:
                return "word/document.xml" in archive.namelist()
        except zipfile.BadZipFile:
            return False
    if extension in (".txt", ".md"):
        if b"\x00" in data[:8192]:
            return False  # binary content
        try:
            data.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                data.decode("cp1252")
            except UnicodeDecodeError:
                return False
        return True
    return False


def validate_upload(filename: str | None, data: bytes) -> tuple[str, str]:
    """Return ``(display_name, extension)`` or raise UploadRejected."""
    settings = get_settings()
    name = safe_display_name(filename)
    extension = Path(name).suffix.lower()
    allowed = settings.allowed_upload_extensions
    if extension not in allowed:
        raise UploadRejected(
            "unsupported_type", f"Unsupported file type. Allowed types: {', '.join(allowed)}."
        )
    if not data:
        raise UploadRejected("empty_file", "The file is empty.")
    if len(data) > settings.max_upload_size_bytes:
        raise UploadRejected(
            "file_too_large", f"The file is larger than {settings.max_upload_size_mb} MB."
        )
    if not _looks_like(extension, data):
        raise UploadRejected(
            "content_mismatch", f"The file content is not a valid {extension} file."
        )
    return name, extension


def stored_file_path(stored_filename: str) -> Path:
    upload_dir = get_settings().upload_dir.resolve()
    path = (upload_dir / stored_filename).resolve()
    if not path.is_relative_to(upload_dir):
        raise ValueError("Stored file path escapes the upload directory")
    return path


def save_file(data: bytes, extension: str) -> str:
    """Write ``data`` under UPLOAD_DIR and return the generated stored filename."""
    upload_dir = get_settings().upload_dir
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_filename = f"{uuid.uuid4().hex}{extension}"
    path = stored_file_path(stored_filename)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_bytes(data)
    temporary.replace(path)
    return stored_filename


def delete_file(stored_filename: str) -> None:
    try:
        stored_file_path(stored_filename).unlink(missing_ok=True)
    except (OSError, ValueError):
        pass  # already gone or unreachable; nothing useful to do
