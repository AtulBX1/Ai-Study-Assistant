"""Background tasks for PDF document ingestion."""

import logging

from app.celery_app import celery_app
from app.core.database import SessionLocal
from app.services.document_ingestion import ingest_document
from app.services.file_storage import create_file_storage

logger = logging.getLogger(__name__)


@celery_app.task(name="ingest_document")
def process_document_job(document_id: int) -> None:
    """Open worker resources and run ingestion for one document."""
    storage = create_file_storage()
    with SessionLocal() as db:
        try:
            ingest_document(document_id, db, storage)
        except Exception:
            logger.exception("Document ingestion failed for document %s", document_id)
            raise
