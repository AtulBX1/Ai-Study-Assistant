"""BM25 and dense retrieval fused with weighted Reciprocal Rank Fusion."""

from collections.abc import Sequence
from typing import Any

from app.core.config import get_settings
from app.retrieval.base import ChunkRecord, Retriever
from app.retrieval.bm25 import BM25Retriever
from app.retrieval.dense import DenseRetriever
from app.retrieval.registry import register_retriever
from app.services.embeddings import EmbeddingService
from app.services.vector_store import VectorStore


@register_retriever("hybrid")
class HybridRetriever(Retriever):
    """Fuse independent BM25 and cosine rankings and expose their evidence."""

    def __init__(
        self,
        chunks: Sequence[ChunkRecord],
        user_id: int = 0,
        *,
        dense_weight: float | None = None,
        rrf_k: int | None = None,
        dense_retriever: DenseRetriever | None = None,
        bm25_retriever: BM25Retriever | None = None,
        vector_store: VectorStore | None = None,
        embedding_service: EmbeddingService | None = None,
    ) -> None:
        super().__init__(chunks, user_id)
        settings = get_settings()
        self.dense_weight = (
            settings.hybrid_dense_weight if dense_weight is None else dense_weight
        )
        self.rrf_k = settings.rrf_k if rrf_k is None else rrf_k
        if not 0 <= self.dense_weight <= 1:
            raise ValueError("dense_weight must be between 0 and 1.")
        if self.rrf_k < 1:
            raise ValueError("rrf_k must be at least 1.")
        self._dense = dense_retriever or DenseRetriever(
            chunks,
            user_id,
            vector_store=vector_store,
            embedding_service=embedding_service,
        )
        self._bm25 = bm25_retriever or BM25Retriever(chunks, user_id)
        self._explanations: dict[int, dict[str, Any]] = {}

    @staticmethod
    def _rank(scores: list[float]) -> dict[int, int]:
        ranked = sorted(
            (index for index, score in enumerate(scores) if score > 0),
            key=lambda index: (-scores[index], index),
        )
        return {index: rank for rank, index in enumerate(ranked, start=1)}

    def score(self, query: str) -> list[float]:
        """Compute weighted reciprocal ranks; absent component hits contribute 0."""
        dense_scores = self._dense.score(query)
        bm25_scores = self._bm25.score(query)
        dense_ranks = self._rank(dense_scores)
        bm25_ranks = self._rank(bm25_scores)
        sparse_weight = 1.0 - self.dense_weight
        fused: list[float] = []
        self._explanations = {}
        for index, chunk in enumerate(self.chunks):
            dense_rank = dense_ranks.get(index)
            bm25_rank = bm25_ranks.get(index)
            dense_rrf = (
                self.dense_weight / (self.rrf_k + dense_rank)
                if dense_rank is not None
                else 0.0
            )
            bm25_rrf = (
                sparse_weight / (self.rrf_k + bm25_rank)
                if bm25_rank is not None
                else 0.0
            )
            fused_score = dense_rrf + bm25_rrf
            fused.append(fused_score)
            self._explanations[chunk.chunk_id] = {
                "dense_rank": dense_rank,
                "dense_score": dense_scores[index],
                "bm25_rank": bm25_rank,
                "bm25_score": bm25_scores[index],
                "dense_rrf": dense_rrf,
                "bm25_rrf": bm25_rrf,
            }
        return fused

    def explain(self, chunk_id: int) -> dict[str, Any] | None:
        """Return the component ranks/scores computed for the last query."""
        return self._explanations.get(chunk_id)
