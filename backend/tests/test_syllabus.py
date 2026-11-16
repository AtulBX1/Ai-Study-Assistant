"""Deterministic tests for syllabus parsing, mapping, and private access."""

from conftest import access_token_for

from app.models import (
    Chunk,
    ChunkTopic,
    Document,
    DocumentPage,
    Syllabus,
    SyllabusTopic,
    User,
)
from app.services.syllabus import coverage, parse_syllabus, remap_syllabus


class FakeEmbedder:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            value = text.casefold()
            vectors.append(
                [1.0, 0.0]
                if "calculus" in value or "derivative" in value
                else [0.0, 1.0]
            )
        return vectors


def test_parse_nested_numbering_bullets_and_comma_subtopics():
    parsed = parse_syllabus(
        """Unit I: Mathematics
1. Calculus, limits; derivatives
1.1 Differential calculus
- Chain rule
2. Algebra
"""
    )
    assert parsed[0]["title"] == "Mathematics"
    assert parsed[0]["children"][0]["title"] == "Calculus"
    assert parsed[0]["children"][0]["sub_topics"] == ["limits", "derivatives"]
    assert parsed[0]["children"][0]["children"][0]["title"] == "Differential calculus"
    assert (
        parsed[0]["children"][0]["children"][0]["children"][0]["title"] == "Chain rule"
    )
    assert parsed[0]["children"][1]["title"] == "Algebra"


def test_obvious_chunk_mapping_and_unmatched_coverage(db_session):
    user = User(email="syllabus@test.local", full_name="Test", password_hash="hash")
    db_session.add(user)
    db_session.flush()
    doc = Document(owner_id=user.id, title="notes.pdf", status="ready")
    syllabus = Syllabus(owner_id=user.id, title="Course")
    db_session.add_all([doc, syllabus])
    db_session.flush()
    calculus = SyllabusTopic(
        syllabus_id=syllabus.id, title="Calculus", keywords=["derivative"]
    )
    unmatched = SyllabusTopic(syllabus_id=syllabus.id, title="Organic chemistry")
    db_session.add_all([calculus, unmatched])
    db_session.flush()
    chunk = Chunk(
        doc_id=doc.id,
        page=1,
        page_start=1,
        page_end=1,
        text="Calculus derivative rules",
        token_count=4,
    )
    db_session.add(chunk)
    db_session.flush()
    remap_syllabus(db_session, syllabus, user.id, FakeEmbedder(), threshold=0.7)
    mappings = list(db_session.query(ChunkTopic).all())
    assert [(mapping.topic_id, mapping.source) for mapping in mappings] == [
        (calculus.id, "auto")
    ]
    result = coverage(db_session, syllabus.id)
    assert result["topics"][0]["chunks"] == 1
    assert result["topics"][1]["status"] == "no material"


def test_manual_mapping_survives_auto_remap(db_session):
    user = User(email="manual@test.local", full_name="Manual", password_hash="hash")
    db_session.add(user)
    db_session.flush()
    doc = Document(owner_id=user.id, title="notes.pdf", status="ready")
    syllabus = Syllabus(owner_id=user.id, title="Private")
    db_session.add_all([doc, syllabus])
    db_session.flush()
    topic = SyllabusTopic(syllabus_id=syllabus.id, title="Organic chemistry")
    db_session.add(topic)
    db_session.flush()
    chunk = Chunk(
        doc_id=doc.id,
        page=1,
        page_start=1,
        page_end=1,
        text="Calculus derivatives",
        token_count=2,
    )
    db_session.add(chunk)
    db_session.flush()
    manual = ChunkTopic(
        chunk_id=chunk.id,
        topic_id=topic.id,
        source="manual",
        score=1.0,
        page_start=1,
        page_end=1,
    )
    db_session.add(manual)
    db_session.flush()
    remap_syllabus(db_session, syllabus, user.id, FakeEmbedder(), threshold=0.7)
    assert manual in db_session.query(ChunkTopic).all()


def test_syllabus_owner_isolation(client, db_session):
    owner = User(email="owner@test.local", full_name="Owner", password_hash="hash")
    other = User(email="other@test.local", full_name="Other", password_hash="hash")
    db_session.add_all([owner, other])
    db_session.flush()
    syllabus = Syllabus(owner_id=owner.id, title="Private")
    db_session.add(syllabus)
    db_session.flush()
    db_session.add(SyllabusTopic(syllabus_id=syllabus.id, title="Topic"))
    db_session.commit()
    response = client.get(
        f"/syllabi/{syllabus.id}",
        headers={"Authorization": f"Bearer {access_token_for(other.id)}"},
    )
    assert response.status_code == 404


def test_private_syllabus_opt_in_never_triggers_web_search(
    client, db_session, monkeypatch
):
    owner = User(
        email="private-web-syllabus@test.local",
        full_name="Owner",
        password_hash="hash",
    )
    db_session.add(owner)
    db_session.flush()
    doc = Document(
        owner_id=owner.id,
        title="Private course",
        status="ready",
        is_private=True,
    )
    db_session.add(doc)
    db_session.flush()
    db_session.add(DocumentPage(document_id=doc.id, page_number=1, text=""))
    db_session.commit()
    calls = []
    monkeypatch.setattr(
        "app.services.web_search.search_web",
        lambda *args, **kwargs: calls.append(args) or ([], None),
    )
    response = client.post(
        "/syllabi",
        headers={"Authorization": f"Bearer {access_token_for(owner.id)}"},
        json={"title": "Private course", "document_id": doc.id, "use_web_search": True},
    )
    assert response.status_code == 200, response.text
    assert calls == []
    assert response.json()["sources"]["web"] == []


def test_public_syllabus_stores_web_items_separately(client, db_session, monkeypatch):
    owner = User(
        email="public-web-syllabus@test.local",
        full_name="Owner",
        password_hash="hash",
    )
    db_session.add(owner)
    db_session.flush()
    doc = Document(
        owner_id=owner.id,
        title="Public course",
        status="ready",
        is_private=False,
    )
    db_session.add(doc)
    db_session.flush()
    db_session.add(DocumentPage(document_id=doc.id, page_number=1, text=""))
    db_session.commit()
    source = {
        "title": "Course reference",
        "url": "https://example.test/course",
        "domain": "example.test",
        "snippet": "A fetched course topic sentence.",
    }
    monkeypatch.setattr(
        "app.services.web_search.search_web", lambda *_args: ([source], None)
    )
    response = client.post(
        "/syllabi",
        headers={"Authorization": f"Bearer {access_token_for(owner.id)}"},
        json={"title": "Public course", "document_id": doc.id, "use_web_search": True},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["sources"]["web"] == [source]
    assert payload["web_items"][0]["url"] == source["url"]
    assert payload["web_items"][0]["quote"] == source["snippet"]
    saved = client.get(
        f"/syllabi/{payload['id']}",
        headers={"Authorization": f"Bearer {access_token_for(owner.id)}"},
    )
    assert saved.json()["sources"]["web"] == [source]
