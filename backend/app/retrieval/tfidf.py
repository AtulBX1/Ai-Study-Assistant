"""TF-IDF cosine-similarity retriever."""

from collections.abc import Sequence

from sklearn.feature_extraction.text import TfidfVectorizer

from app.retrieval.base import ChunkRecord, Retriever, preprocess_tokens
from app.retrieval.registry import register_retriever


@register_retriever("tfidf")
class TfidfRetriever(Retriever):
    """Rank chunks by cosine similarity in a normalized TF-IDF space."""

    def __init__(self, chunks: Sequence[ChunkRecord]) -> None:
        super().__init__(chunks)
        tokenized = [preprocess_tokens(chunk.text) for chunk in self.chunks]
        self._valid_indexes = [
            index for index, tokens in enumerate(tokenized) if tokens
        ]
        self._matrix = None
        self._vectorizer: TfidfVectorizer | None = None
        if self._valid_indexes:
            self._vectorizer = TfidfVectorizer(
                tokenizer=str.split,
                token_pattern=None,
                preprocessor=None,
                lowercase=False,
                norm="l2",
            )
            texts = [" ".join(tokenized[index]) for index in self._valid_indexes]
            self._matrix = self._vectorizer.fit_transform(texts)

    def score(self, query: str) -> list[float]:
        """Compute cosine similarity via the dot product of L2-normalized rows."""
        scores = [0.0] * len(self.chunks)
        query_tokens = preprocess_tokens(query)
        if not query_tokens or self._vectorizer is None or self._matrix is None:
            return scores
        query_vector = self._vectorizer.transform([" ".join(query_tokens)])
        if query_vector.nnz == 0:
            return scores
        similarities = (self._matrix @ query_vector.T).toarray().ravel()
        for row, original_index in enumerate(self._valid_indexes):
            scores[original_index] = float(similarities[row])
        return scores
