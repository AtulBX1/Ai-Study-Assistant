"""Owner-scoped PDF upload, ingestion status, and retrieval endpoints."""

import json
import logging
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Generator
from typing import Annotated
from urllib.parse import quote
from uuid import uuid4

import pymupdf
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models import Document, DocumentPage, DocumentStatusEvent, User
from app.schemas.documents import DocumentPageResponse, DocumentResponse
from app.services.document_ingestion import (
    InvalidPDFError,
    PDFPageLimitError,
    UnsupportedPDFError,
    inspect_pdf,
    sanitize_filename,
)
from app.services.file_storage import FileStorage, create_file_storage
from app.services.job_queue import JobQueue, create_job_queue
from app.services.vector_store import VectorStore, create_vector_store
from app.workers.document_tasks import process_document_job

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])
DatabaseSession = Annotated[Session, Depends(get_db)]
AuthenticatedUser = Annotated[User, Depends(get_current_user)]
_image_cache: OrderedDict[tuple[int, int, str], bytes] = OrderedDict()
_image_cache_lock = threading.Lock()


def get_document_file_storage() -> FileStorage:
    """Resolve the configured document storage adapter."""
    return create_file_storage()


def get_document_job_queue(background_tasks: BackgroundTasks) -> JobQueue:
    """Resolve the configured queue and register the local ingestion handler."""
    return create_job_queue(
        background_tasks,
        {"ingest_document": process_document_job},
    )


def get_document_vector_store() -> VectorStore:
    """Resolve the configured vector-store adapter."""
    return create_vector_store()


def _owned_document(db: Session, document_id: int, owner_id: int) -> Document:
    document = db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.owner_id == owner_id,
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document


def _remember_image(key: tuple[int, int, str], image: bytes, capacity: int) -> bytes:
    with _image_cache_lock:
        _image_cache[key] = image
        _image_cache.move_to_end(key)
        while len(_image_cache) > capacity:
            _image_cache.popitem(last=False)
    return image


def _clear_document_images(document_id: int) -> None:
    with _image_cache_lock:
        for key in list(_image_cache):
            if key[0] == document_id:
                del _image_cache[key]


