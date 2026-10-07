"""Authenticated API coverage for lazy sequence-model predictions."""

from pathlib import Path

import pytest
import torch
from conftest import access_token_for
from fastapi.testclient import TestClient
from ml.sequence_models.data import save_inference_artifact
from ml.sequence_models.models import SequenceClassifier
from ml.sequence_models.vocabulary import Vocabulary
from sqlalchemy.orm import Session

from app.models import Chunk, Document, User
from app.routers import lab


def _user(db_session: Session) -> User:
    user = User(
        email="sequence-test@example.test",
        full_name="Sequence Test",
        password_hash="test-password-hash",
    )
    db_session.add(user)
    db_session.flush()
    return user


def _artifact(root: Path, task: str, architecture: str) -> Path:
    vocabulary = Vocabulary.build(
        ["a helpful positive review", "a difficult technical topic"],
        min_frequency=1,
    )
    classes = (
        ["negative", "positive"] if task == "sentiment" else ["easy", "medium", "hard"]
    )
    model = SequenceClassifier(
        len(vocabulary),
        len(classes),
        architecture=architecture,  # type: ignore[arg-type]
        embedding_dim=8,
        hidden_size=8,
    )
    path = root / task / f"{architecture}.pt"
    save_inference_artifact(
        path,
        model,
        architecture,
        vocabulary.to_dict(),
        classes,
        {"embedding_dim": 8, "hidden_size": 8, "num_layers": 1, "dropout": 0.0},
        32,
    )
    return path


def test_classify_endpoint_loads_fixture_model(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    monkeypatch,
) -> None:
    user = _user(db_session)
    predictor_path = _artifact(tmp_path, "sentiment", "lstm")
    from ml.sequence_models.inference import SequencePredictor

    predictor = SequencePredictor(predictor_path, device=torch.device("cpu"))
    monkeypatch.setattr(lab, "_sequence_predictor", lambda _task, _model: predictor)
    response = client.post(
        "/lab/classify",
        json={
            "text": "a helpful positive review",
            "task": "sentiment",
            "model": "lstm",
        },
        headers={"Authorization": f"Bearer {access_token_for(user.id)}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["task"] == "sentiment"
    assert body["model"] == "lstm"
    assert body["label"] in {"negative", "positive"}
    assert set(body["probabilities"]) == {"negative", "positive"}
    assert sum(body["probabilities"].values()) == pytest.approx(1.0)


def test_untrained_model_returns_clear_service_error(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    user = _user(db_session)

    def missing_model(*_args):
        raise FileNotFoundError("No trained lstm weights are available for sentiment.")

    monkeypatch.setattr(lab, "_sequence_predictor", missing_model)
    response = client.post(
        "/lab/classify",
        json={"text": "hello", "task": "sentiment", "model": "lstm"},
        headers={"Authorization": f"Bearer {access_token_for(user.id)}"},
    )
    assert response.status_code == 503
    assert "No trained lstm weights" in response.json()["detail"]


def test_batch_endpoint_stores_labels_on_owned_chunks(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    user = _user(db_session)
    document = Document(owner_id=user.id, title="notes.pdf", status="ready")
    db_session.add(document)
    db_session.flush()
    chunk = Chunk(
        doc_id=document.id,
        page=1,
        page_start=1,
        page_end=1,
        text="a difficult technical topic",
        token_count=4,
        chunk_index=0,
    )
    db_session.add(chunk)
    db_session.commit()

    class Predictor:
        def predict(self, _text: str) -> dict[str, object]:
            return {
                "label": "hard",
                "confidence": 0.8,
                "probabilities": {"easy": 0.1, "medium": 0.1, "hard": 0.8},
            }

    monkeypatch.setattr(lab, "_sequence_predictor", lambda *_args: Predictor())
    response = client.post(
        "/lab/difficulty/batch",
        json={"document_id": document.id},
        headers={"Authorization": f"Bearer {access_token_for(user.id)}"},
    )
    assert response.status_code == 200
    assert response.json()["tagged_chunks"] == 1
    db_session.refresh(chunk)
    assert chunk.difficulty_label == "hard"
    assert chunk.difficulty_confidence == 0.8
    assert chunk.difficulty_model == "lstm"
