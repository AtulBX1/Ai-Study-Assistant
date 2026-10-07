"""Cosine-similarity retrieval over indexed sentence-transformer vectors."""

from collections.abc import Sequence
from uuid import NAMESPACE_URL, uuid5

from app.core.config import get_settings
from app.retrieval.base import ChunkRecord, Retriever
from app.retrieval.registry import register_retriever
from app.services.embeddings import EmbeddingService, get_embedding_service
from app.services.vector_store import VectorStore, get_vector_store


def _stable_vector_id(user_id: int, document_id: int, chunk_id: int) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"ai-study-assistant:{user_id}:{document_id}:{chunk_id}",
        )
    )


@register_retriever("dense")
class DenseRetriever(Retriever):
    """Search document embeddings in Qdrant using cosine similarity."""

    def __init__(
        self,
        chunks: Sequence[ChunkRecord],
        user_id: int = 0,
        *,
        vector_store: VectorStore | None = None,
        embedding_service: EmbeddingService | None = None,
    ) -> None:
        super().__init__(chunks, user_id)
        self.vector_store = vector_store or get_vector_store()
        self.embedding_service = embedding_service or get_embedding_service()
        self.settings = get_settings()
        self._chunk_by_vector_id = {
            chunk.vector_id
            or _stable_vector_id(user_id, chunk.document_id, chunk.chunk_id): chunk
            for chunk in self.chunks
        }
        missing = [chunk for chunk in self.chunks if not chunk.vector_id]
        if missing:
            ids = [
                _stable_vector_id(user_id, chunk.document_id, chunk.chunk_id)
                for chunk in missing
            ]
            vectors = self.embedding_service.embed_texts(
                [chunk.text for chunk in missing]
            )
            payloads = [
                {
                    "user_id": user_id,
                    "document_id": chunk.document_id,
                    "chunk_id": chunk.chunk_id,
                    "page": chunk.page,
                    "section": chunk.section,
                }
                for chunk in missing
            ]
            self.vector_store.upsert(
                self.settings.qdrant_collection, ids, vectors, payloads
            )

    def score(self, query: str) -> list[float]:
        """Return cosine similarities for each chunk in the scoped corpus."""
        if not self.chunks:
            return []
        query_vector = self.embedding_service.embed_texts([query])[0]
        document_ids = sorted({chunk.document_id for chunk in self.chunks})
        matches = self.vector_store.search(
            self.settings.qdrant_collection,
            query_vector,
            limit=len(self.chunks),
            user_id=self.user_id,
            document_ids=document_ids,
        )
        score_by_id = {match.id: float(match.score) for match in matches}
        return [
            score_by_id.get(
                chunk.vector_id
                or _stable_vector_id(self.user_id, chunk.document_id, chunk.chunk_id),
                0.0,
            )
            for chunk in self.chunks
        ]
