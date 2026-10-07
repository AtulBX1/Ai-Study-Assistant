"""Lazy sentence-transformer embeddings with cache-backed normalized vectors."""

import hashlib
import json
import os
from collections.abc import Callable, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import numpy as np

from app.core.cache import Cache, create_cache
from app.core.config import Settings, get_settings


class SentenceEncoder(Protocol):
    """Minimal sentence-transformer encoder surface used by this service."""

    def encode(
        self,
        sentences: list[str],
        *,
        batch_size: int,
        convert_to_numpy: bool,
        normalize_embeddings: bool,
        show_progress_bar: bool,
    ) -> np.ndarray: ...


class EmbeddingService:
    """Encode and cache text vectors, loading the configured model on demand."""

    def __init__(
        self,
        settings: Settings | None = None,
        cache: Cache | None = None,
        model: SentenceEncoder | None = None,
        model_factory: Callable[[], SentenceEncoder] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.cache = cache or create_cache(self.settings)
        self._model = model
        self._model_factory = model_factory

    def _load_model(self) -> SentenceEncoder:
        if self._model is None:
            cache_root = Path(self.settings.hf_home).expanduser().resolve()
            cache_root.mkdir(parents=True, exist_ok=True)
            os.environ["HF_HOME"] = str(cache_root)
            if self._model_factory is not None:
                self._model = self._model_factory()
            else:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(
                    self.settings.embedding_model_name,
                    device=self.settings.embedding_device,
                    cache_folder=str(cache_root),
                )
        return self._model

    def _cache_key(self, text: str) -> str:
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return (
            f"embedding:{self.settings.embedding_model_name}:"
            f"{self.settings.embedding_device}:{text_hash}"
        )

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one finite, unit-normalized vector for each input string."""
        if any(not text.strip() for text in texts):
            raise ValueError("Embedding input text must not be blank.")
        if not texts:
            return []

        keys = [self._cache_key(text) for text in texts]
        vectors: list[list[float] | None] = [None] * len(texts)
        missing_by_key: dict[str, str] = {}
        for index, key in enumerate(keys):
            cached = self.cache.get(key)
            if cached is not None:
                parsed = json.loads(cached)
                if not isinstance(parsed, list) or not parsed:
                    raise ValueError("Cached embedding has an invalid vector shape.")
                vectors[index] = [float(value) for value in parsed]
            else:
                missing_by_key.setdefault(key, texts[index])

        if missing_by_key:
            missing_keys = list(missing_by_key)
            model_vectors = self._load_model().encode(
                [missing_by_key[key] for key in missing_keys],
                batch_size=self.settings.embedding_batch_size,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            array = np.asarray(model_vectors, dtype=np.float32)
            if array.ndim != 2 or array.shape[0] != len(missing_keys):
                raise ValueError("Embedding model returned an invalid vector shape.")
            if not np.isfinite(array).all():
                raise ValueError("Embedding model returned non-finite vector values.")
            norms = np.linalg.norm(array, axis=1, keepdims=True)
            if np.any(norms == 0):
                raise ValueError("Embedding model returned a zero-length vector.")
            array /= norms
            for key, vector in zip(missing_keys, array, strict=True):
                encoded = [float(value) for value in vector]
                self.cache.set(key, json.dumps(encoded, allow_nan=False))
            by_key = {
                key: [float(value) for value in vector]
                for key, vector in zip(missing_keys, array, strict=True)
            }
            for index, key in enumerate(keys):
                if vectors[index] is None:
                    vectors[index] = by_key[key]

        if any(vector is None for vector in vectors):
            raise RuntimeError("An embedding was not produced for every input.")
        return [vector for vector in vectors if vector is not None]


@lru_cache(maxsize=1)
def _get_embedding_service() -> EmbeddingService:
    return EmbeddingService()


def get_embedding_service() -> EmbeddingService:
    """Return the process-wide lazy embedding service."""
    return _get_embedding_service()
