"""CI-safe tests for Step 11b grounding and the local generation lab."""

import json

from conftest import access_token_for
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.models import Chunk, Document, Message, User
from app.routers.chat import get_rag_pipeline
from app.services.rag import (
    AnswerCache,
    FakeProvider,
    RAGChatPipeline,
    RateLimiter,
    local_generation,
)
from app.services.rag.grounding import evaluate_grounding


def _header(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token_for(user_id)}"}


def _user_doc(db_session, email: str) -> tuple[User, int]:
    user = User(email=email, full_name="Grounding test", password_hash="x")
    db_session.add(user)
    db_session.flush()
    document = Document(owner_id=user.id, title="notes.pdf", status="ready")
    db_session.add(document)
    db_session.flush()
    chunk = Chunk(
        doc_id=document.id,
        page=1,
        page_start=1,
        page_end=1,
        section="NLP",
        text=(
            "NLP is the branch of AI concerned with understanding, interpreting, "
            "and generating human language."
        ),
        token_count=16,
        chunk_index=0,
    )
    db_session.add(chunk)
    db_session.flush()
    return user, chunk.id


def _retriever(score: float):
    def retrieve(db, user_id, query, doc_ids=None, top_k=5):
        doc = db.scalar(select(Document).where(Document.owner_id == user_id))
        if doc is None:
            return [], False
        chunk = db.scalar(select(Chunk).where(Chunk.doc_id == doc.id))
        if chunk is None:
            return [], False
        return [
            {
                "chunk_id": chunk.id,
                "document_id": doc.id,
                "document_title": doc.title,
                "page": chunk.page,
                "text": chunk.text,
                "is_private": False,
                "retrieval_score": 0.8,
                "rerank_score": score,
                "score_components": {"dense_score": 0.8},
            }
        ], False

    return retrieve


def _pipe(response: str, score: float = 0.9) -> RAGChatPipeline:
    return RAGChatPipeline(
        provider=FakeProvider(response_text=response),
        rate_limiter=RateLimiter(requests_per_minute=100),
        cache=AnswerCache(),
        context_retriever=_retriever(score),
        settings=Settings(
            gemini_api_key="valid-key",
            rag_retrieval_confidence_threshold=0.5,
            hf_home="/no/local/model",
        ),
    )


def _events(response_text: str) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in response_text.splitlines()
        if line.startswith("data: ")
    ]


def test_refuses_when_top_rerank_score_is_below_threshold(
    client: TestClient, db_session
) -> None:
    user, _ = _user_doc(db_session, "low-score@example.com")
    client.app.dependency_overrides[get_rag_pipeline] = lambda: _pipe(
        "Never generated", 0.2
    )
    session = client.post("/chat/sessions", headers=_header(user.id), json={}).json()
    response = client.post(
        f"/chat/sessions/{session['id']}/messages",
        headers=_header(user.id),
        json={"query": "Explain NLP"},
    )
    events = _events(response.text)
    assert events[-1]["done"] is True
    assert "not found in the document" in [event.get("token") for event in events]
    saved = db_session.scalar(select(Message).where(Message.role == "assistant"))
    assert saved.content == "not found in the document"
    client.app.dependency_overrides.clear()


def test_grounding_scores_supported_and_flags_unsupported_sentence() -> None:
    chunks = [
        {
            "chunk_id": 1,
            "text": (
                "NLP is the branch of AI concerned with understanding human language."
            ),
        }
    ]
    result = evaluate_grounding(
        "NLP is the branch of AI concerned with understanding human language. "
        "NLP was invented on Mars in 2088.",
        chunks,
        Settings(hf_home="/missing-embeddings", rag_grounding_sentence_threshold=0.45),
    )
    assert result["grounding_score"] == 0.5
    assert result["unsupported_sentences"] == ["NLP was invented on Mars in 2088."]
    assert result["chunks"][0]["used_sentences"]
    assert result["chunks"][0]["highlight_offsets"]


