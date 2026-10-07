"""Authenticated classical document search."""

from collections.abc import Sequence
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models import Chunk, Document, User
from app.retrieval import ChunkRecord, RetrievalResult, get_retriever

router = APIRouter(tags=["search"])
DatabaseSession = Annotated[Session, Depends(get_db)]
AuthenticatedUser = Annotated[User, Depends(get_current_user)]
MAX_QUERY_LENGTH = 2000
MAX_SEARCH_RESULTS = 50


class SearchRequest(BaseModel):
    """A bounded query over an optional set of owned documents."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)
    mode: Literal["tfidf", "bm25"] = "tfidf"
    doc_ids: list[int] | None = Field(default=None, max_length=100)
    k: int = Field(default=5, ge=1, le=MAX_SEARCH_RESULTS)

    @field_validator("query")
    @classmethod
    def validate_query(cls, query: str) -> str:
        if not query.strip():
            raise ValueError("query cannot be blank.")
        return query

    @field_validator("doc_ids")
    @classmethod
    def validate_document_ids(cls, doc_ids: list[int] | None) -> list[int] | None:
        if doc_ids is not None and (
            any(document_id < 1 for document_id in doc_ids)
            or len(set(doc_ids)) != len(doc_ids)
        ):
            raise ValueError("doc_ids must contain unique positive IDs.")
        return doc_ids


def _owned_document_ids(
    db: Session, user_id: int, requested_ids: Sequence[int] | None
) -> list[int]:
    query = select(Document.id).where(Document.owner_id == user_id)
    if requested_ids is not None:
        if not requested_ids:
            return []
        query = query.where(Document.id.in_(requested_ids))
    owned_ids = list(db.scalars(query.order_by(Document.id)))
    if requested_ids is not None and set(owned_ids) != set(requested_ids):
        raise HTTPException(status_code=404, detail="Document not found.")
    return owned_ids


def _chunk_record(chunk: Chunk) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=chunk.id,
        document_id=chunk.doc_id,
        text=chunk.text,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        section=chunk.section,
    )


def _serialize_result(result: RetrievalResult) -> dict[str, object]:
    return {
        "chunk_id": result.chunk_id,
        "text": result.text,
        "document_id": result.document_id,
        "page": result.page,
        "page_start": result.page,
        "page_end": result.page_end,
        "section": result.section,
        "score": result.score,
        "rank": result.rank,
    }


@router.post("/search")
def search(
    request: SearchRequest,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, object]:
    """Search only the current user's documents with a registered retriever."""
    document_ids = _owned_document_ids(db, user.id, request.doc_ids)
    if not document_ids:
        return {"query": request.query, "mode": request.mode, "results": []}
    chunks = list(
        db.scalars(
            select(Chunk)
            .join(Document, Chunk.doc_id == Document.id)
            .where(
                Document.owner_id == user.id,
                Chunk.doc_id.in_(document_ids),
            )
            .order_by(Chunk.doc_id, Chunk.chunk_index, Chunk.id)
        )
    )
    records = [_chunk_record(chunk) for chunk in chunks]
    retriever = get_retriever(request.mode, user.id, records)
    results = retriever.retrieve(request.query, document_ids, request.k)
    return {
        "query": request.query,
        "mode": request.mode,
        "results": [_serialize_result(result) for result in results],
    }
