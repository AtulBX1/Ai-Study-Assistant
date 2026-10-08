"""Unit tests for transformer utilities and owner-scoped endpoints."""

from types import SimpleNamespace

import pytest
import torch
from conftest import access_token_for
from fastapi.testclient import TestClient
from ml.transformers.ner.data import align_ner_labels
from sqlalchemy.orm import Session

from app.models import Chunk, Document, DocumentKeyTerm, DocumentPage, User
from app.services import transformer_inference as inference


class _Tokenizer:
    def __call__(self, *_args, **_kwargs):
        return {
            "input_ids": torch.tensor([[101, 1, 2, 102, 0]]),
            "attention_mask": torch.tensor([[1, 1, 1, 1, 0]]),
            "offset_mapping": torch.tensor([[[0, 0], [0, 5], [6, 10], [0, 0], [0, 0]]]),
        }

    def convert_ids_to_tokens(self, ids):
        return [f"tok-{token_id}" for token_id in ids]


class _QAModel:
    def __call__(self, **_kwargs):
        start = torch.tensor([[0.0, 10.0, 0.0, 0.0, 0.0]])
        end = torch.tensor([[0.0, 0.0, 10.0, 0.0, 0.0]])
        return SimpleNamespace(start_logits=start, end_logits=end)


def test_ner_alignment_labels_first_subtoken_only() -> None:
    assert align_ner_labels([None, 0, 0, 1, 1, None], [3, 4]) == [
        -100,
        3,
        -100,
        4,
        -100,
        -100,
    ]


def test_qa_span_extraction_preserves_offsets_and_no_answer_threshold(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        inference,
        "_load_qa",
        lambda: (_QAModel(), _Tokenizer(), torch.device("cpu")),
    )
    result = inference.answer_chunk("Where?", "Paris city!", 0.0)
    assert result["answer"] == "Paris city"
    assert (result["start_offset"], result["end_offset"]) == (0, 10)
    rejected = inference.answer_chunk("Where?", "Paris city!", 1.0)
    assert rejected["answer"] == "no answer found"
    assert rejected["found"] is False


def test_sinusoidal_encoding_shape_and_known_values() -> None:
    values = inference.sinusoidal_encoding(2, 4)
    assert len(values) == 2
    assert all(len(row) == 4 for row in values)
    assert values[0] == [0.0, 1.0, 0.0, 1.0]
    assert values[1][0] == pytest.approx(torch.sin(torch.tensor(1.0)).item())
    assert values[1][1] == pytest.approx(torch.cos(torch.tensor(1.0)).item())
    assert values[1][2] == pytest.approx(torch.sin(torch.tensor(0.01)).item())
    assert values[1][3] == pytest.approx(torch.cos(torch.tensor(0.01)).item())


def test_attention_output_shapes(monkeypatch) -> None:
    class AttentionTokenizer(_Tokenizer):
        def __call__(self, *_args, **_kwargs):
            return {
                "input_ids": torch.tensor([[101, 1, 2, 102]]),
                "attention_mask": torch.ones((1, 4), dtype=torch.long),
            }

        def convert_ids_to_tokens(self, ids):
            return [str(token_id) for token_id in ids]

    class AttentionModel:
        config = SimpleNamespace(n_heads=3)

        def __call__(self, **_kwargs):
            matrices = tuple(torch.ones((1, 3, 4, 4)) for _ in range(2))
            return SimpleNamespace(attentions=matrices)

    monkeypatch.setattr(
        inference,
        "_load_attention_model",
        lambda: (AttentionModel(), AttentionTokenizer(), torch.device("cpu")),
    )
    output = inference.attention_weights("A test sentence.")
    assert output["shape"] == [2, 3, 4, 4]
    assert len(output["layers"]) == 2
    assert len(output["layers"][0]) == 3
    assert len(output["layers"][0][0]) == 4
    assert len(output["tokens"]) == 4


def test_tokenizer_comparison_returns_tokens_ids_and_counts(monkeypatch) -> None:
    class LabTokenizer:
        def __call__(self, *_args, **_kwargs):
            return {"input_ids": [11, 12]}

        def convert_ids_to_tokens(self, ids):
            return ["rare", "emoji"][: len(ids)]

    monkeypatch.setattr(
        inference,
        "_load_tokenizers",
        lambda: (LabTokenizer(), LabTokenizer(), LabTokenizer()),
    )
    result = inference.tokenizer_lab("rare word and emoji")
    assert set(result) == {
        "gpt2_bpe",
        "distilbert_wordpiece",
        "t5_sentencepiece",
    }
    for tokenizer_output in result.values():
        assert tokenizer_output["tokens"] == ["rare", "emoji"]
        assert tokenizer_output["ids"] == [11, 12]
        assert tokenizer_output["token_count"] == 2
        assert tokenizer_output["rare_oov"]
        assert tokenizer_output["numbers"]
        assert tokenizer_output["emoji"]


def test_missing_weights_fail_lazily_with_clear_message(tmp_path, monkeypatch) -> None:
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    monkeypatch.setattr(inference, "MODEL_ROOT", tmp_path)
    inference._load_qa.cache_clear()
    with pytest.raises(FileNotFoundError, match="not trained yet"):
        inference._load_qa()
    inference._load_qa.cache_clear()


def test_qa_endpoint_does_not_retrieve_another_users_document(
    client: TestClient, db_session: Session, monkeypatch
) -> None:
    owner = User(
        email="transformer-owner@example.test",
        full_name="Owner",
        password_hash="test-password-hash",
    )
    other = User(
        email="transformer-other@example.test",
        full_name="Other",
        password_hash="test-password-hash",
    )
    db_session.add_all([owner, other])
    db_session.flush()
    document = Document(owner_id=owner.id, title="private.pdf", status="ready")
    db_session.add(document)
    db_session.flush()
    db_session.add(
        Chunk(
            doc_id=document.id,
            page=1,
            page_start=1,
            page_end=1,
            text="private study content",
            chunk_index=0,
        )
    )
    db_session.commit()
    monkeypatch.setattr(
        inference,
        "answer_chunk",
        lambda *_args: (_ for _ in ()).throw(AssertionError("must not infer")),
    )
    response = client.post(
        "/lab/qa/extractive",
        json={"question": "What is private?", "doc_ids": [document.id]},
        headers={"Authorization": f"Bearer {access_token_for(other.id)}"},
    )
    assert response.status_code == 404


def test_document_key_terms_persist_tfidf_terms(
    client: TestClient, db_session: Session, monkeypatch
) -> None:
    user = User(
        email="transformer-keyterms@example.test",
        full_name="Key Terms",
        password_hash="test-password-hash",
    )
    db_session.add(user)
    db_session.flush()
    document = Document(owner_id=user.id, title="terms.pdf", status="ready")
    db_session.add(document)
    db_session.flush()
    db_session.add(
        DocumentPage(
            document_id=document.id,
            page_number=1,
            text="Transformers use attention mechanisms and token embeddings.",
            cleaned_text="Transformers use attention mechanisms and token embeddings.",
        )
    )
    db_session.commit()
    monkeypatch.setattr(inference, "extract_entities", lambda _text: [])
    response = client.post(
        f"/documents/{document.id}/key-terms?top_n=2",
        headers={"Authorization": f"Bearer {access_token_for(user.id)}"},
    )
    assert response.status_code == 200
    assert response.json()["stored_terms"] == 2
    stored = list(
        db_session.query(DocumentKeyTerm).filter_by(document_id=document.id).all()
    )
    assert {row.label for row in stored} == {"KEYPHRASE"}
    assert all(row.source == "keyphrase" for row in stored)
