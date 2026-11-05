"""Fake-only tests for grounded glossary and owner-scoped flashcards."""

from datetime import UTC, datetime, timedelta

from app.models import (
    Chunk,
    Document,
    DocumentKeyTerm,
    DocumentPage,
    Flashcard,
    FlashcardReviewLog,
    GlossaryTerm,
    Question,
    Quiz,
    User,
)
from app.services.study.sm2 import schedule_review
from tests.conftest import access_token_for


def _user(db_session, name: str) -> User:
    user = User(
        email=f"{name}@example.test",
        full_name=name,
        password_hash="unused",
    )
    db_session.add(user)
    db_session.flush()
    return user


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token_for(user.id)}"}


def _document(db_session, owner: User, title: str = "Study notes") -> Document:
    document = Document(owner_id=owner.id, title=title, status="ready")
    db_session.add(document)
    db_session.flush()
    return document


def test_sm2_good_sequence_again_and_minimum_ease():
    now = datetime(2026, 11, 6, tzinfo=UTC)
    ease, interval, repetitions = 2.5, 0, 0
    result = schedule_review(
        ease=ease, interval=interval, repetitions=repetitions, quality=4, now=now
    )
    assert result.interval == 1
    ease, interval, repetitions = result.ease, result.interval, result.repetitions

    result = schedule_review(
        ease=ease, interval=interval, repetitions=repetitions, quality=4, now=now
    )
    assert result.interval == 6
    ease, interval, repetitions = result.ease, result.interval, result.repetitions

    result = schedule_review(
        ease=ease, interval=interval, repetitions=repetitions, quality=4, now=now
    )
    assert result.interval == round(6 * result.ease)
    ease, interval, repetitions = result.ease, result.interval, result.repetitions

    result = schedule_review(
        ease=ease, interval=interval, repetitions=repetitions, quality=0, now=now
    )
    assert result.interval == 1
    assert result.repetitions == 0

    for _ in range(10):
        result = schedule_review(
            ease=result.ease,
            interval=result.interval,
            repetitions=result.repetitions,
            quality=0,
            now=now,
        )
    assert result.ease == 1.3


def test_due_cards_include_past_and_today_but_not_future_or_suspended(
    client, db_session
):
    owner = _user(db_session, "due-owner")
    document = _document(db_session, owner)
    now = datetime.now(UTC)
    cards = [
        Flashcard(
            owner_id=owner.id,
            document_id=document.id,
            front=f"Card {label}",
            back="Answer",
            due_at=due_at,
            suspended=suspended,
        )
        for label, due_at, suspended in (
            ("past", now - timedelta(days=1), False),
            ("today", now, False),
            ("future", now + timedelta(days=1), False),
            ("suspended", now - timedelta(days=1), True),
        )
    ]
    db_session.add_all(cards)
    db_session.commit()

    response = client.get("/study/flashcards/due", headers=_headers(owner))

    assert response.status_code == 200
    assert {item["front"] for item in response.json()} == {"Card past", "Card today"}


def test_generation_is_idempotent_and_uses_accepted_questions_and_glossary(
    client, db_session
):
    owner = _user(db_session, "generation-owner")
    document = _document(db_session, owner)
    first = "Attention is a mechanism that lets a model focus on relevant tokens."
    second = "Transformers process token sequences using self-attention."
    third = "Self-attention is an attention mechanism that relates sequence positions."
    db_session.add_all(
        [
            DocumentPage(
                document_id=document.id, page_number=1, text=f"{first} {second}"
            ),
            DocumentPage(document_id=document.id, page_number=2, text=third),
            DocumentKeyTerm(
                document_id=document.id,
                term="Self-attention",
                label="KEYPHRASE",
                page=2,
                source="keyphrase",
            ),
        ]
    )
    db_session.flush()
    chunk = Chunk(
        doc_id=document.id,
        page=1,
        page_start=1,
        page_end=1,
        text=f"{first} {second}",
        token_count=20,
        chunk_index=0,
    )
    quiz = Quiz(
        owner_id=owner.id,
        title="Accepted questions",
        source_document_id=document.id,
    )
    db_session.add_all([chunk, quiz])
    db_session.flush()
    db_session.add_all(
        [
            Question(
                quiz_id=quiz.id,
                type="fill_in_the_blank",
                difficulty="easy",
                prompt="Fill in the blank: _____ lets models focus on relevant tokens.",
                answer="Attention",
                options={"evidence": first, "document_id": document.id},
                page=1,
                source_chunk_id=chunk.id,
            ),
            Question(
                quiz_id=quiz.id,
                type="short_answer",
                difficulty="easy",
                prompt="What architecture processes token sequences?",
                answer="Transformers",
                options={"evidence": second, "document_id": document.id},
                page=1,
                source_chunk_id=chunk.id,
            ),
            Question(
                quiz_id=quiz.id,
                type="short_answer",
                difficulty="easy",
                prompt="Which model is mentioned?",
                answer="Transformers",
                options={"evidence": second, "document_id": document.id},
                page=1,
                source_chunk_id=chunk.id,
            ),
        ]
    )
    db_session.commit()

    headers = _headers(owner)
    glossary_path = f"/study/documents/{document.id}/glossary/regenerate"
    glossary_response = client.post(glossary_path, headers=headers)
    assert glossary_response.status_code == 200
    assert glossary_response.json()["generated"] == 1
    path = f"/study/documents/{document.id}/flashcards/generate"
    first_response = client.post(path, headers=headers)
    second_response = client.post(path, headers=headers)

    assert first_response.status_code == 201
    assert first_response.json()["created"] == 3
    assert second_response.status_code == 201
    assert second_response.json()["created"] == 0
    assert db_session.query(Flashcard).filter_by(document_id=document.id).count() == 3


