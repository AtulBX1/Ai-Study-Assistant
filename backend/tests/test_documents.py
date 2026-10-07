"""PDF upload, ingestion, ownership, and page retrieval tests."""

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf
import pytesseract
import pytest
from conftest import access_token_for
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.main import app
from app.models import Chunk, Document, DocumentPage, DocumentStatusEvent, User
from app.nlp.preprocessing import normalize_text
from app.routers.documents import (
    get_document_embedding_service,
    get_document_file_storage,
    get_document_job_queue,
    get_document_vector_store,
)
from app.services.document_ingestion import ingest_document
from app.services.file_storage import LocalFileStorage

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"


class RecordingQueue:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple[Any, ...]]] = []

    def enqueue(self, task_name: str, *args: Any, **kwargs: Any) -> None:
        self.jobs.append((task_name, args))


class NoopVectorStore:
    def __init__(self) -> None:
        self.deleted_documents: list[int] = []
        self.upserted: list[tuple[list[str], list[dict[str, Any]]]] = []

    def upsert(self, collection, ids, vectors, payloads=None) -> None:
        self.upserted.append((ids, payloads or []))

    def search(self, collection, vector, limit=5, user_id=None, document_ids=None):
        raise NotImplementedError

    def delete_ids(self, collection, ids) -> None:
        return None

    def delete_document(self, document_id: int) -> None:
        self.deleted_documents.append(document_id)


class FakeEmbeddingService:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


@dataclass
class DocumentTestContext:
    client: TestClient
    storage: LocalFileStorage
    queue: RecordingQueue
    vector_store: NoopVectorStore
    owner: User
    headers: dict[str, str]
    settings: Settings
    embedding_service: FakeEmbeddingService


@pytest.fixture
def document_context(
    client: TestClient, db_session, tmp_path: Path
) -> DocumentTestContext:
    storage = LocalFileStorage(tmp_path / "pdf-storage")
    queue = RecordingQueue()
    vector_store = NoopVectorStore()
    embedding_service = FakeEmbeddingService()
    settings = Settings(
        max_pdf_size_bytes=20 * 1024 * 1024,
        max_pdf_pages=500,
        page_image_cache_size=4,
    )
    owner = User(
        email="pdf-owner@example.com",
        full_name="PDF Owner",
        password_hash="unused",
    )
    db_session.add(owner)
    db_session.commit()
    overrides = {
        get_document_file_storage: lambda: storage,
        get_document_job_queue: lambda: queue,
        get_document_vector_store: lambda: vector_store,
        get_document_embedding_service: lambda: embedding_service,
        get_settings: lambda: settings,
    }
    app.dependency_overrides.update(overrides)
    context = DocumentTestContext(
        client=client,
        storage=storage,
        queue=queue,
        vector_store=vector_store,
        owner=owner,
        headers={"Authorization": f"Bearer {access_token_for(owner.id)}"},
        settings=settings,
        embedding_service=embedding_service,
    )
    yield context
    for dependency in overrides:
        app.dependency_overrides.pop(dependency, None)


def _sample(name: str) -> bytes:
    return (SAMPLES / name).read_bytes()


def _upload(
    context: DocumentTestContext,
    content: bytes | None = None,
    filename: str = "sample.pdf",
):
    return context.client.post(
        "/documents/upload",
        headers=context.headers,
        files={
            "file": (
                filename,
                content if content is not None else _sample("text.pdf"),
                "application/octet-stream",
            )
        },
    )


def _ingest(
    document_id: int,
    db_session,
    context: DocumentTestContext,
) -> None:
    ingest_document(
        document_id,
        db_session,
        context.storage,
        vector_store=context.vector_store,
        embedding_service=context.embedding_service,
    )


def _encrypted_pdf() -> bytes:
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Encrypted page")
    return pdf.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="owner-password",
        user_pw="user-password",
    )


def _two_page_pdf() -> bytes:
    pdf = pymupdf.open()
    pdf.new_page()
    pdf.new_page()
    return pdf.tobytes()


def test_upload_stores_pdf_safely_and_enqueues_ingestion(
    document_context: DocumentTestContext,
) -> None:
    response = _upload(
        document_context,
        filename=r"..\private\week-one notes.pdf",
    )

    assert response.status_code == 202
    document = response.json()
    assert document["status"] == "queued"
    assert document["progress"] == 0
    assert document["title"] == "week-one notes.pdf"
    assert document_context.queue.jobs == [("ingest_document", (document["id"],))]
    stored_key = document_context.client.get(
        f"/documents/{document['id']}/download",
        headers=document_context.headers,
    ).headers.get("content-disposition")
    assert stored_key == 'attachment; filename="week-one%20notes.pdf"'


