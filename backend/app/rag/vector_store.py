"""Persistent FAISS index of chunk vectors.

* Vector ids are document_chunks.id, so a search hit maps straight to a database row.
* The index lives in VECTOR_INDEX_DIR as index.faiss plus index_meta.json, which
  records the embedding "signature" (provider:model:dimensions). Searching with a
  different embedding model is refused instead of returning nonsense.
* The API process and the Celery worker may both write. Writers hold a file lock,
  re-read the latest index from disk, change it, and atomically replace the file.
  Readers reload automatically when the file on disk is newer than their copy.

Recovery: if the files are lost or corrupted, delete them and run
``python scripts/rebuild_index.py`` (or "Rebuild index" in the admin UI); every
document is re-embedded from the files stored in UPLOAD_DIR.
"""

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import faiss
import numpy as np
from filelock import FileLock

from app.core.config import get_settings

logger = logging.getLogger(__name__)

INDEX_FILE = "index.faiss"
META_FILE = "index_meta.json"
LOCK_FILE = "index.lock"


class VectorStoreError(Exception):
    """The index cannot be read or written. The message is safe to show to admins."""


class VectorIndexMismatchError(VectorStoreError):
    """The index was built with a different embedding model or dimension."""


@dataclass
class IndexStatus:
    exists: bool
    vector_count: int
    signature: str | None
    updated_at: str | None


def _replace_with_retry(source: Path, target: Path, attempts: int = 5) -> None:
    # On Windows, replacing a file that another process is reading at that instant
    # fails with PermissionError; a short retry is enough.
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.05 * (attempt + 1))


class FaissVectorStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.index_path = directory / INDEX_FILE
        self.meta_path = directory / META_FILE
        self._file_lock = FileLock(str(directory / LOCK_FILE), timeout=60)
        self._thread_lock = threading.RLock()
        self._index: faiss.Index | None = None
        self._signature: str | None = None
        self._loaded_stamp: tuple[int, int] | None = None

    # ------------------------------------------------------------------ disk I/O

    def _read_meta(self) -> dict:
        try:
            return json.loads(self.meta_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            raise VectorStoreError("The vector index metadata file is unreadable.") from exc

    def _reload_if_changed(self) -> None:
        """Bring the in-memory copy up to date with the file on disk."""
        try:
            stat = self.index_path.stat()
        except FileNotFoundError:
            self._index, self._signature, self._loaded_stamp = None, None, None
            return
        stamp = (stat.st_mtime_ns, stat.st_size)
        if self._index is not None and stamp == self._loaded_stamp:
            return
        try:
            data = np.frombuffer(self.index_path.read_bytes(), dtype=np.uint8)
            index = faiss.deserialize_index(data)
        except Exception as exc:  # noqa: BLE001 - FAISS raises RuntimeError subclasses
            raise VectorStoreError(
                "The vector index file is corrupted. Rebuild the index from the admin page "
                "or with scripts/rebuild_index.py."
            ) from exc
        self._index = index
        self._signature = self._read_meta().get("signature")
        self._loaded_stamp = stamp

    def _write(self, index: faiss.Index, signature: str) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.index_path.with_suffix(".faiss.tmp")
        temporary.write_bytes(faiss.serialize_index(index).tobytes())
        _replace_with_retry(temporary, self.index_path)
        meta = {
            "signature": signature,
            "vector_count": int(index.ntotal),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        meta_temporary = self.meta_path.with_suffix(".json.tmp")
        meta_temporary.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        _replace_with_retry(meta_temporary, self.meta_path)
        self._index = index
        self._signature = signature
        stat = self.index_path.stat()
        self._loaded_stamp = (stat.st_mtime_ns, stat.st_size)

    @staticmethod
    def _new_index(dimensions: int) -> faiss.Index:
        # Inner product on unit vectors == cosine similarity. IDMap2 supports removal.
        return faiss.IndexIDMap2(faiss.IndexFlatIP(dimensions))

    def _check_signature(self, signature: str) -> None:
        if self._index is not None and self._signature != signature:
            raise VectorIndexMismatchError(
                f"The search index was built with '{self._signature}' but the current "
                f"embedding model is '{signature}'. Rebuild the index to search again."
            )

    # ------------------------------------------------------------------ public API

    def search(self, vector: np.ndarray, k: int, signature: str) -> list[tuple[int, float]]:
        """Return up to ``k`` (chunk_id, similarity) pairs, best first."""
        with self._thread_lock:
            self._reload_if_changed()
            if self._index is None or self._index.ntotal == 0:
                return []
            self._check_signature(signature)
            query = np.asarray(vector, dtype=np.float32).reshape(1, -1)
            if query.shape[1] != self._index.d:
                raise VectorIndexMismatchError("Query vector size does not match the index.")
            scores, ids = self._index.search(query, min(k, int(self._index.ntotal)))
        return [(int(i), float(s)) for i, s in zip(ids[0], scores[0], strict=True) if i != -1]

    def replace(
        self,
        *,
        remove_ids: list[int],
        add_ids: list[int],
        vectors: np.ndarray,
        signature: str,
    ) -> None:
        """Atomically remove some vectors and add others (used to (re)index a document)."""
        vectors = np.asarray(vectors, dtype=np.float32)
        if len(add_ids) != len(vectors):
            raise ValueError("add_ids and vectors must have the same length")
        with self._file_lock, self._thread_lock:
            self._reload_if_changed()
            if self._index is None:
                if not len(vectors):
                    return
                index = self._new_index(vectors.shape[1])
            else:
                self._check_signature(signature)
                index = self._index
                if len(vectors) and vectors.shape[1] != index.d:
                    raise VectorIndexMismatchError("Vector size does not match the index.")
            if remove_ids:
                index.remove_ids(np.asarray(remove_ids, dtype=np.int64))
            if len(add_ids):
                index.add_with_ids(vectors, np.asarray(add_ids, dtype=np.int64))
            self._write(index, signature)

    def remove(self, ids: list[int]) -> None:
        if not ids:
            return
        with self._file_lock, self._thread_lock:
            self._reload_if_changed()
            if self._index is None:
                return
            self._index.remove_ids(np.asarray(ids, dtype=np.int64))
            self._write(self._index, self._signature or "")

    def reset(self, signature: str, dimensions: int) -> None:
        """Start an empty index (e.g. after switching embedding models)."""
        with self._file_lock, self._thread_lock:
            self._write(self._new_index(dimensions), signature)

    def status(self) -> IndexStatus:
        with self._thread_lock:
            try:
                self._reload_if_changed()
            except VectorStoreError:
                return IndexStatus(exists=True, vector_count=0, signature=None, updated_at=None)
            meta = self._read_meta() if self._index is not None else {}
            return IndexStatus(
                exists=self._index is not None,
                vector_count=int(self._index.ntotal) if self._index is not None else 0,
                signature=self._signature,
                updated_at=meta.get("updated_at"),
            )


@lru_cache
def get_vector_store() -> FaissVectorStore:
    directory = get_settings().vector_index_dir
    directory.mkdir(parents=True, exist_ok=True)
    return FaissVectorStore(directory)
