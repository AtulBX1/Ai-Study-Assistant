"""Classical Word2Vec training and lazily loaded pretrained GloVe vectors."""

import difflib
import os
import warnings
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Literal

import numpy as np

from app.nlp.preprocessing import preprocess_tokens

if TYPE_CHECKING:
    from app.retrieval.base import ChunkRecord

Architecture = Literal["cbow", "skipgram"]
EmbeddingModel = Literal["cbow", "skipgram", "glove"]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
WORD2VEC_ROOT = PROJECT_ROOT / "models" / "word2vec"
GLOVE_ROOT = PROJECT_ROOT / "models" / "glove"
GLOVE_NAME = "glove-wiki-gigaword-100"


class EmbeddingUnavailableError(FileNotFoundError):
    """An expected document embedding has not been trained."""


class OutOfVocabularyError(ValueError):
    """A requested word is absent from an embedding vocabulary."""

    def __init__(self, word: str, suggestion: str | None = None) -> None:
        self.word = word
        self.suggestion = suggestion
        message = f"Word {word!r} is out of vocabulary."
        if suggestion:
            message += f" Did you mean {suggestion!r}?"
        super().__init__(message)


def model_path(user_id: int, document_id: int, architecture: Architecture) -> Path:
    """Return the isolated on-disk path for one user's document model."""
    return WORD2VEC_ROOT / str(user_id) / str(document_id) / f"{architecture}.model"


def train_word2vec(
    chunks: Sequence["ChunkRecord"],
    user_id: int,
    document_id: int,
    architecture: Architecture,
    *,
    vector_size: int = 100,
    window: int = 5,
    min_count: int = 1,
    epochs: int = 20,
    negative: int = 5,
    seed: int = 42,
) -> dict[str, int | float | str | bool]:
    """Train and save CBOW or Skip-Gram from Step 4-preprocessed chunk tokens."""
    from gensim.models import Word2Vec

    sentences = [
        tokens
        for chunk in chunks
        if chunk.document_id == document_id
        if (tokens := preprocess_tokens(chunk.text))
    ]
    started = perf_counter()
    model = Word2Vec(
        vector_size=vector_size,
        window=window,
        min_count=min_count,
        workers=1,
        sg=int(architecture == "skipgram"),
        negative=negative,
        seed=seed,
        sample=0,
    )
    if not sentences:
        warning = "No tokens remained after preprocessing; model was not saved."
        warnings.warn(warning, RuntimeWarning, stacklevel=2)
        return {
            "architecture": architecture,
            "vocab_size": 0,
            "training_time_seconds": round(perf_counter() - started, 6),
            "saved": False,
            "warning": warning,
        }
    model.build_vocab(sentences)
    vocabulary_size = len(model.wv)
    warning = None
    if vocabulary_size < 2:
        warning = (
            "Vocabulary is too small for meaningful word similarities "
            f"({vocabulary_size} word(s)); add more chunks or lower min_count."
        )
        warnings.warn(warning, RuntimeWarning, stacklevel=2)
    if vocabulary_size:
        model.train(sentences, total_examples=model.corpus_count, epochs=epochs)
        path = model_path(user_id, document_id, architecture)
        path.parent.mkdir(parents=True, exist_ok=True)
        model.save(str(path))
    else:
        warning = "No words met min_count; model was not saved."
    return {
        "architecture": architecture,
        "vocab_size": vocabulary_size,
        "training_time_seconds": round(perf_counter() - started, 6),
        "saved": bool(vocabulary_size),
        "warning": warning or "",
    }


def load_word2vec(user_id: int, document_id: int, architecture: Architecture):
    """Load a saved per-user, per-document model."""
    from gensim.models import Word2Vec

    path = model_path(user_id, document_id, architecture)
    if not path.is_file():
        raise EmbeddingUnavailableError(
            f"No {architecture} model is trained for this document."
        )
    return Word2Vec.load(str(path)).wv


@lru_cache(maxsize=1)
def load_glove():
    """Load GloVe only on demand, keeping its download/cache in models/glove."""
    GLOVE_ROOT.mkdir(parents=True, exist_ok=True)
    os.environ["GENSIM_DATA_DIR"] = str(GLOVE_ROOT)
    import gensim.downloader as api

    api.BASE_DIR = str(GLOVE_ROOT)
    return api.load(GLOVE_NAME)


