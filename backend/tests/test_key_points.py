"""Fake-only checks for grounded document key points."""

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import Document, DocumentPage, User
from app.services.study.key_points import generate_key_points, validate_items
from app.services.study.summaries import DocumentSection
from tests.conftest import access_token_for


@pytest.fixture(autouse=True)
def block_t5_weights(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.services.study.summaries.T5_WEIGHTS_DIR", tmp_path / "none"
    )


class FakeProvider:
    name = "fake"
    is_external = False

    def __init__(self, answer):
        self.answer = answer
        self.calls = 0

    def generate(self, prompt, system_prompt=None):
        self.calls += 1
        return self.answer


def test_evidence_items_without_exact_source_sentence_are_rejected():
    section = DocumentSection(
        "s",
        "Chapter",
        2,
        2,
        "Alpha is a grounded sentence.",
        [(2, "Alpha is a grounded sentence.")],
    )
    accepted = validate_items(
        [
            {"text": "Grounded", "evidence_sentence": "Alpha is a grounded sentence."},
            {"text": "Invented", "evidence_sentence": "This is not in the document."},
        ],
        section,
    )
    assert accepted == [
        {
            "text": "Grounded",
            "evidence_sentence": "Alpha is a grounded sentence.",
            "page": 2,
        }
    ]


def test_provider_failure_falls_back_to_extractive_source_items(db_session):
    user = User(
        email="keypoints@example.test", full_name="Key Points", password_hash="unused"
    )
    db_session.add(user)
    db_session.flush()
    document = Document(
        owner_id=user.id, title="Notes.pdf", status="ready", is_private=False
    )
    db_session.add(document)
    db_session.flush()
    text = "The system stores every valid observation for later analysis. " * 9
    db_session.add(
        DocumentPage(
            document_id=document.id,
            page_number=1,
            text=text,
            cleaned_text=text,
            headings=[],
        )
    )
    db_session.flush()
    provider = FakeProvider("not json")
    result = generate_key_points(db_session, document, "llm", provider)
    assert provider.calls == 1
    assert result["engine_used"] == "extractive"
    assert result["sections"][0]["items"][0]["evidence_sentence"] in text


def test_key_points_cache_is_reused_per_document_and_engine(
    client, db_session, test_engine, monkeypatch
):
    monkeypatch.setattr(
        "app.routers.documents.SessionLocal",
        sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False),
    )
    user = User(
        email="keypoints-cache@example.test", full_name="Cache", password_hash="unused"
    )
    db_session.add(user)
    db_session.flush()
    document = Document(
        owner_id=user.id, title="Cache.pdf", status="ready", is_private=False
    )
    db_session.add(document)
    db_session.flush()
    text = "Caching stores stable generated output for repeated calls. " * 8
    db_session.add(
        DocumentPage(
            document_id=document.id,
            page_number=1,
            text=text,
            cleaned_text=text,
            headings=[],
        )
    )
    db_session.commit()
    headers = {"Authorization": f"Bearer {access_token_for(user.id)}"}
    first = client.post(
        f"/documents/{document.id}/key-points?engine=extractive", headers=headers
    )
    assert first.json()["status"] == "queued"
    completed = client.get(
        f"/documents/{document.id}/key-points?job_id={first.json()['job_id']}",
        headers=headers,
    )
    assert completed.json()["status"] == "complete", completed.json()
    second = client.post(
        f"/documents/{document.id}/key-points?engine=extractive", headers=headers
    )
    assert second.json()["status"] == "complete"
    assert second.json()["result"]["id"] == completed.json()["result"]["id"]
