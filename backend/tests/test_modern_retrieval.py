"""Modern embedding, vector retrieval, RRF, and reranking coverage."""

import os
from collections.abc import Sequence

import numpy as np
import pytest
from conftest import access_token_for
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient
from sqlalchemy.orm import Session

from app.core.cache import MemoryCache
from app.core.config import Settings
from app.models import Chunk, Document, User
from app.retrieval.base import ChunkRecord, RetrievalResult
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.query_processing import NoOpQueryExpander, NoOpQueryRewriter
from app.retrieval.registry import invalidate_retriever_cache
from app.services.embeddings import EmbeddingService
from app.services.reranker import CrossEncoderReranker
from app.services.vector_store import QdrantVectorStore


class FakeEncoder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def encode(
        self,
        sentences: list[str],
        *,
        batch_size: int,
        convert_to_numpy: bool,
        normalize_embeddings: bool,
        show_progress_bar: bool,
    ) -> np.ndarray:
        self.calls.append(sentences)
        return np.asarray([[3.0, 4.0] for _ in sentences], dtype=np.float32)


def test_embedding_service_batches_normalizes_and_caches_text() -> None:
    encoder = FakeEncoder()
    service = EmbeddingService(
        Settings(embedding_model_name="test-encoder"),
        cache=MemoryCache(),
        model_factory=lambda: encoder,
    )

    assert not encoder.calls
    vectors = service.embed_texts(["same text", "another text", "same text"])
    cached = service.embed_texts(["same text"])

    assert len(vectors) == 3
    assert all(len(vector) == 2 for vector in vectors)
    assert all(np.linalg.norm(vector) == pytest.approx(1.0) for vector in vectors)
    assert cached == [vectors[0]]
    assert encoder.calls == [["same text", "another text"]]


def test_embedding_service_rejects_blank_input() -> None:
    service = EmbeddingService(Settings(), cache=MemoryCache(), model=FakeEncoder())
    with pytest.raises(ValueError, match="must not be blank"):
        service.embed_texts([""])


class FakeRanker:
    def __init__(self, scores: list[float]) -> None:
        self.scores = scores

    def predict(self, sentences, *, show_progress_bar: bool) -> np.ndarray:
        assert not show_progress_bar
        return np.asarray(self.scores, dtype=np.float32)


def _result(chunk_id: int, text: str, score: float, rank: int) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=chunk_id,
        text=text,
        document_id=1,
        page=chunk_id,
        page_end=chunk_id,
        section=None,
        score=score,
        rank=rank,
    )


def test_cross_encoder_reranker_reorders_fixture_and_preserves_scores() -> None:
    candidates = [
        _result(1, "weaker", 0.9, 1),
        _result(2, "stronger", 0.5, 2),
    ]
    reranker = CrossEncoderReranker(
        Settings(),
        model=FakeRanker([0.1, 0.95]),
    )

    outcome = reranker.rerank("query", candidates, 1)

    assert outcome.applied
    assert [item.chunk_id for item in outcome.results] == [2]
    assert outcome.results[0].original_score == 0.5
    assert outcome.results[0].rerank_score == pytest.approx(0.95)


def test_cross_encoder_scores_only_top_30_and_returns_top_5() -> None:
    class CandidateCountingRanker:
        def __init__(self) -> None:
            self.scored = 0

        def predict(
            self,
            sentences: list[tuple[str, str]],
            *,
            show_progress_bar: bool,
        ) -> np.ndarray:
            self.scored = len(sentences)
            return np.arange(len(sentences), dtype=np.float32)

    model = CandidateCountingRanker()
    candidates = [
        _result(index, f"candidate-{index}", 1 / index, index) for index in range(1, 36)
    ]

    outcome = CrossEncoderReranker(Settings(), model=model).rerank(
        "query", candidates, 5
    )

    assert model.scored == 30
    assert [item.chunk_id for item in outcome.results] == [30, 29, 28, 27, 26]


def test_cross_encoder_failure_keeps_original_order() -> None:
    def unavailable() -> FakeRanker:
        raise RuntimeError("model unavailable")

    candidates = [_result(1, "first", 0.8, 1), _result(2, "second", 0.7, 2)]
    outcome = CrossEncoderReranker(
        Settings(),
        model_factory=unavailable,
    ).rerank("query", candidates, 2)

    assert not outcome.applied
    assert outcome.error == "Cross-encoder reranking was unavailable."
    assert [item.chunk_id for item in outcome.results] == [1, 2]
    assert [item.original_score for item in outcome.results] == [0.8, 0.7]
    assert all(item.rerank_score is None for item in outcome.results)


class FixedScores:
    def __init__(self, scores: list[float]) -> None:
        self.scores = scores

    def score(self, query: str) -> list[float]:
        return self.scores