def keyed_vectors(model: EmbeddingModel, user_id: int, document_id: int | None = None):
    """Resolve a pretrained or owner-scoped Word2Vec vocabulary."""
    if model == "glove":
        return load_glove()
    if document_id is None:
        raise ValueError("document_id is required for CBOW and Skip-Gram models.")
    return load_word2vec(user_id, document_id, model)


def suggest_word(word: str, vocabulary: Sequence[str]) -> str | None:
    """Find a close spelling without comparing against a huge vocabulary."""
    target = word.lower()
    nearby = [
        candidate
        for candidate in vocabulary
        if candidate
        and candidate[0].lower() == target[:1]
        and abs(len(candidate) - len(target)) <= max(2, len(target) // 3)
    ]
    candidates = nearby or list(vocabulary[:10_000])
    matches = difflib.get_close_matches(target, candidates, n=1, cutoff=0.65)
    return matches[0] if matches else None


def require_words(vectors, words: Sequence[str]) -> list[str]:
    """Normalize words and raise a useful OOV error at the first missing term."""
    normalized = [word.strip().lower() for word in words]
    for word in normalized:
        if word not in vectors:
            raise OutOfVocabularyError(word, suggest_word(word, vectors.index_to_key))
    return normalized


def cosine_similarity(vectors, first: str, second: str) -> float:
    """Return cosine similarity after validating both vocabulary entries."""
    first, second = require_words(vectors, [first, second])
    return float(vectors.similarity(first, second))


def most_similar(vectors, word: str, topn: int) -> list[dict[str, float | str]]:
    """Return nearest words with cosine similarity scores."""
    (word,) = require_words(vectors, [word])
    return [
        {"word": candidate, "score": float(score)}
        for candidate, score in vectors.most_similar(word, topn=topn)
    ]


def solve_analogy(
    vectors, a: str, b: str, c: str, topn: int
) -> list[dict[str, float | str]]:
    """Solve a - b + c in the embedding space."""
    a, b, c = require_words(vectors, [a, b, c])
    return [
        {"word": candidate, "score": float(score)}
        for candidate, score in vectors.most_similar(
            positive=[a, c], negative=[b], topn=topn
        )
    ]


def project_vectors(
    vectors,
    method: Literal["pca", "tsne", "umap"],
    dims: Literal[2, 3],
    top_n: int,
) -> dict[str, object]:
    """Project frequent vocabulary terms and cluster their original vectors."""
    from sklearn.cluster import KMeans
    from sklearn.decomposition import PCA

    words = list(vectors.index_to_key[:top_n])
    if not words:
        raise ValueError("The embedding vocabulary is empty.")
    matrix = np.asarray([vectors[word] for word in words], dtype=np.float32)
    if method == "pca":
        components = min(dims, len(words), matrix.shape[1])
        reduced = PCA(n_components=components, random_state=42).fit_transform(matrix)
        if components < dims:
            reduced = np.pad(reduced, ((0, 0), (0, dims - components)))
    elif method == "tsne":
        if len(words) < 2:
            raise ValueError("t-SNE needs at least two vocabulary words.")
        from sklearn.manifold import TSNE

        perplexity = min(30.0, max(1.0, (len(words) - 1) / 3.0))
        reduced = TSNE(
            n_components=dims,
            perplexity=perplexity,
            init="random",
            learning_rate="auto",
            random_state=42,
        ).fit_transform(matrix)
    else:
        try:
            import umap
        except ImportError as error:
            raise RuntimeError(
                "UMAP is not installed; install the optional umap-learn extra "
                "only if its Windows dependencies are available."
            ) from error
        if len(words) < 3:
            raise ValueError("UMAP needs at least three vocabulary words.")
        reduced = umap.UMAP(
            n_components=dims,
            n_neighbors=min(15, len(words) - 1),
            random_state=42,
        ).fit_transform(matrix)

    cluster_count = min(8, max(1, int(np.sqrt(len(words)))))
    cluster_ids = KMeans(
        n_clusters=cluster_count,
        n_init=10,
        random_state=42,
    ).fit_predict(matrix)
    return {
        "coordinates": [
            {"word": word, "coordinates": [float(value) for value in point]}
            for word, point in zip(words, reduced, strict=True)
        ],
        "labels": words,
        "cluster_ids": [int(cluster_id) for cluster_id in cluster_ids],
    }