def test_chat_explanation_metadata_and_owner_isolation(
    client: TestClient, db_session
) -> None:
    owner, chunk_id = _user_doc(db_session, "explanation-owner@example.com")
    other = User(
        email="explanation-other@example.com", full_name="Other", password_hash="x"
    )
    db_session.add(other)
    db_session.commit()
    client.app.dependency_overrides[get_rag_pipeline] = lambda: _pipe(
        "NLP is the branch of AI concerned with understanding human language. "
        "[notes.pdf, p.1]"
    )
    session = client.post("/chat/sessions", headers=_header(owner.id), json={}).json()
    response = client.post(
        f"/chat/sessions/{session['id']}/messages",
        headers=_header(owner.id),
        json={"query": "What is NLP?", "mode": "simple"},
    )
    done = _events(response.text)[-1]
    explanation = done["explanation"]
    assert explanation["provider"] == done["provider"]
    assert explanation["mode"] == "simple"
    assert explanation["latency_ms"] >= 0
    assert explanation["chunks"][0]["chunk_id"] == chunk_id
    assert explanation["chunks"][0]["retrieval_score"] == 0.8
    assert "rerank_score" in explanation["chunks"][0]
    assert done["grounding_score"] == 1.0
    assert (
        client.get(
            f"/chat/sessions/{session['id']}", headers=_header(other.id)
        ).status_code
        == 404
    )
    client.app.dependency_overrides.clear()


def test_local_lab_routes_use_fake_model(
    client: TestClient, db_session, monkeypatch
) -> None:
    user, _ = _user_doc(db_session, "lab-user@example.com")

    from app.routers import rag_playground

    monkeypatch.setattr(
        rag_playground,
        "_generate_side_by_side",
        lambda prompt, settings: {
            "model": "distilgpt2",
            "results": [
                {
                    "setting": settings[0],
                    "text": "tiny",
                    "tokens": [{"token": "tiny", "probability": 0.75}],
                }
            ],
        },
    )
    monkeypatch.setattr(
        rag_playground,
        "_calculate_perplexity",
        lambda text: {
            "model": "distilgpt2",
            "token_count": 2,
            "perplexity": 2.5,
        },
    )
    headers = _header(user.id)
    generated = client.post(
        "/lab/generate",
        headers=headers,
        json={
            "prompt": "Hello",
            "settings": [{"strategy": "greedy", "max_new_tokens": 1}],
        },
    )
    assert generated.status_code == 200
    assert generated.json()["results"][0]["tokens"][0]["probability"] == 0.75
    from app.routers.rag_playground import get_current_user

    client.app.dependency_overrides[get_current_user] = lambda: user
    perplexity = client.post("/lab/perplexity", json={"text": "Hello world"})
    assert perplexity.status_code == 200
    assert perplexity.json()["perplexity"] == 2.5
    client.app.dependency_overrides.clear()


def test_missing_local_weights_return_clear_message(
    client: TestClient, db_session, monkeypatch
) -> None:
    user, _ = _user_doc(db_session, "lab-missing@example.com")

    def missing(*args, **kwargs):
        raise FileNotFoundError("Local distilgpt2 weights are not cached.")

    from app.routers import rag_playground

    monkeypatch.setattr(rag_playground, "_generate_side_by_side", missing)
    response = client.post(
        "/lab/generate",
        headers=_header(user.id),
        json={
            "prompt": "Try local model",
            "settings": [{"strategy": "greedy", "max_new_tokens": 1}],
        },
    )
    assert response.status_code == 503
    assert "weights are not cached" in response.json()["detail"]


def test_local_playground_settings_and_probabilities_with_tiny_model(
    monkeypatch,
) -> None:
    class TinyTensor:
        def __init__(self, values):
            self.values = values

        def __getitem__(self, item):
            if item == (0, -1, slice(None)):
                return TinyTensor([1.0, 3.0, 0.5])
            return self.values[item]

        def detach(self):
            return self

        def float(self):
            return self

        def cpu(self):
            return self

        def tolist(self):
            return self.values

    class TinyModel:
        def __call__(self, input_ids):
            return type("Output", (), {"logits": TinyTensor([[0, 0, 0]])})()

    class TinyTokenizer:
        eos_token_id = None

        def __call__(self, text, return_tensors):
            return {"input_ids": [[0]]}

        def decode(self, ids, skip_special_tokens=True):
            return "x" * len(ids)

    class TinyTorch:
        class inference_mode:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        @staticmethod
        def multinomial(probabilities, num_samples):
            return type("Sample", (), {"item": lambda self: 1})()

        @staticmethod
        def tensor(values):
            return values

    monkeypatch.setattr(
        local_generation,
        "_load_local_model",
        lambda *args: (TinyModel(), TinyTokenizer(), TinyTorch),
    )
    result = local_generation.generate_side_by_side(
        "hi",
        [
            {
                "strategy": "greedy",
                "max_new_tokens": 1,
                "num_beams": 2,
                "top_k": 2,
                "top_p": 0.9,
                "temperature": 1.0,
                "repetition_penalty": 1.0,
            }
        ],
        Settings(hf_home="/fake"),
    )
    assert result["results"][0]["text"] == "x"
    assert 0 < result["results"][0]["tokens"][0]["probability"] <= 1
