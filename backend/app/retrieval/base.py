"""Shared chunk metadata and retriever contract."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

from app.nlp.preprocessing import preprocess_tokens

__all__ = ["ChunkRecord", "RetrievalResult", "Retriever", "preprocess_tokens"]


@dataclass(frozen=True)
class ChunkRecord:
    """Retriever-ready view of a persisted or evaluation chunk."""

    chunk_id: int
    text: str
    document_id: int
    page_start: int
    page_end: int
    section: str | None = None

    @property
    def page(self) -> int:
        """Return the first page for APIs and page-based evaluation."""
        return self.page_start


@dataclass(frozen=True)
class RetrievalResult:
    """One ranked chunk result with source citation metadata."""

    chunk_id: int
    text: str
    document_id: int
    page: int
    page_end: int
    section: str | None
    score: float
    rank: int


class Retriever(ABC):
    """Common interface for ranking chunks from selected documents."""

    def __init__(self, chunks: Sequence[ChunkRecord], user_id: int = 0) -> None:
        self.chunks = tuple(chunks)
        self.user_id = user_id

    @abstractmethod
    def score(self, query: str) -> list[float]:
        """Return one relevance score for every chunk in ``self.chunks``."""

    def retrieve(
        self,
        query: str,
        doc_ids: Sequence[int] | None,
        k: int,
    ) -> list[RetrievalResult]:
        """Return up to k ranked chunks, optionally restricted to document IDs."""
        if k < 1:
            raise ValueError("k must be at least 1.")
        selected_ids = set(doc_ids) if doc_ids is not None else None
        selected = [
            (index, chunk)
            for index, chunk in enumerate(self.chunks)
            if selected_ids is None or chunk.document_id in selected_ids
        ]
        if not selected:
            return []

        scores = self.score(query)
        ranked = sorted(
            (
                (scores[index], chunk.chunk_id, chunk)
                for index, chunk in selected
                if scores[index] > 0
            ),
            key=lambda result: (-result[0], result[1]),
        )[:k]
        return [
            RetrievalResult(
                chunk_id=chunk.chunk_id,
                text=chunk.text,
                document_id=chunk.document_id,
                page=chunk.page,
                page_end=chunk.page_end,
                section=chunk.section,
                score=float(score),
                rank=rank,
            )
            for rank, (score, _, chunk) in enumerate(ranked, start=1)
        ]