def test_regenerated_glossary_definitions_are_exact_page_sentences(client, db_session):
    owner = _user(db_session, "glossary-owner")
    document = _document(db_session, owner)
    texts = {
        1: "A neural network is a model made of connected units.",
        2: "Backpropagation means computing gradients to update model weights.",
    }
    db_session.add_all(
        [
            DocumentPage(document_id=document.id, page_number=page, text=text)
            for page, text in texts.items()
        ]
    )
    db_session.add_all(
        [
            DocumentKeyTerm(
                document_id=document.id,
                term=term,
                label="KEYPHRASE",
                page=page,
                source="keyphrase",
            )
            for page, term in ((1, "neural network"), (2, "Backpropagation"))
        ]
    )
    db_session.commit()

    response = client.post(
        f"/study/documents/{document.id}/glossary/regenerate",
        headers=_headers(owner),
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 2
    for item in items:
        assert item["definition"] == item["evidence_sentence"]
        assert item["evidence_sentence"] in texts[item["page"]]


def test_custom_glossary_terms_are_grounded_and_can_be_edited(client, db_session):
    owner = _user(db_session, "custom-owner")
    document = _document(db_session, owner)
    text = "A recurrent neural network processes sequential data."
    db_session.add_all(
        [
            DocumentPage(document_id=document.id, page_number=1, text=text),
            DocumentPage(
                document_id=document.id,
                page_number=2,
                text="Training is important.",
            ),
        ]
    )
    db_session.commit()

    created = client.post(
        f"/study/documents/{document.id}/glossary",
        headers=_headers(owner),
        json={"term": "recurrent neural network"},
    )
    assert created.status_code == 201
    assert created.json()["evidence_sentence"] == text

    ungrounded = client.post(
        f"/study/documents/{document.id}/glossary",
        headers=_headers(owner),
        json={"term": "AI"},
    )
    assert ungrounded.status_code == 422

    edited = client.patch(
        f"/study/glossary/{created.json()['id']}",
        headers=_headers(owner),
        json={"term": "neural network"},
    )
    assert edited.status_code == 200
    assert edited.json()["evidence_sentence"] == text


def test_users_cannot_read_or_review_another_users_cards_or_glossary(
    client, db_session
):
    owner = _user(db_session, "isolation-owner")
    other = _user(db_session, "isolation-other")
    document = _document(db_session, owner)
    card = Flashcard(
        owner_id=owner.id,
        document_id=document.id,
        front="Question",
        back="Answer",
        due_at=datetime.now(UTC),
    )
    term = GlossaryTerm(
        owner_id=owner.id,
        document_id=document.id,
        term="Attention",
        term_key="attention",
        definition="Attention is a mechanism.",
        page=1,
        evidence_sentence="Attention is a mechanism.",
        source="custom",
        importance=1.0,
    )
    db_session.add_all([card, term])
    db_session.commit()

    due = client.get("/study/flashcards/due", headers=_headers(other))
    review = client.post(
        f"/study/flashcards/{card.id}/review",
        headers=_headers(other),
        json={"rating": "Good"},
    )
    glossary = client.get(
        f"/study/documents/{document.id}/glossary",
        headers=_headers(other),
    )

    assert due.status_code == 200
    assert due.json() == []
    assert review.status_code == 404
    assert glossary.status_code == 404


def test_review_endpoint_maps_rating_and_persists_review_log(client, db_session):
    owner = _user(db_session, "review-owner")
    document = _document(db_session, owner)
    card = Flashcard(
        owner_id=owner.id,
        document_id=document.id,
        front="Question",
        back="Answer",
        due_at=datetime.now(UTC),
    )
    db_session.add(card)
    db_session.commit()

    response = client.post(
        f"/study/flashcards/{card.id}/review",
        headers=_headers(owner),
        json={"rating": "Good"},
    )

    assert response.status_code == 200
    assert response.json()["quality"] == 4
    assert response.json()["card"]["interval"] == 1
    assert (
        db_session.query(FlashcardReviewLog)
        .filter_by(flashcard_id=card.id, rating="Good", quality=4)
        .count()
        == 1
    )
