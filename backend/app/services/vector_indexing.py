"""Persist chunk embeddings and source metadata through the vector-store interface."""

from collections.abc import Sequence
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Chunk, Document
from app.services.embeddings import EmbeddingService, get_embedding_service
from app.services.vector_store import VectorStore, get_vector_store


def index_document_chunks(
    db: Session,
    document: Document,
    *,
    chunks: Sequence[Chunk] | None = None,
    vector_store: VectorStore | None = None,
    embedding_service: EmbeddingService | None = None,
) -> int:
    """Embed and upsert a document's chunks, assigning each persisted vector ID."""
    stored_chunks = (
        list(chunks)
        if chunks is not None
        else list(
            db.scalars(
                select(Chunk)
                .where(Chunk.doc_id == document.id)
                .order_by(Chunk.chunk_index, Chunk.id)
            )
        )
    )
    if not stored_chunks:
        return 0

    store = vector_store or get_vector_store()
    embedder = embedding_service or get_embedding_service()
    settings = get_settings()
    ids = [str(uuid4()) for _ in stored_chunks]
    vectors = embedder.embed_texts([chunk.text for chunk in stored_chunks])
    payloads = [
        {
            "user_id": document.owner_id,
            "document_id": document.id,
            "chunk_id": chunk.id,
            "page": chunk.page,
            "section": chunk.section,
        }
        for chunk in stored_chunks
    ]
    store.upsert(settings.qdrant_collection, ids, vectors, payloads)
    for chunk, vector_id in zip(stored_chunks, ids, strict=True):
        chunk.vector_id = vector_id
    db.flush()
    return len(stored_chunks)
