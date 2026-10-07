"""Word2Vec training and authenticated embedding lab API tests."""

import numpy as np
import pytest
from conftest import access_token_for

from app.models import Chunk, Document, User
from app.nlp import embeddings_classic
from app.retrieval.base import ChunkRecord


def _records(document_id: int = 1) -> list[ChunkRecord]:
    return [
        ChunkRecord(
            index,
            text,
            document_id,
            index,
            index,
        )
        for index, text in enumerate(
            [
                "king queen royal crown kingdom",
                "man woman king queen person",
                "king royal ruler throne kingdom",
                "queen woman royal crown ruler",
                "biology cell gene protein organism",
                "cell gene biology organism protein",
            ],
            start=1,
        )
    ]


def _add_document(db_session, owner_id: int, text: str) -> Document:
    document = Document(owner_id=owner_id, title="Embedding notes", status="ready")
    db_session.add(document)
    db_session.flush()
    db_session.add(
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
    db_session.flush()
    return document


def _headers(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token_for(user_id)}"}


def test_cbow_and_skipgram_save_distinct_models(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(embeddings_classic, "WORD2VEC_ROOT", tmp_path)
    cbow = embeddings_classic.train_word2vec(
        _records(), 10, 1, "cbow", vector_size=20, epochs=10
    )
    skipgram = embeddings_classic.train_word2vec(
        _records(), 10, 1, "skipgram", vector_size=20, epochs=10
    )

    cbow_vectors = embeddings_classic.load_word2vec(10, 1, "cbow")
    skipgram_vectors = embeddings_classic.load_word2vec(10, 1, "skipgram")
    assert cbow["vocab_size"] == skipgram["vocab_size"] > 5
    assert cbow["saved"] and skipgram["saved"]
    cbow_path = embeddings_classic.model_path(10, 1, "cbow")
    skipgram_path = embeddings_classic.model_path(10, 1, "skipgram")
    assert cbow_path != skipgram_path
    assert not np.array_equal(cbow_vectors["king"], skipgram_vectors["king"])


def test_tiny_corpus_warns_and_empty_vocabulary_does_not_crash(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(embeddings_classic, "WORD2VEC_ROOT", tmp_path)
    with pytest.warns(RuntimeWarning, match="too small"):
        result = embeddings_classic.train_word2vec(
            [ChunkRecord(1, "singular", 1, 1, 1)],
            1,
            1,
            "cbow",
            vector_size=10,
            epochs=1,
        )
    assert result["vocab_size"] == 1
    assert result["saved"] is True
    with pytest.warns(RuntimeWarning, match="No tokens"):
        empty = embeddings_classic.train_word2vec(
            [ChunkRecord(2, "and the", 1, 1, 1)],
            2,
            2,
            "cbow",
            vector_size=10,
            epochs=1,
        )
    assert empty["saved"] is False


def test_projection_returns_two_and_three_dimensional_coordinates(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(embeddings_classic, "WORD2VEC_ROOT", tmp_path)
    embeddings_classic.train_word2vec(
        _records(), 10, 1, "cbow", vector_size=10, epochs=2
    )
    vectors = embeddings_classic.load_word2vec(10, 1, "cbow")
    for method in ("pca", "tsne"):
        for dimensions in (2, 3):
            projection = embeddings_classic.project_vectors(
                vectors, method, dimensions, top_n=10
            )
            assert len(projection["coordinates"]) == 10
            assert len(projection["labels"]) == len(projection["cluster_ids"]) == 10
            assert all(
                len(row["coordinates"]) == dimensions
                for row in projection["coordinates"]
            )


@pytest.mark.skipif(
    not (embeddings_classic.GLOVE_ROOT / embeddings_classic.GLOVE_NAME).exists(),
    reason="Download the selected GloVe model explicitly to run this slow test.",
)
@pytest.mark.slow
def test_downloaded_glove_analogy() -> None:
    vectors = embeddings_classic.load_glove()
    result = embeddings_classic.solve_analogy(vectors, "king", "man", "woman", topn=5)
    assert result
    assert all("word" in candidate and "score" in candidate for candidate in result)


def test_similar_words_oov_analogy_projection_and_ownership(
    client, db_session, monkeypatch
) -> None:
    owner = User(
        email="embeddings-owner@example.com",
        full_name="Embedding Owner",
        password_hash="unused",
    )
    stranger = User(
        email="embeddings-stranger@example.com",
        full_name="Embedding Stranger",
        password_hash="unused",
    )
    db_session.add_all([owner, stranger])
    db_session.flush()
    document = _add_document(
        db_session,
        owner.id,
        "king man woman queen royal kingdom",
    )
    foreign_document = _add_document(
        db_session,
        stranger.id,
        "king man woman queen royal kingdom",
    )
    db_session.commit()

    class FakeVectors:
        index_to_key = ["king", "queen", "man", "woman", "royal", "kingdom"]
        vectors = {}

        def __contains__(self, word):
            return word in self.vectors

        def __getitem__(self, word):
            return self.vectors[word]

        def most_similar(self, positive, negative=None, topn=10):
            if isinstance(positive, str):
                excluded = {positive}
            else:
                excluded = set(positive) | set(negative or [])
            return [
                (word, 0.9 - index / 10)
                for index, word in enumerate(self.index_to_key)
                if word not in excluded
            ][:topn]

        def similarity(self, first, second):
            return 0.75

    FakeVectors.vectors = {
        word: np.asarray([float(index + 1), float(index % 2)], dtype=np.float32)
        for index, word in enumerate(FakeVectors.index_to_key)
    }

    monkeypatch.setattr(
        "app.routers.lab.keyed_vectors",
        lambda model, user_id, document_id: FakeVectors(),
    )
    headers = _headers(owner.id)

    similar = client.get(
        "/lab/embeddings/similar",
        headers=headers,
        params={"document_id": document.id, "word": "king", "model": "glove"},
    )
    assert similar.status_code == 200
    assert similar.json()["similar"][0] == {"word": "queen", "score": 0.8}

    oov = client.get(
        "/lab/embeddings/similar",
        headers=headers,
        params={"document_id": document.id, "word": "kng", "model": "glove"},
    )
    assert oov.status_code == 404
    assert oov.json()["detail"]["suggestion"] == "king"

    analogy = client.get(
        "/lab/embeddings/analogy",
        headers=headers,
        params={"a": "king", "b": "man", "c": "woman", "model": "glove"},
    )
    assert analogy.status_code == 200
    assert analogy.json()["expression"] == "king - man + woman"
    assert analogy.json()["candidates"]

    similarity = client.get(
        "/lab/embeddings/similarity",
        headers=headers,
        params={"w1": "king", "w2": "queen", "model": "glove"},
    )
    assert similarity.status_code == 200
    assert similarity.json()["cosine_similarity"] == 0.75

    monkeypatch.setattr(
        "app.routers.lab.project_vectors",
        lambda vectors, method, dims, top_n: {
            "coordinates": [
                {"word": "king", "coordinates": [1.0, 2.0]},
                {"word": "queen", "coordinates": [2.0, 1.0]},
            ],
            "labels": ["king", "queen"],
            "cluster_ids": [0, 1],
        },
    )
    projection = client.get(
        "/lab/embeddings/projection",
        headers=headers,
        params={"document_id": document.id, "model": "glove", "dims": 2},
    )
    assert projection.status_code == 200
    assert all(len(row["coordinates"]) == 2 for row in projection.json()["coordinates"])

    denied = client.get(
        "/lab/embeddings/similar",
        headers=headers,
        params={
            "document_id": foreign_document.id,
            "word": "king",
            "model": "glove",
        },
    )
    assert denied.status_code == 404


def test_word2vec_training_endpoint_and_retrieval_search(
    client, db_session, monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(embeddings_classic, "WORD2VEC_ROOT", tmp_path)
    owner = User(
        email="word2vec-search@example.com",
        full_name="Word2Vec Search",
        password_hash="unused",
    )
    stranger = User(
        email="word2vec-stranger@example.com",
        full_name="Word2Vec Stranger",
        password_hash="unused",
    )
    db_session.add_all([owner, stranger])
    db_session.flush()
    document = _add_document(
        db_session,
        owner.id,
        "photosynthesis chlorophyll sunlight plants energy green pigment",
    )
    foreign_document = _add_document(
        db_session,
        stranger.id,
        "photosynthesis chlorophyll sunlight plants energy green pigment",
    )
    db_session.commit()
    headers = _headers(owner.id)

    trained = client.post(
        "/lab/word2vec/train",
        headers=headers,
        json={
            "document_id": document.id,
            "architecture": "cbow",
            "vector_size": 20,
            "window": 3,
            "min_count": 1,
            "epochs": 10,
        },
    )
    assert trained.status_code == 200
    assert trained.json()["vocab_size"] > 3
    assert trained.json()["training_time_seconds"] >= 0

    results = client.post(
        "/search",
        headers=headers,
        json={
            "query": "photosynthesis chlorophyll",
            "mode": "word2vec",
            "doc_ids": [document.id],
        },
    )
    assert results.status_code == 200
    assert results.json()["results"][0]["document_id"] == document.id
    assert results.json()["results"][0]["score"] > 0

    denied = client.post(
        "/lab/word2vec/train",
        headers=headers,
        json={"document_id": foreign_document.id, "architecture": "cbow"},
    )
    assert denied.status_code == 404