def test_hybrid_rrf_math_matches_hand_calculated_ranks() -> None:
    chunks = [
        ChunkRecord(index, f"chunk {index}", 100, index, index) for index in (1, 2, 3)
    ]
    retriever = HybridRetriever(
        chunks,
        user_id=77,
        dense_weight=0.75,
        rrf_k=10,
        dense_retriever=FixedScores([0.9, 0.1, 0.8]),  # type: ignore[arg-type]
        bm25_retriever=FixedScores([0.1, 1.0, 0.0]),  # type: ignore[arg-type]
    )

    scores = retriever.score("test")

    assert scores == pytest.approx(
        [
            0.75 / 11 + 0.25 / 12,
            0.75 / 13 + 0.25 / 11,
            0.75 / 12,
        ]
    )
    assert retriever.explain(1) == {
        "dense_rank": 1,
        "dense_score": 0.9,
        "bm25_rank": 2,
        "bm25_score": 0.1,
        "dense_rrf": 0.75 / 11,
        "bm25_rrf": 0.25 / 12,
    }


class TopicEncoder:
    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            normalized = text.lower()
            relevant = any(
                word in normalized
                for word in ("daylight", "leaves", "chlorophyll", "sunlight")
            )
            vectors.append([1.0, 0.0] if relevant else [0.0, 1.0])
        return vectors


def _add_search_document(db: Session, owner_id: int, title: str, text: str) -> Document:
    document = Document(owner_id=owner_id, title=title, status="ready")
    db.add(document)
    db.flush()
    db.add(
        Chunk(
            doc_id=document.id,
            page=1,
            page_start=1,
            page_end=1,
            chunk_index=0,
            text=text,
            token_count=len(text.split()),
        )
    )
    db.flush()
    return document


def test_dense_and_hybrid_search_are_scoped_and_explainable(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.retrieval.dense as dense_module

    owner = User(
        email="dense-owner@example.com",
        full_name="Dense Owner",
        password_hash="unused",
    )
    stranger = User(
        email="dense-stranger@example.com",
        full_name="Dense Stranger",
        password_hash="unused",
    )
    db_session.add_all([owner, stranger])
    db_session.flush()
    owned = _add_search_document(
        db_session,
        owner.id,
        "Owned biology",
        "Green plants use chlorophyll to transform sunlight into chemical energy.",
    )
    _add_search_document(
        db_session,
        owner.id,
        "Owned geology",
        "Volcanoes release magma, ash, and hot gases during eruptions.",
    )
    _add_search_document(
        db_session,
        stranger.id,
        "Private biology",
        "Green plants use chlorophyll to transform sunlight.",
    )
    db_session.commit()

    store = QdrantVectorStore(QdrantClient(":memory:"))
    monkeypatch.setattr(dense_module, "get_vector_store", lambda: store)
    monkeypatch.setattr(dense_module, "get_embedding_service", lambda: TopicEncoder())
    invalidate_retriever_cache("dense", owner.id, owned.id)
    invalidate_retriever_cache("hybrid", owner.id, owned.id)
    headers = {"Authorization": f"Bearer {access_token_for(owner.id)}"}

    for mode in ("dense", "hybrid"):
        response = client.post(
            "/search",
            headers=headers,
            json={
                "query": "How do leaves capture daylight and create fuel?",
                "mode": mode,
                "k": 5,
            },
        )
        assert response.status_code == 200
        result = response.json()["results"][0]
        assert result["document_id"] == owned.id
        assert result["page"] == 1
        assert result["score"] > 0
        if mode == "hybrid":
            assert result["components"]["dense_rank"] == 1
            assert result["components"]["bm25_rank"] is None


def test_search_reports_unreranked_fallback(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.routers.search as search_module

    owner = User(
        email="rerank-owner@example.com",
        full_name="Rerank Owner",
        password_hash="unused",
    )
    db_session.add(owner)
    db_session.flush()
    document = _add_search_document(
        db_session,
        owner.id,
        "Biology",
        "Green plants use sunlight and chlorophyll for photosynthesis.",
    )
    db_session.commit()

    def unavailable() -> FakeRanker:
        raise RuntimeError("cross encoder unavailable")

    monkeypatch.setattr(
        search_module,
        "get_cross_encoder_reranker",
        lambda: CrossEncoderReranker(Settings(), model_factory=unavailable),
    )
    response = client.post(
        "/search",
        headers={"Authorization": f"Bearer {access_token_for(owner.id)}"},
        json={"query": "photosynthesis", "mode": "bm25", "rerank": True},
    )

    assert response.status_code == 200
    result = response.json()
    assert not result["rerank_applied"]
    assert result["rerank_error"] == "Cross-encoder reranking was unavailable."
    assert result["results"][0]["document_id"] == document.id
    assert result["results"][0]["original_score"] == result["results"][0]["score"]
    assert result["results"][0]["rerank_score"] is None


def test_query_processing_noop_interfaces_preserve_query() -> None:
    query = "  preserve this exact query  "
    rewritten = NoOpQueryRewriter().rewrite(query)

    assert rewritten == query
    assert NoOpQueryExpander().expand(rewritten) == [query]


@pytest.mark.slow
@pytest.mark.skipif(
    not os.environ.get("RUN_MODEL_DOWNLOAD_TESTS"),
    reason="Enable RUN_MODEL_DOWNLOAD_TESTS=1 only when model downloads are available.",
)
def test_sentence_transformer_model_download_smoke() -> None:
    from app.services.embeddings import EmbeddingService

    vector = EmbeddingService().embed_texts(["small model download smoke test"])[0]

    assert len(vector) == 384
    assert np.linalg.norm(vector) == pytest.approx(1.0)
