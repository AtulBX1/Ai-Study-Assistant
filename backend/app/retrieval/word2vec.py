"""Cosine retrieval over averaged, document-local Word2Vec vectors."""

from collections.abc import Sequence

import numpy as np

from app.nlp.embeddings_classic import (
    EmbeddingUnavailableError,
    load_word2vec,
    model_path,
)
from app.retrieval.base import ChunkRecord, Retriever, preprocess_tokens
from app.retrieval.registry import register_retriever


@register_retriever("word2vec")
class Word2VecRetriever(Retriever):
    """Average query/chunk word vectors and rank with cosine similarity."""

    def __init__(self, chunks: Sequence[ChunkRecord], user_id: int = 0) -> None:
        super().__init__(chunks, user_id)
        self._models = {}
        self._chunk_vectors: dict[int, tuple[int, np.ndarray | None]] = {}
        for document_id in {chunk.document_id for chunk in self.chunks}:
            available = [
                (model_path(user_id, document_id, architecture), architecture)
                for architecture in ("cbow", "skipgram")
                if model_path(user_id, document_id, architecture).is_file()
            ]
            if not available:
                continue
            _, architecture = max(
                available, key=lambda item: item[0].stat().st_mtime_ns
            )
            try:
                self._models[document_id] = load_word2vec(
                    user_id, document_id, architecture
                )
            except EmbeddingUnavailableError:
                continue

    def _average(self, tokens: list[str], vectors) -> np.ndarray | None:
        known = [vectors[token] for token in tokens if token in vectors]
        if not known:
            return None
        return np.mean(known, axis=0)

    def score(self, query: str) -> list[float]:
        """Compute cosine similarity for each chunk using its document model."""
        tokens = preprocess_tokens(query)
        scores = [0.0] * len(self.chunks)
        by_document: dict[int, np.ndarray | None] = {}
        for index, chunk in enumerate(self.chunks):
            vectors = self._models.get(chunk.document_id)
            if vectors is None:
                continue
            if chunk.document_id not in by_document:
                by_document[chunk.document_id] = self._average(tokens, vectors)
            query_vector = by_document[chunk.document_id]
            if query_vector is None:
                continue
            cached = self._chunk_vectors.get(chunk.chunk_id)
            if cached is None or cached[0] != id(vectors):
                chunk_vector = self._average(preprocess_tokens(chunk.text), vectors)
                self._chunk_vectors[chunk.chunk_id] = (id(vectors), chunk_vector)
            else:
                chunk_vector = cached[1]
            if chunk_vector is None:
                continue
            denominator = np.linalg.norm(query_vector) * np.linalg.norm(chunk_vector)
            if denominator:
                scores[index] = float(np.dot(query_vector, chunk_vector) / denominator)
        return scores
