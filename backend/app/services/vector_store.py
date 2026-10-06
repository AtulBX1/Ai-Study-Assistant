"""Vector-store interface with local Qdrant and server-backed adapters."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from qdrant_client import QdrantClient, models

from app.core.config import Settings, get_settings


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
        self, collection: str, vector: list[float], limit: int = 5
    ) -> list[VectorMatch]:
        """Return the closest vector points."""


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
        self, collection: str, vector: list[float], limit: int = 5
    ) -> list[VectorMatch]:
        results = self._client.query_points(
            collection_name=collection, query=vector, limit=limit
        ).points
        return [
            VectorMatch(id=str(point.id), score=point.score, payload=point.payload)
            for point in results
        ]


def create_vector_store(settings: Settings | None = None) -> VectorStore:
    """Select persistent local Qdrant or a Qdrant server from BACKEND."""
    runtime_settings = settings or get_settings()
    if runtime_settings.backend == "local":
        Path(runtime_settings.qdrant_local_path).mkdir(parents=True, exist_ok=True)
        client = QdrantClient(path=runtime_settings.qdrant_local_path)
    else:
        runtime_settings.validate_vector_backend()
        if runtime_settings.qdrant_url is None:
            raise ValueError("QDRANT_URL is required when BACKEND=prod.")
        client = QdrantClient(url=runtime_settings.qdrant_url)
    return QdrantVectorStore(client)
