"""Authenticated, owner-scoped seq2seq endpoint tests."""

import json
from pathlib import Path

import pytest
import torch
from conftest import access_token_for
from fastapi.testclient import TestClient
from ml.seq2seq.models import Seq2SeqConfig, SequenceToSequence
from ml.seq2seq.vocabulary import EOS_ID, Seq2SeqVocabulary
from sqlalchemy.orm import Session

from app.core.cache import MemoryCache
from app.middleware import RateLimitMiddleware
from app.models import Document, DocumentPage, User
from app.routers import lab
from app.services import seq2seq_inference


@pytest.fixture(autouse=True)
def isolate_test_rate_limit(client: TestClient):
    middleware = client.app.middleware_stack
    while middleware is not None and not isinstance(middleware, RateLimitMiddleware):
        middleware = getattr(middleware, "app", None)
    assert isinstance(middleware, RateLimitMiddleware)
    assert isinstance(middleware.cache, MemoryCache)
    middleware.cache._counters.clear()
    yield
    middleware.cache._counters.clear()


def _user(db: Session, email: str) -> User:
    user = User(
        email=email,
        full_name="Seq2seq Endpoint",
        password_hash="test-password-hash",
    )
    db.add(user)
    db.flush()
    return user


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token_for(user.id)}"}


def test_summarize_endpoint_uses_fixture_and_returns_attention(
    client: TestClient, db_session: Session, tmp_path: Path, monkeypatch
) -> None:
    user = _user(db_session, "seq2seq-api@example.test")
    document = Document(owner_id=user.id, title="fixture.pdf", status="ready")
    db_session.add(document)
    db_session.flush()
    db_session.add(
        DocumentPage(
            document_id=document.id,
            page_number=2,
            text="fixture source",
            cleaned_text="fixture source",
        )
    )
    db_session.commit()
    vocabulary = Seq2SeqVocabulary.build(
        ["fixture source"], min_frequency=1, max_size=12
    )
    config = Seq2SeqConfig(
        vocab_size=len(vocabulary),
        embedding_dim=8,
        hidden_size=8,
        dropout=0,
        attention="bahdanau",
        max_source_length=8,
        max_target_length=5,
    )
    model = SequenceToSequence(config)
    with torch.no_grad():
        for parameter in model.parameters():
            parameter.zero_()
        model.output_projection.bias.fill_(-20)
        model.output_projection.bias[vocabulary.token_to_id["fixture"]] = 10
        model.output_projection.bias[EOS_ID] = 0
    checkpoint_path = tmp_path / "models" / "seq2seq" / "bahdanau.pt"
    checkpoint_path.parent.mkdir(parents=True)
    torch.save(
        {
            "config": config.to_dict(),
            "vocabulary": vocabulary.to_dict(),
            "model": model.state_dict(),
        },
        checkpoint_path,
    )
    monkeypatch.setattr(seq2seq_inference, "ROOT", tmp_path)
    seq2seq_inference.clear_model_cache()
    response = client.post(
        "/lab/summarize/seq2seq",
        json={
            "document_id": document.id,
            "page_start": 2,
            "page_end": 2,
            "model": "bahdanau",
            "decoding": "greedy",
        },
        headers=_headers(user),
    )
    assert response.status_code == 200
    assert response.json()["summary"] == "fixture fixture fixture"
    assert len(response.json()["attention_matrix"]) == 2
    assert len(response.json()["attention_matrix"][0]) == 3
    assert response.json()["source"] == {
        "document_id": document.id,
        "pages": [2],
    }
    seq2seq_inference.clear_model_cache()


def test_untrained_summary_returns_clear_service_error(
    client: TestClient, db_session: Session, monkeypatch
) -> None:
    user = _user(db_session, "seq2seq-missing@example.test")

    def missing(*_args):
        raise FileNotFoundError("No trained bahdanau seq2seq weights are available.")

    monkeypatch.setattr(lab, "_seq2seq_summary", missing)
    response = client.post(
        "/lab/summarize/seq2seq",
        json={"text": "a source sentence", "model": "bahdanau"},
        headers=_headers(user),
    )
    assert response.status_code == 503
    assert "No trained bahdanau seq2seq weights" in response.json()["detail"]


def test_document_summarization_enforces_ownership_before_inference(
    client: TestClient, db_session: Session, monkeypatch
) -> None:
    owner = _user(db_session, "seq2seq-owner@example.test")
    other_user = _user(db_session, "seq2seq-other@example.test")
    document = Document(owner_id=owner.id, title="private.pdf", status="ready")
    db_session.add(document)
    db_session.flush()
    db_session.add(
        DocumentPage(
            document_id=document.id,
            page_number=1,
            text="private source text",
            cleaned_text="private source text",
        )
    )
    db_session.commit()
    monkeypatch.setattr(
        lab,
        "_seq2seq_summary",
        lambda *_args: (_ for _ in ()).throw(AssertionError("must not infer")),
    )
    response = client.post(
        "/lab/summarize/seq2seq",
        json={"document_id": document.id, "page_start": 1, "page_end": 1},
        headers=_headers(other_user),
    )
    assert response.status_code == 404


def test_results_endpoint_reads_stored_table(
    client: TestClient, db_session: Session, tmp_path: Path, monkeypatch
) -> None:
    user = _user(db_session, "seq2seq-results@example.test")
    model_dir = tmp_path / "models" / "seq2seq"
    model_dir.mkdir(parents=True)
    expected = {"models": {"bahdanau": {"metrics": {"greedy": {"rouge1": 0.5}}}}}
    (model_dir / "evaluation.json").write_text(json.dumps(expected), encoding="utf-8")
    monkeypatch.setattr(lab, "PROJECT_ROOT", tmp_path)
    response = client.get("/lab/seq2seq/results", headers=_headers(user))
    assert response.status_code == 200
    assert response.json() == expected
