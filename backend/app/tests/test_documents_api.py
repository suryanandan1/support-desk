"""Knowledge-base API: upload validation, ingestion, listing, deletion, re-indexing."""

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.models.audit_log import AuditLog
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.models.user import UserRole
from app.rag.embeddings import get_embedding_provider
from app.rag.vector_store import get_vector_store
from app.tests.factories import make_docx, make_pdf

UPLOAD = "/api/v1/documents/upload"
DOCS = "/api/v1/documents"

REFUND_MD = b"""# Refund Policy
Refunds are available within 30 days of delivery for unused items.

## Processing time
Approved refunds are returned to the original payment method within 5-7 business days.
"""


def _upload(client, headers, *files, category=None):
    data = {"category": category} if category else None
    return client.post(UPLOAD, files=[("files", f) for f in files], data=data, headers=headers)


def _search(text: str, k: int = 5) -> list[int]:
    provider = get_embedding_provider()
    return [cid for cid, _ in get_vector_store().search(provider.embed_query(text), k, provider.signature)]


@pytest.fixture
def admin_headers(admin, auth_headers):
    return auth_headers(admin)


# --------------------------------------------------------------------------- permissions


@pytest.mark.parametrize("role", [UserRole.CUSTOMER, UserRole.AGENT])
def test_only_admins_can_manage_documents(client, make_user, auth_headers, role):
    headers = auth_headers(make_user(role))

    assert _upload(client, headers, ("a.md", REFUND_MD)).status_code == 403
    assert client.get(DOCS, headers=headers).status_code == 403
    assert client.post(f"{DOCS}/reindex", headers=headers).status_code == 403


# --------------------------------------------------------------------------- upload + ingestion


def test_upload_indexes_the_document_end_to_end(client, db, admin_headers):
    response = _upload(client, admin_headers, ("refund_policy.md", REFUND_MD, "text/markdown"), category="Billing")

    assert response.status_code == 201
    body = response.json()
    assert body["errors"] == []
    document = body["documents"][0]
    assert document["original_filename"] == "refund_policy.md"
    assert document["category"] == "billing"
    assert document["status"] == "indexed"  # the test runs Celery tasks eagerly
    assert document["chunk_count"] == 2
    assert document["index_version"] == 1
    assert document["embedding_model"] == get_embedding_provider().signature
    assert document["uploaded_by"]["full_name"]

    chunks = db.scalars(select(DocumentChunk).order_by(DocumentChunk.chunk_index)).all()
    assert [c.section for c in chunks] == ["Refund Policy", "Refund Policy > Processing time"]
    # The best search hit for a refund-timing question is the processing-time chunk.
    assert _search("how many business days until my refund arrives")[0] == chunks[1].id


def test_pdf_and_docx_uploads_are_supported(client, db, admin_headers):
    pdf = make_pdf(["Warranty covers defects for one year.", "Claims need a receipt."])
    word = make_docx([("h1", "Accounts"), ("p", "Reset your password from the login page.")])

    response = _upload(client, admin_headers, ("warranty.pdf", pdf), ("accounts.docx", word))

    assert response.status_code == 201
    statuses = {d["original_filename"]: (d["status"], d["page_count"]) for d in response.json()["documents"]}
    assert statuses == {"warranty.pdf": ("indexed", 2), "accounts.docx": ("indexed", None)}
    pages = set(db.scalars(select(DocumentChunk.page_number).where(DocumentChunk.page_number.is_not(None))))
    assert pages == {1, 2}


def test_each_file_is_validated_separately(client, admin_headers):
    response = _upload(
        client,
        admin_headers,
        ("good.md", REFUND_MD),
        ("virus.exe", b"MZ\x90\x00"),
        ("fake.pdf", b"this is plain text pretending to be a pdf"),
        ("empty.txt", b""),
        ("binary.txt", b"\x00\x01\x02 binary"),
    )

    assert response.status_code == 201
    body = response.json()
    assert [d["original_filename"] for d in body["documents"]] == ["good.md"]
    assert {e["filename"]: e["code"] for e in body["errors"]} == {
        "virus.exe": "unsupported_type",
        "fake.pdf": "content_mismatch",
        "empty.txt": "empty_file",
        "binary.txt": "content_mismatch",
    }