@router.post("/upload", response_model=DocumentResponse, status_code=202)
async def upload_document(
    db: DatabaseSession,
    user: AuthenticatedUser,
    file_storage: Annotated[FileStorage, Depends(get_document_file_storage)],
    job_queue: Annotated[JobQueue, Depends(get_document_job_queue)],
    file: Annotated[UploadFile, File(...)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Document:
    """Validate and store a PDF, then queue its page ingestion."""
    content = await file.read(settings.max_pdf_size_bytes + 1)
    if len(content) > settings.max_pdf_size_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"PDF exceeds the {settings.max_pdf_size_bytes}-byte size limit.",
        )
    try:
        page_count = inspect_pdf(content, settings.max_pdf_pages)
    except InvalidPDFError as error:
        if isinstance(error, UnsupportedPDFError):
            status_code = 415
        elif isinstance(error, PDFPageLimitError):
            status_code = 413
        else:
            status_code = 422
        raise HTTPException(status_code=status_code, detail=str(error)) from error

    title = sanitize_filename(file.filename or "document.pdf")
    if not title.lower().endswith(".pdf"):
        title = f"{title}.pdf"[:255]
    storage_key = f"{user.id}/{uuid4().hex}.pdf"
    file_storage.put(storage_key, content)
    document = Document(
        owner_id=user.id,
        title=title,
        status="queued",
        progress=0,
        page_count=page_count,
        storage_key=storage_key,
    )
    try:
        db.add(document)
        db.flush()
        db.add(
            DocumentStatusEvent(
                document_id=document.id,
                status="queued",
                progress=0,
            )
        )
        db.commit()
        db.refresh(document)
    except Exception:
        db.rollback()
        file_storage.delete(storage_key)
        raise

    try:
        job_queue.enqueue("ingest_document", document.id)
    except Exception as error:
        logger.exception("Could not enqueue ingestion for document %s", document.id)
        document.status = "failed"
        document.progress = 100
        document.error_message = "Could not enqueue the document ingestion job."
        db.add(
            DocumentStatusEvent(
                document_id=document.id,
                status="failed",
                progress=100,
                error_message=document.error_message,
            )
        )
        db.commit()
        raise HTTPException(
            status_code=503,
            detail=(
                "The document was stored, but its ingestion job could not be queued."
            ),
        ) from error
    return document


@router.get("", response_model=list[DocumentResponse])
def list_documents(
    db: DatabaseSession,
    user: AuthenticatedUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Document]:
    """Return a page of only the authenticated user's documents."""
    return list(
        db.scalars(
            select(Document)
            .where(Document.owner_id == user.id)
            .order_by(Document.id)
            .offset(offset)
            .limit(limit)
        )
    )


@router.get("/{document_id}/status", response_model=DocumentResponse)
def get_document_status(
    document_id: int,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> Document:
    """Return the owner-scoped current ingestion stage and progress."""
    return _owned_document(db, document_id, user.id)


@router.get("/{document_id}/events")
def stream_document_events(
    document_id: int,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> StreamingResponse:
    """Stream persisted stage/progress updates until ingestion is terminal."""
    document = _owned_document(db, document_id, user.id)

    def events() -> Generator[str, None, None]:
        last_event_id = 0
        while True:
            updates = list(
                db.scalars(
                    select(DocumentStatusEvent)
                    .where(
                        DocumentStatusEvent.document_id == document_id,
                        DocumentStatusEvent.id > last_event_id,
                    )
                    .order_by(DocumentStatusEvent.id)
                )
            )
            for update in updates:
                last_event_id = update.id
                data = {
                    "document_id": document_id,
                    "status": update.status,
                    "progress": update.progress,
                    "error_message": update.error_message,
                }
                yield f"id: {update.id}\ndata: {json.dumps(data)}\n\n"
            if document.status in {"ready", "failed"} and not updates:
                return
            if document.status in {"ready", "failed"} and updates:
                terminal = updates[-1].status in {"ready", "failed"}
                if terminal:
                    return
            time.sleep(0.5)
            db.refresh(document)
            yield ": keep-alive\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{document_id}/pages/{page_number}", response_model=DocumentPageResponse)
def get_document_page(
    document_id: int,
    page_number: int,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> DocumentPage:
    """Return one page's text and structured layout from an owned document."""
    _owned_document(db, document_id, user.id)
    page = db.scalar(
        select(DocumentPage).where(
            DocumentPage.document_id == document_id,
            DocumentPage.page_number == page_number,
        )
    )
    if page is None:
        raise HTTPException(status_code=404, detail="Document page not found.")
    return page


@router.get("/{document_id}/pages/{page_number}/image")
def get_document_page_image(
    document_id: int,
    page_number: int,
    db: DatabaseSession,
    user: AuthenticatedUser,
    file_storage: Annotated[FileStorage, Depends(get_document_file_storage)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """Render and cache one owned PDF page as a PNG image."""
    document = _owned_document(db, document_id, user.id)
    if page_number < 1 or (document.page_count and page_number > document.page_count):
        raise HTTPException(status_code=404, detail="Document page not found.")
    if document.storage_key is None:
        raise HTTPException(status_code=404, detail="Document file not found.")
    revision = document.updated_at.isoformat()
    cache_key = (document.id, page_number, revision)
    with _image_cache_lock:
        image = _image_cache.get(cache_key)
        if image is not None:
            _image_cache.move_to_end(cache_key)
    if image is None:
        content = file_storage.get(document.storage_key)
        try:
            with pymupdf.open(stream=content, filetype="pdf") as pdf:
                if page_number > pdf.page_count:
                    raise HTTPException(
                        status_code=404, detail="Document page not found."
                    )
                pixmap = pdf[page_number - 1].get_pixmap(
                    matrix=pymupdf.Matrix(1.5, 1.5), alpha=False
                )
                image = pixmap.tobytes("png")
        except pymupdf.FileDataError as error:
            raise HTTPException(
                status_code=422, detail="The stored PDF cannot be rendered."
            ) from error
        image = _remember_image(cache_key, image, settings.page_image_cache_size)
    return Response(content=image, media_type="image/png")


@router.get("/{document_id}/download")
def download_document(
    document_id: int,
    db: DatabaseSession,
    user: AuthenticatedUser,
    file_storage: Annotated[FileStorage, Depends(get_document_file_storage)],
) -> Response:
    """Download the original PDF belonging to the authenticated user."""
    document = _owned_document(db, document_id, user.id)
    if document.storage_key is None:
        raise HTTPException(status_code=404, detail="Document file not found.")
    content = file_storage.get(document.storage_key)
    safe_filename = re.sub(r"[^A-Za-z0-9._ -]", "_", document.title)
    disposition_name = quote(safe_filename, safe="")
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{disposition_name}"'},
    )


@router.delete("/{document_id}", status_code=204)
def delete_document(
    document_id: int,
    db: DatabaseSession,
    user: AuthenticatedUser,
    file_storage: Annotated[FileStorage, Depends(get_document_file_storage)],
    vector_store: Annotated[VectorStore, Depends(get_document_vector_store)],
) -> Response:
    """Delete an owned document, its file, pages, chunks, and future vectors."""
    document = _owned_document(db, document_id, user.id)
    vector_store.delete_document(document_id)
    if document.storage_key is not None:
        file_storage.delete(document.storage_key)
    db.delete(document)
    db.commit()
    _clear_document_images(document_id)
    return Response(status_code=204)


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: int,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> Document:
    """Fetch a document only when it belongs to the authenticated user."""
    return _owned_document(db, document_id, user.id)
