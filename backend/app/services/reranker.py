"""Lazy cross-encoder reranking with a logged unreranked fallback."""

import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import numpy as np

from app.core.config import Settings, get_settings
from app.retrieval.base import RetrievalResult

logger = logging.getLogger(__name__)
MAX_RERANK_CANDIDATES = 30


class CrossEncoderModel(Protocol):
    """Minimal sentence-transformers CrossEncoder surface."""

    def predict(
        self, sentences: list[tuple[str, str]], *, show_progress_bar: bool
    ) -> np.ndarray: ...


@dataclass(frozen=True)
class RerankOutcome:
    """Reranked results and whether cross-encoder scoring succeeded."""

    results: list[RetrievalResult]
    applied: bool
    error: str | None = None


class CrossEncoderReranker:
    """Score top retrieval candidates with a lazily initialized cross-encoder."""

    def __init__(
        self,
        settings: Settings | None = None,
        model: CrossEncoderModel | None = None,
        model_factory: Callable[[], CrossEncoderModel] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._model = model
        self._model_factory = model_factory

    def _load_model(self) -> CrossEncoderModel:
        if self._model is None:
            cache_root = Path(self.settings.hf_home).expanduser().resolve()
            cache_root.mkdir(parents=True, exist_ok=True)
            os.environ["HF_HOME"] = str(cache_root)
            if self._model_factory is not None:
                self._model = self._model_factory()
            else:
                from sentence_transformers import CrossEncoder

                self._model = CrossEncoder(
                    self.settings.reranker_model_name,
                    device=self.settings.embedding_device,
                    cache_folder=str(cache_root),
                )
        return self._model

    def rerank(
        self,
        query: str,
        candidates: Sequence[RetrievalResult],
        k: int,
    ) -> RerankOutcome:
        """Rerank at most 30 results, returning original order on model failure."""
        limited = list(candidates[:MAX_RERANK_CANDIDATES])
        if not limited:
            return RerankOutcome([], applied=True)
        try:
            scores = np.asarray(
                self._load_model().predict(
                    [(query, candidate.text) for candidate in limited],
                    show_progress_bar=False,
                ),
                dtype=np.float32,
            ).reshape(-1)
            if len(scores) != len(limited) or not np.isfinite(scores).all():
                raise ValueError("Cross-encoder returned invalid rerank scores.")
        except Exception:
            logger.exception("Cross-encoder reranking failed; keeping retrieval order.")
            return RerankOutcome(
                [
                    replace(
                        candidate,
                        original_score=candidate.score,
                        rerank_score=None,
                    )
                    for candidate in limited[:k]
                ],
                applied=False,
                error="Cross-encoder reranking was unavailable.",
            )

        ranked = sorted(
            zip(limited, scores, strict=True),
            key=lambda pair: (-float(pair[1]), pair[0].rank, pair[0].chunk_id),
        )[:k]
        return RerankOutcome(
            [
                replace(
                    candidate,
                    original_score=candidate.score,
                    rerank_score=float(score),
                    rank=rank,
                )
                for rank, (candidate, score) in enumerate(ranked, start=1)
            ],
            applied=True,
        )


def get_cross_encoder_reranker() -> CrossEncoderReranker:
    """Return the process-wide lazy cross-encoder service."""
    return _get_cross_encoder_reranker()


@lru_cache(maxsize=1)
def _get_cross_encoder_reranker() -> CrossEncoderReranker:
    return CrossEncoderReranker()