def test_oversized_files_are_rejected(client, admin_headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_size_mb", 1)

    response = _upload(client, admin_headers, ("big.txt", b"a" * (1024 * 1024 + 1)))

    assert response.json()["errors"][0]["code"] == "file_too_large"


def test_oversized_requests_are_rejected_before_reading_the_body(client, admin_headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_size_mb", 1)
    monkeypatch.setattr(get_settings(), "max_files_per_upload", 1)

    response = _upload(client, admin_headers, ("huge.txt", b"a" * (3 * 1024 * 1024)))

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_too_many_files_in_one_request(client, admin_headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_files_per_upload", 2)

    response = _upload(client, admin_headers, ("a.md", b"# A\ntext a"), ("b.md", b"# B\ntext b"), ("c.md", b"# C\ntext c"))

    assert response.status_code == 400


def test_duplicate_files_are_detected(client, db, admin_headers):
    _upload(client, admin_headers, ("refund_policy.md", REFUND_MD))

    again = _upload(client, admin_headers, ("copy-of-refund.md", REFUND_MD))
    twice_in_batch = _upload(client, admin_headers, ("x.md", b"# X\nnew text"), ("y.md", b"# X\nnew text"))

    assert again.json()["errors"][0]["code"] == "duplicate"
    assert "refund_policy.md" in again.json()["errors"][0]["message"]
    assert [e["code"] for e in twice_in_batch.json()["errors"]] == ["duplicate"]
    assert db.scalar(select(func.count()).select_from(Document)) == 2


def test_filenames_cannot_escape_the_upload_folder(client, db, admin_headers):
    response = _upload(client, admin_headers, ("../../../etc/evil.md", REFUND_MD))

    document = db.get(Document, response.json()["documents"][0]["id"])
    assert document.original_filename == "evil.md"
    assert ".." not in document.stored_filename and "/" not in document.stored_filename
    assert (get_settings().upload_dir / document.stored_filename).is_file()


def test_unreadable_documents_are_marked_failed_with_a_reason(client, admin_headers):
    response = _upload(client, admin_headers, ("scan.pdf", make_pdf([""])))

    document = response.json()["documents"][0]
    assert document["status"] == "failed"
    assert "Scanned PDFs" in document["error_message"]


def test_queue_outage_marks_the_document_failed_with_instructions(client, admin_headers, monkeypatch):
    from kombu.exceptions import OperationalError

    from app.tasks import document_tasks

    attempts = []

    def broker_down(*_args, **_kwargs):
        attempts.append(1)
        raise OperationalError("Error 10061 connecting to localhost:6379")

    monkeypatch.setattr(document_tasks.ingest_document_task, "apply_async", broker_down)

    documents = _upload(client, admin_headers, ("a.md", REFUND_MD), ("b.md", b"# B\nOther text.")).json()["documents"]

    assert [d["status"] for d in documents] == ["failed", "failed"]
    assert all("Memurai" in d["error_message"] for d in documents)
    # Each attempt waits for a connection timeout, so the second file is not retried.
    assert len(attempts) == 1


def test_uploads_are_audited(client, db, admin, admin_headers):
    _upload(client, admin_headers, ("a.md", REFUND_MD))

    entry = db.scalar(select(AuditLog).where(AuditLog.action == "document.uploaded"))
    assert entry.actor_id == admin.id
    assert entry.details["filename"] == "a.md"


# --------------------------------------------------------------------------- listing


def test_list_filters_and_paginates(client, admin_headers):
    _upload(client, admin_headers, ("refunds.md", REFUND_MD), category="billing")
    _upload(client, admin_headers, ("shipping.md", b"# Shipping\nWe ship worldwide in 5 days."), category="shipping")
    _upload(client, admin_headers, ("scan.pdf", make_pdf([""])))

    everything = client.get(DOCS, headers=admin_headers).json()
    failed = client.get(DOCS, params={"status": "failed"}, headers=admin_headers).json()
    billing = client.get(DOCS, params={"category": "Billing"}, headers=admin_headers).json()
    search = client.get(DOCS, params={"search": "ship"}, headers=admin_headers).json()
    page = client.get(DOCS, params={"page_size": 2, "page": 2}, headers=admin_headers).json()

    assert everything["total"] == 3
    assert [d["original_filename"] for d in failed["items"]] == ["scan.pdf"]
    assert [d["original_filename"] for d in billing["items"]] == ["refunds.md"]
    assert [d["original_filename"] for d in search["items"]] == ["shipping.md"]
    assert len(page["items"]) == 1 and page["pages"] == 2


def test_get_document_and_its_chunks(client, admin_headers):
    document_id = _upload(client, admin_headers, ("refunds.md", REFUND_MD)).json()["documents"][0]["id"]

    single = client.get(f"{DOCS}/{document_id}", headers=admin_headers)
    chunks = client.get(f"{DOCS}/{document_id}/chunks", headers=admin_headers).json()

    assert single.json()["id"] == document_id
    assert chunks["total"] == 2
    assert chunks["items"][1]["section"] == "Refund Policy > Processing time"
    assert client.get(f"{DOCS}/9999", headers=admin_headers).status_code == 404


def test_index_status_reports_counts_and_model(client, admin_headers):
    _upload(client, admin_headers, ("refunds.md", REFUND_MD), category="billing")

    status = client.get(f"{DOCS}/index-status", headers=admin_headers).json()

    assert status["vector_count"] == 2
    assert status["index_signature"] == status["expected_signature"]
    assert status["needs_rebuild"] is False
    assert status["document_counts"]["indexed"] == 1
    assert status["categories"] == ["billing"]


# --------------------------------------------------------------------------- delete + reindex


def test_delete_removes_file_chunks_and_vectors(client, db, admin_headers):
    document_id = _upload(client, admin_headers, ("refunds.md", REFUND_MD)).json()["documents"][0]["id"]
    stored = get_settings().upload_dir / db.get(Document, document_id).stored_filename
    assert _search("refund processing time")

    response = client.delete(f"{DOCS}/{document_id}", headers=admin_headers)

    assert response.status_code == 204
    db.expire_all()
    assert db.get(Document, document_id) is None
    assert db.scalar(select(func.count()).select_from(DocumentChunk)) == 0
    assert _search("refund processing time") == []
    assert not stored.exists()
    assert db.scalar(select(AuditLog).where(AuditLog.action == "document.deleted")) is not None


def test_documents_being_processed_cannot_be_deleted(client, db, admin_headers):
    document_id = _upload(client, admin_headers, ("refunds.md", REFUND_MD)).json()["documents"][0]["id"]
    db.get(Document, document_id).status = DocumentStatus.PROCESSING
    db.commit()

    assert client.delete(f"{DOCS}/{document_id}", headers=admin_headers).status_code == 409


def test_reindex_replaces_chunks_and_bumps_the_version(client, db, admin_headers):
    document_id = _upload(client, admin_headers, ("refunds.md", REFUND_MD)).json()["documents"][0]["id"]
    old_ids = set(db.scalars(select(DocumentChunk.id)))

    response = client.post(f"{DOCS}/{document_id}/reindex", headers=admin_headers)

    assert response.status_code == 202
    assert response.json()["status"] == "indexed"
    assert response.json()["index_version"] == 2
    db.expire_all()
    new_ids = set(db.scalars(select(DocumentChunk.id)))
    assert new_ids and not (new_ids & old_ids)  # ids are never reused
    assert set(_search("refund processing time")) <= new_ids


def test_rebuild_index_reingests_every_document(client, admin_headers):
    _upload(client, admin_headers, ("refunds.md", REFUND_MD), ("shipping.md", b"# Shipping\nWe ship in 5 days."))

    response = client.post(f"{DOCS}/reindex", headers=admin_headers)

    assert response.status_code == 202
    assert response.json() == {"queued": 2}
    listing = client.get(DOCS, headers=admin_headers).json()["items"]
    assert {d["status"] for d in listing} == {"indexed"}
    assert get_vector_store().status().vector_count == 3
