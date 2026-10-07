"""Vector-store interface with local Qdrant and server-backed adapters."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from qdrant_client import QdrantClient, models

from app.core.config import PROJECT_ROOT, Settings, get_settings


@dataclass(frozen=True)
class VectorMatch:
    """A vector result with its identifier, score, and optional metadata."""

    id: str
    score: float
    payload: dict[str, Any] | None


class VectorStore(Protocol):
    """Operations shared by local and production vector indexes."""

    def upsert(
        self,
        collection: str,
        ids: list[str],
        vectors: list[list[float]],
        payloads: list[dict[str, Any]] | None = None,
    ) -> None:
        """Insert or replace vector points."""

    def search(
        self,
        collection: str,
        vector: list[float],
        limit: int = 5,
        user_id: int | None = None,
        document_ids: list[int] | None = None,
    ) -> list[VectorMatch]:
        """Return closest points, optionally restricted by owner and documents."""

    def delete_document(self, document_id: int) -> None:
        """Remove vector points whose payload belongs to a document."""

    def delete_ids(self, collection: str, ids: list[str]) -> None:
        """Remove selected vector points from a collection."""


class QdrantVectorStore:
    """Qdrant adapter usable in embedded-file or remote-server mode."""

    def __init__(self, client: QdrantClient) -> None:
        self._client = client

    def upsert(
        self,
        collection: str,
        ids: list[str],
        vectors: list[list[float]],
        payloads: list[dict[str, Any]] | None = None,
    ) -> None:
        if not ids or not vectors or len(ids) != len(vectors):
            raise ValueError("ids and vectors must have the same non-zero length.")
        if payloads is not None and len(payloads) != len(ids):
            raise ValueError("payloads must have the same length as ids.")
        if not self._client.collection_exists(collection):
            self._client.create_collection(
                collection_name=collection,
                vectors_config=models.VectorParams(
                    size=len(vectors[0]), distance=models.Distance.COSINE
                ),
            )
        points = [
            models.PointStruct(
                id=point_id,
                vector=vector,
                payload=payloads[index] if payloads is not None else None,
            )
            for index, (point_id, vector) in enumerate(zip(ids, vectors, strict=True))
        ]
        self._client.upsert(collection_name=collection, points=points)

    def search(
        self,
        collection: str,
        vector: list[float],
        limit: int = 5,
        user_id: int | None = None,
        document_ids: list[int] | None = None,
    ) -> list[VectorMatch]:
        if limit < 1:
            raise ValueError("limit must be at least 1.")
        if document_ids is not None and not document_ids:
            return []
        conditions = []
        if user_id is not None:
            conditions.append(
                models.FieldCondition(
                    key="user_id",
                    match=models.MatchValue(value=user_id),
                )
            )
        if document_ids is not None:
            conditions.append(
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchAny(any=document_ids),
                )
            )
        results = self._client.query_points(
            collection_name=collection,
            query=vector,
            query_filter=models.Filter(must=conditions) if conditions else None,
            limit=limit,
        ).points
        return [
            VectorMatch(id=str(point.id), score=point.score, payload=point.payload)
            for point in results
        ]

    def delete_ids(self, collection: str, ids: list[str]) -> None:
        if ids and self._client.collection_exists(collection):
            self._client.delete(collection_name=collection, points_selector=ids)

    def delete_document(self, document_id: int) -> None:
        selector = models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(value=document_id),
                    )
                ]
            )
        )
        for collection in self._client.get_collections().collections:
            self._client.delete(
                collection_name=collection.name,
                points_selector=selector,
            )


def create_vector_store(settings: Settings | None = None) -> VectorStore:
    """Select persistent local Qdrant or a Qdrant server from BACKEND."""
    runtime_settings = settings or get_settings()
    if runtime_settings.backend == "local":
        local_path = Path(runtime_settings.qdrant_local_path)
        if not local_path.is_absolute():
            local_path = PROJECT_ROOT / local_path
        local_path.mkdir(parents=True, exist_ok=True)
        client = QdrantClient(path=str(local_path.resolve()))
    else:
        runtime_settings.validate_vector_backend()
        if runtime_settings.qdrant_url is None:
            raise ValueError("QDRANT_URL is required when BACKEND=prod.")
        client = QdrantClient(
            url=runtime_settings.qdrant_url,
            api_key=runtime_settings.qdrant_api_key,
        )
    return QdrantVectorStore(client)


@lru_cache(maxsize=1)
def get_vector_store() -> VectorStore:
    """Return the process-wide configured vector-store adapter."""
    return create_vector_store()