def test_ingestion_tracks_stages_and_returns_page_text_and_image(
    document_context: DocumentTestContext,
    db_session,
) -> None:
    uploaded = _upload(document_context)
    document_id = uploaded.json()["id"]

    _ingest(document_id, db_session, document_context)

    status = document_context.client.get(
        f"/documents/{document_id}/status",
        headers=document_context.headers,
    )
    assert status.json()["status"] == "ready"
    assert status.json()["progress"] == 100
    stages = list(
        db_session.scalars(
            select(DocumentStatusEvent.status)
            .where(DocumentStatusEvent.document_id == document_id)
            .order_by(DocumentStatusEvent.id)
        )
    )
    assert stages[0] == "queued"
    assert {"extracting", "processing", "indexing", "ready"}.issubset(stages)
    indexed_chunk = db_session.scalar(select(Chunk).where(Chunk.doc_id == document_id))
    assert indexed_chunk is not None
    assert indexed_chunk.page_start == indexed_chunk.page_end == 1
    assert indexed_chunk.token_count > 0
    assert indexed_chunk.vector_id is not None
    assert document_context.vector_store.upserted
    payload = document_context.vector_store.upserted[-1][1][0]
    assert payload["user_id"] == document_context.owner.id
    assert payload["document_id"] == document_id
    assert payload["chunk_id"] == indexed_chunk.id
    assert payload["page"] == indexed_chunk.page
    assert payload["section"] == indexed_chunk.section

    page = document_context.client.get(
        f"/documents/{document_id}/pages/1",
        headers=document_context.headers,
    )
    assert page.status_code == 200
    assert "TF-IDF" in page.json()["text"]
    assert any(
        heading["text"] == "Text Processing" for heading in page.json()["headings"]
    )

    events = document_context.client.get(
        f"/documents/{document_id}/events",
        headers=document_context.headers,
    )
    assert events.status_code == 200
    assert events.headers["content-type"].startswith("text/event-stream")
    assert '"status": "ready"' in events.text

    image = document_context.client.get(
        f"/documents/{document_id}/pages/1/image",
        headers=document_context.headers,
    )
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert document_context.client.get(
        f"/documents/{document_id}/download",
        headers=document_context.headers,
    ).content == _sample("text.pdf")


def test_ingestion_extracts_structured_tables(
    document_context: DocumentTestContext,
    db_session,
) -> None:
    uploaded = _upload(document_context, _sample("tables.pdf"))
    document_id = uploaded.json()["id"]

    _ingest(document_id, db_session, document_context)

    page = db_session.scalar(
        select(DocumentPage).where(
            DocumentPage.document_id == document_id,
            DocumentPage.page_number == 1,
        )
    )
    assert page is not None
    assert page.tables
    assert "Module | Pages" in page.text
    assert page.cleaned_text == normalize_text(page.text)


