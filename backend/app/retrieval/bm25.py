"""Okapi BM25 retriever using the shared Step 4 token preprocessing."""

from collections.abc import Sequence

from rank_bm25 import BM25Okapi

from app.retrieval.base import ChunkRecord, Retriever, preprocess_tokens
from app.retrieval.registry import register_retriever


@register_retriever("bm25")
class BM25Retriever(Retriever):
    """Rank chunks with BM25 term saturation and document-length normalization."""

    def __init__(self, chunks: Sequence[ChunkRecord], user_id: int = 0) -> None:
        super().__init__(chunks, user_id)
        self._tokenized = [preprocess_tokens(chunk.text) for chunk in self.chunks]
        self._index = (
            BM25Okapi(self._tokenized)
            if self._tokenized and any(self._tokenized)
            else None
        )
        if self._index is not None:
            for token, inverse_frequency in self._index.idf.items():
                if inverse_frequency < 0:
                    # Tiny corpora can assign exact matches negative scores.
                    self._index.idf[token] = abs(inverse_frequency)

    def score(self, query: str) -> list[float]:
        """Return Okapi BM25 scores for a preprocessed query."""
        tokens = preprocess_tokens(query)
        if self._index is None or not tokens:
            return [0.0] * len(self.chunks)
        scores = self._index.get_scores(tokens)
        return [
            float(score) if set(tokens).intersection(document) else 0.0
            for document, score in zip(self._tokenized, scores, strict=True)
        ]
