"""Authenticated search and rechunk endpoint tests."""

from conftest import access_token_for
from fastapi.testclient import TestClient

from app.models import Chunk, Document, DocumentPage, User


def _headers(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token_for(user_id)}"}


def _add_document(db_session, owner_id: int, title: str, text: str) -> Document:
    document = Document(owner_id=owner_id, title=title, status="ready")
    db_session.add(document)
    db_session.flush()
    db_session.add(
        DocumentPage(
            document_id=document.id,
            page_number=1,
            text=text,
            headings=[{"text": "Study Notes"}],
        )
    )
    db_session.add(
        Chunk(
            doc_id=document.id,
            page=1,
            page_start=1,
            page_end=1,
            chunk_index=0,
            section="Study Notes",
            text=text,
            token_count=len(text.split()),
        )
    )
    db_session.flush()
    return document


def test_search_supports_both_modes_and_only_owned_documents(
    client: TestClient, db_session
) -> None:
    owner = User(
        email="search-owner@example.com",
        full_name="Search Owner",
        password_hash="unused",
    )
    stranger = User(
        email="search-stranger@example.com",
        full_name="Search Stranger",
        password_hash="unused",
    )
    db_session.add_all([owner, stranger])
    db_session.flush()
    own_document = _add_document(
        db_session,
        owner.id,
        "My notes",
        "Photosynthesis converts sunlight using chlorophyll in green plants.",
    )
    foreign_document = _add_document(
        db_session,
        stranger.id,
        "Private notes",
        "Photosynthesis secret private chlorophyll data.",
    )
    db_session.commit()
    headers = _headers(owner.id)

    for mode in ("tfidf", "bm25"):
        response = client.post(
            "/search",
            headers=headers,
            json={
                "query": "photosynthesis chlorophyll",
                "mode": mode,
                "k": 5,
            },
        )
        assert response.status_code == 200
        result = response.json()["results"][0]
        assert result["document_id"] == own_document.id
        assert result["page"] == 1
        assert result["page_start"] == 1
        assert result["page_end"] == 1
        assert result["section"] == "Study Notes"
        assert result["score"] > 0

    denied = client.post(
        "/search",
        headers=headers,
        json={
            "query": "private",
            "mode": "tfidf",
            "doc_ids": [foreign_document.id],
        },
    )
    assert denied.status_code == 404
    assert (
        client.post(
            "/search",
            headers=headers,
            json={"query": "   ", "mode": "tfidf"},
        ).status_code
        == 422
    )


def test_rechunk_endpoint_rebuilds_only_an_owned_document(
    client: TestClient, db_session
) -> None:
    owner = User(
        email="rechunk-owner@example.com",
        full_name="Rechunk Owner",
        password_hash="unused",
    )
    stranger = User(
        email="rechunk-stranger@example.com",
        full_name="Rechunk Stranger",
        password_hash="unused",
    )
    db_session.add_all([owner, stranger])
    db_session.flush()
    own_document = _add_document(
        db_session,
        owner.id,
        "My notes",
        "First sentence has several words. Second sentence has several words.",
    )
    foreign_document = _add_document(
        db_session,
        stranger.id,
        "Private notes",
        "Another person's document.",
    )
    db_session.commit()

    response = client.post(
        f"/documents/{own_document.id}/rechunk",
        headers=_headers(owner.id),
        json={"chunk_size": 5, "overlap": 1},
    )

    assert response.status_code == 200
    assert response.json()["document_id"] == own_document.id
    assert len(response.json()["chunks"]) > 1
    assert all(chunk["token_count"] <= 5 for chunk in response.json()["chunks"])
    assert (
        client.post(
            f"/documents/{foreign_document.id}/rechunk",
            headers=_headers(owner.id),
            json={"chunk_size": 5, "overlap": 1},
        ).status_code
        == 404
    )