def test_scanned_page_records_clear_marker_when_tesseract_is_unavailable(
    document_context: DocumentTestContext,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import document_ingestion

    def missing_tesseract(_page: pymupdf.Page) -> str:
        raise pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(document_ingestion, "_ocr_page", missing_tesseract)
    uploaded = _upload(document_context, _sample("scanned.pdf"))
    document_id = uploaded.json()["id"]

    _ingest(document_id, db_session, document_context)

    page = db_session.scalar(
        select(DocumentPage).where(DocumentPage.document_id == document_id)
    )
    assert page is not None
    assert page.ocr_status == "ocr_unavailable"
    assert db_session.get(Document, document_id).status == "ready"


@pytest.mark.skipif(
    shutil.which("tesseract") is None,
    reason="OCR integration skipped: Tesseract executable is not installed.",
)
def test_scanned_page_uses_installed_tesseract(
    document_context: DocumentTestContext,
    db_session,
) -> None:
    uploaded = _upload(document_context, _sample("scanned.pdf"))
    document_id = uploaded.json()["id"]

    _ingest(document_id, db_session, document_context)

    page = db_session.scalar(
        select(DocumentPage).where(DocumentPage.document_id == document_id)
    )
    assert page is not None
    assert page.ocr_status == "completed"
    assert "Scanned lecture notes" in page.text


def test_corrupt_and_encrypted_pdfs_are_rejected(
    document_context: DocumentTestContext,
) -> None:
    corrupt = _upload(document_context, b"%PDF-1.7\nthis is not a PDF")
    encrypted = _upload(document_context, _encrypted_pdf())

    assert corrupt.status_code == 422
    assert "corrupt or unreadable" in corrupt.json()["detail"]
    assert encrypted.status_code == 422
    assert encrypted.json()["detail"] == "Encrypted PDFs are not supported."
    assert document_context.queue.jobs == []


def test_empty_oversized_and_over_page_limit_pdfs_are_rejected(
    document_context: DocumentTestContext,
) -> None:
    empty = _upload(document_context, b"")
    assert empty.status_code == 422
    assert "empty" in empty.json()["detail"]

    document_context.settings.max_pdf_size_bytes = 100
    oversized = _upload(document_context)
    assert oversized.status_code == 413
    assert "size limit" in oversized.json()["detail"]

    document_context.settings.max_pdf_size_bytes = 20 * 1024 * 1024
    document_context.settings.max_pdf_pages = 1
    too_many_pages = _upload(document_context, _two_page_pdf())
    assert too_many_pages.status_code == 413
    assert "limit is 1" in too_many_pages.json()["detail"]


def test_document_endpoints_deny_cross_user_access(
    document_context: DocumentTestContext,
    db_session,
) -> None:
    uploaded = _upload(document_context)
    document_id = uploaded.json()["id"]
    _ingest(document_id, db_session, document_context)
    stranger = User(
        email="pdf-stranger@example.com",
        full_name="PDF Stranger",
        password_hash="unused",
    )
    db_session.add(stranger)
    db_session.commit()
    headers = {"Authorization": f"Bearer {access_token_for(stranger.id)}"}

    assert document_context.client.get("/documents", headers=headers).json() == []
    for path in (
        f"/documents/{document_id}",
        f"/documents/{document_id}/status",
        f"/documents/{document_id}/events",
        f"/documents/{document_id}/pages/1",
        f"/documents/{document_id}/pages/1/image",
        f"/documents/{document_id}/download",
    ):
        assert document_context.client.get(path, headers=headers).status_code == 404
    assert (
        document_context.client.delete(
            f"/documents/{document_id}",
            headers=headers,
        ).status_code
        == 404
    )


def test_reindex_replaces_vectors_only_for_the_owner(
    document_context: DocumentTestContext,
    db_session,
) -> None:
    uploaded = _upload(document_context)
    document_id = uploaded.json()["id"]
    _ingest(document_id, db_session, document_context)
    old_vector_id = db_session.scalar(
        select(Chunk.vector_id).where(Chunk.doc_id == document_id)
    )
    stranger = User(
        email="reindex-stranger@example.com",
        full_name="Reindex Stranger",
        password_hash="unused",
    )
    db_session.add(stranger)
    db_session.flush()
    foreign_document = Document(
        owner_id=stranger.id,
        title="Foreign document",
        status="ready",
    )
    db_session.add(foreign_document)
    db_session.commit()

    response = document_context.client.post(
        f"/documents/{document_id}/reindex",
        headers=document_context.headers,
    )

    assert response.status_code == 200
    assert response.json() == {"document_id": document_id, "indexed_count": 1}
    assert document_context.vector_store.deleted_documents == [
        document_id,
        document_id,
    ]
    assert (
        db_session.scalar(select(Chunk.vector_id).where(Chunk.doc_id == document_id))
        != old_vector_id
    )
    assert (
        document_context.client.post(
            f"/documents/{foreign_document.id}/reindex",
            headers=document_context.headers,
        ).status_code
        == 404
    )


def test_delete_removes_owned_file_pages_and_future_vectors(
    document_context: DocumentTestContext,
    db_session,
) -> None:
    uploaded = _upload(document_context)
    document_id = uploaded.json()["id"]
    storage_key = db_session.get(Document, document_id).storage_key
    _ingest(document_id, db_session, document_context)

    deleted = document_context.client.delete(
        f"/documents/{document_id}",
        headers=document_context.headers,
    )

    assert deleted.status_code == 204
    assert db_session.get(Document, document_id) is None
    assert (
        db_session.scalar(
            select(DocumentPage).where(DocumentPage.document_id == document_id)
        )
        is None
    )
    assert document_context.vector_store.deleted_documents == [
        document_id,
        document_id,
    ]
    with pytest.raises(FileNotFoundError):
        document_context.storage.get(storage_key)


def test_document_list_supports_owner_scoped_pagination(
    document_context: DocumentTestContext,
) -> None:
    first = _upload(document_context, filename="first.pdf").json()
    _upload(document_context, filename="second.pdf")

    response = document_context.client.get(
        "/documents?limit=1&offset=1",
        headers=document_context.headers,
    )

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["id"] == first["id"] + 1
